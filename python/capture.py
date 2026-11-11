"""Captured Recordings for the beta (see docs/specs/beta-telemetry-and-updates.md).

A Captured Recording is a Recording copied in full to the Cora team for
accuracy review, because it was rated (Feedback) or fell in the sample. This
module keeps the local queue (`captures` table) and builds the archive; the
upload itself is python/beta_sender.py's. Nothing is queued under enterprise
lockdown or while sharing is off.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import random
import re
import sqlite3
import tarfile
import tempfile
from pathlib import Path

import db
import paths

# What a Captured Recording holds, by file name at the top of the Recording
# folder; nothing else in the folder is ever archived (no playback mix,
# screenshots, OCR, earlier versions; manual notes live in the DB).
AUDIO_TRACKS = re.compile(r"audio\.(m4a|mp3|wav|aiff|aif|mp4|caf|mov)")  # the mic + system multi-track original
ARCHIVED_FILES = (
    "transcript_diarized.md", "diarization.json", "gemini_diarization.json",  # transcript
    "speakers_timeline.json",                                                 # speaker timeline
    "participants.json",                                                      # Participants roster
    "enhanced_notes.md", "call_summary.json",                                 # generated notes
    "metadata.json",                                                          # Recording metadata
)
REASONS = ("feedback", "sample")
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,200}")  # what the receiver accepts as a recording id
MAX_AGE = dt.timedelta(days=7)  # a capture the receiver did not take by then is dropped
RUN_METADATA = "run_metadata.json"  # this Recording's pipeline runs from traces.db, built at archive time
SPAN_CONTENT = ("input", "output")  # prompt and response text stay out of run metadata


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- the queue ----------------------------------------------------------------------

def request(recording_id: str, reason: str) -> bool:
    """Queue a Recording for capture. True if this call queued it; False if
    it was already asked for (whatever became of it) or sharing is off
    (toggle, enterprise lockdown, no receiver in this build). ValueError for
    an id or reason the receiver would refuse."""
    import usage_events
    if reason not in REASONS:
        raise ValueError(f"capture reason must be one of {REASONS}")
    if not isinstance(recording_id, str) or not SAFE_ID.fullmatch(recording_id) or recording_id in (".", ".."):
        raise ValueError(f"unsafe recording id {recording_id!r}")
    if not usage_events.sharing_enabled():
        return False
    with db.get_db() as conn:
        cur = conn.execute("INSERT OR IGNORE INTO captures (recording_id, reason, requested_at) VALUES (?, ?, ?)",
                           (recording_id, reason, _iso(_now())))
        conn.commit()
        return cur.rowcount == 1


def sample(payload: dict) -> bool:
    """Called for every `processing_finished` event: capture the Recording if
    its id's seeded draw falls under the remote config's sample rate and it is
    shorter than the length cap. The same Recording always draws the same
    number, so reprocessing never re-rolls it. True if this queued it."""
    import beta_sender
    recording_id, duration_s = payload.get("recording_id"), payload.get("duration_s")
    if not isinstance(recording_id, str) or isinstance(duration_s, bool) \
            or not isinstance(duration_s, (int, float)):
        return False
    config = beta_sender.remote_config()
    if random.Random(recording_id).random() >= config["capture_sample_rate"]:
        return False
    if duration_s / 60 >= config["capture_max_minutes"]:
        return False
    try:
        return request(recording_id, "sample")
    except ValueError:
        return False


_PENDING = "uploaded_at IS NULL AND dropped_at IS NULL"


def next_pending():
    """The oldest capture still to upload (a row with recording_id and reason), or None."""
    with db.get_db() as conn:
        return conn.execute(f"SELECT recording_id, reason, requested_at FROM captures WHERE {_PENDING}"
                            " ORDER BY requested_at, rowid LIMIT 1").fetchone()


def has_pending(recording_id: str) -> bool:
    """Whether this Recording waits for upload (audio pruning leaves it alone)."""
    with db.get_db() as conn:
        return conn.execute(f"SELECT 1 FROM captures WHERE recording_id = ? AND {_PENDING}",
                            (recording_id,)).fetchone() is not None


def pending_count() -> int:
    with db.get_db() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM captures WHERE {_PENDING}").fetchone()[0]


def mark_uploaded(recording_id: str) -> None:
    with db.get_db() as conn:
        conn.execute("UPDATE captures SET uploaded_at = ? WHERE recording_id = ? AND uploaded_at IS NULL",
                     (_iso(_now()), recording_id))
        conn.commit()


def drop_expired() -> int:
    """Drop captures still not uploaded more than 7 days after they were
    asked for, recording one `capture_dropped` event each. Returns how many."""
    import usage_events
    now = _now()
    with db.get_db() as conn:
        expired = conn.execute(f"SELECT recording_id, reason FROM captures WHERE {_PENDING}"
                               " AND requested_at < ? ORDER BY requested_at, rowid",
                               (_iso(now - MAX_AGE),)).fetchall()
        for row in expired:
            conn.execute("UPDATE captures SET dropped_at = ? WHERE recording_id = ?",
                         (_iso(now), row["recording_id"]))
        conn.commit()
    for row in expired:
        usage_events.record("capture_dropped", {"recording_id": row["recording_id"], "reason": row["reason"]})
    return len(expired)


# ---- the archive --------------------------------------------------------------------

def _folder(recording_id: str) -> Path:
    recording = db.get_recording(recording_id)
    if not recording or not recording.get("folder_path"):
        raise FileNotFoundError(f"no Recording {recording_id}")
    folder = Path(recording["folder_path"])
    if not folder.is_dir():
        raise FileNotFoundError(f"Recording folder missing: {folder}")
    return folder


def _run_metadata(recording_id: str) -> bytes:
    import ai_trace
    runs, spans = [], []
    if ai_trace.TRACE_DB.exists():
        conn = sqlite3.connect(ai_trace.TRACE_DB, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            runs = [dict(r) for r in conn.execute(
                "SELECT * FROM runs WHERE recording_id = ? ORDER BY started_at", (recording_id,))]
            spans = [{k: r[k] for k in r.keys() if k not in SPAN_CONTENT} for r in conn.execute(
                "SELECT * FROM spans WHERE recording_id = ? ORDER BY started_at", (recording_id,))]
        except sqlite3.OperationalError:
            pass  # no trace tables yet
        finally:
            conn.close()
    return json.dumps({"recording_id": recording_id, "runs": runs, "spans": spans}, indent=2).encode()


def build_archive(recording_id: str) -> Path:
    """A tar.gz of the Recording's audio tracks, transcript, speaker timeline,
    Participants, generated notes and run metadata, in a temp file under the
    data dir. The caller deletes it. FileNotFoundError if the Recording is gone."""
    folder = _folder(recording_id)
    names = sorted(p.name for p in folder.iterdir()
                   if p.is_file() and (AUDIO_TRACKS.fullmatch(p.name) or p.name in ARCHIVED_FILES))
    fd, tmp = tempfile.mkstemp(prefix=".capture-", suffix=".tar.gz", dir=paths.DATA_DIR)
    os.close(fd)
    archive = Path(tmp)
    try:
        with tarfile.open(archive, "w:gz") as tar:
            for name in names:
                tar.add(folder / name, arcname=name, recursive=False)
            data = _run_metadata(recording_id)
            info = tarfile.TarInfo(RUN_METADATA)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
    return archive
