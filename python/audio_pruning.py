"""Audio pruning for the beta (see docs/specs/beta-telemetry-and-updates.md).

A pass deletes the audio of Recordings older than `audio_retention_days`,
then, while all audio together is over `audio_cap_mb`, the audio of the
oldest Recordings left. Only audio goes: the original multi-track
`audio.<ext>`, the playback mix and the transcription WAVs (including the
copies earlier versions kept). Transcript, notes, timeline, Participants and
screenshots stay. A Recording that is live, processing, failed, being
continued or waiting to be captured is never touched. The Recording's
metadata records `audio_pruned_at` (with the reason and the limit then in
force) so the notes view can say why the player is gone.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

import db

INTERVAL_S = 6 * 60 * 60  # fallback timer between passes
LOG_NAME = "audio_pruning.jsonl"
_lock = threading.Lock()  # one pass at a time
_wake, _stop = threading.Event(), threading.Event()
_thread: threading.Thread | None = None

AUDIO_NAMES = re.compile(r"audio\.[A-Za-z0-9]+|playback\.m4a|audio_transcribed\.[A-Za-z0-9]+")
VERSIONED_AUDIO = re.compile(r"audio_transcribed\.[A-Za-z0-9]+")
MB = 1024 * 1024


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def audio_files(folder: Path) -> list[Path]:
    """The audio in a Recording folder: top-level tracks and derived copies,
    plus the transcription WAVs kept under versions/."""
    if not folder.is_dir():
        return []
    found = [p for p in folder.iterdir() if p.is_file() and AUDIO_NAMES.fullmatch(p.name)]
    versions = folder / "versions"
    if versions.is_dir():
        found += [p for p in versions.glob("*/*") if p.is_file() and VERSIONED_AUDIO.fullmatch(p.name)]
    return found


def _size(paths: list[Path]) -> int:
    total = 0
    for p in paths:
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _recorded_at(recording: dict, folder: Path) -> dt.datetime:
    raw = recording.get("recorded_at") or ""
    try:
        when = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return when if when.tzinfo else when.astimezone()
    except ValueError:
        try:
            return dt.datetime.fromtimestamp(folder.stat().st_mtime, dt.timezone.utc)
        except OSError:
            return _now()


def _setting(key: str) -> int:
    from api.routes.settings import read_setting
    return int(read_setting(key))


# needs_diarization: never processed, so the audio is all there is of it.
SKIPPED_STAGES = frozenset({"recording", "paused", "processing", "failed", "needs_diarization"})


def _untouchable(recording: dict) -> bool:
    """Live (recording/paused), processing, failed or never processed, being continued (its
    audio is about to be merged), a transient Continuation, or waiting to
    be uploaded as a Captured Recording."""
    import capture
    import recording_stage
    meta = recording.get("metadata") or {}
    return (recording_stage.stage(recording) in SKIPPED_STAGES
            or bool(meta.get("continuation_status")) or bool(meta.get("continues_recording_id"))
            or capture.has_pending(recording["id"]))


def _prune(recording_id: str, files: list[Path], reason: str, limit: int, now: dt.datetime) -> int | None:
    """Delete the files and flag the Recording; None (nothing deleted) if it
    became untouchable since the pass looked (a reprocess started, say)."""
    fresh = db.get_recording(recording_id)
    if not fresh or _untouchable(fresh):
        return None
    freed = 0
    for path in files:
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except FileNotFoundError:
            pass
    db.set_recording_metadata(recording_id, audio_pruned_at=now.isoformat(timespec="seconds"),
                              audio_pruned_reason=reason, audio_pruned_limit=limit)
    return freed


def run_pass() -> dict:
    """One pruning pass. Returns {removed, by_age, by_cap, skipped, bytes_freed}."""
    now = _now()
    days, cap_mb = _setting("audio_retention_days"), _setting("audio_cap_mb")
    counts = {"removed": 0, "by_age": 0, "by_cap": 0, "skipped": 0, "bytes_freed": 0}
    candidates, untouchable_bytes, pruned = [], 0, []
    for recording in db.get_all_recordings():
        folder = Path(recording.get("folder_path") or "")
        if not recording.get("folder_path") or not folder.is_dir():
            continue
        files = audio_files(folder)
        if not files:
            continue
        if _untouchable(recording):
            counts["skipped"] += 1
            untouchable_bytes += _size(files)  # still on disk, so still under the cap
            continue
        candidates.append((_recorded_at(recording, folder), recording["id"], files))
    candidates.sort(key=lambda c: c[0])
    cutoff = now - dt.timedelta(days=days)
    remaining = []
    for when, recording_id, files in candidates:
        freed = _prune(recording_id, files, "retention", days, now) if when < cutoff else None
        if freed is None:
            remaining.append((recording_id, files))
        else:
            counts["bytes_freed"] += freed
            counts["by_age"] += 1
            pruned.append({"recording_id": recording_id, "reason": "retention", "bytes": freed})
    total = untouchable_bytes + sum(_size(files) for _, files in remaining)
    for recording_id, files in remaining:  # oldest first
        if total <= cap_mb * MB:
            break
        freed = _prune(recording_id, files, "cap", cap_mb, now)
        if freed is None:
            continue
        counts["bytes_freed"] += freed
        counts["by_cap"] += 1
        pruned.append({"recording_id": recording_id, "reason": "cap", "bytes": freed})
        total -= freed
    counts["removed"] = counts["by_age"] + counts["by_cap"]
    if counts["removed"]:
        n = counts["removed"]
        db.log_notification("Audio removed to save space",
                            f"Audio removed from {n} recording{'s' if n != 1 else ''} to save space."
                            " Transcripts and notes are kept.")
    _log({"at": now.isoformat(timespec="seconds"), "retention_days": days, "cap_mb": cap_mb, **counts,
          "pruned": pruned})
    return counts


def _log(entry: dict) -> None:
    """One JSONL line per pass in <data>/logs/audio_pruning.jsonl (local only)."""
    import paths
    print(f"[Audio pruning] {entry}", flush=True)
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(paths.LOGS_DIR / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---- when passes run ---------------------------------------------------------------

def _disabled() -> bool:
    """Automatic passes are off in the test suite (tests call run_pass)."""
    return os.environ.get("CORA_AUDIO_PRUNING_DISABLED") == "1"


def _safe_pass() -> None:
    with _lock:
        try:
            run_pass()
        except Exception as e:  # noqa: BLE001 - pruning never takes the server down
            _log({"at": _now().isoformat(timespec="seconds"), "error": f"{type(e).__name__}: {e}"})


def _run() -> None:
    while not _stop.is_set():
        _safe_pass()
        _wake.wait(INTERVAL_S)
        _wake.clear()


def start() -> None:
    """Run a pass now on a background thread, then again after every
    processing job (trigger) and every 6 hours as a fallback."""
    global _thread
    if _disabled() or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="audio-pruning", daemon=True)
    _thread.start()


def trigger() -> None:
    """A processing job ended: run a pass soon, off the caller's thread."""
    if _disabled():
        return
    if _thread and _thread.is_alive():
        _wake.set()
    else:
        threading.Thread(target=_safe_pass, name="audio-pruning-once", daemon=True).start()


def stop() -> None:
    _stop.set()
    _wake.set()
