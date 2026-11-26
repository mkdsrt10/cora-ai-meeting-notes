"""Live transcript files (GLOSSARY "Live transcript"; docs/specs/live-transcript.md).

Electron's Recording session writes one JSONL file per Recording session while
it records: ``inbox/<first chunk id>_live.jsonl`` (src/recording/live-transcript.js).
When that chunk is imported the file moves into the Recording folder as
``live_transcript.jsonl`` and stays there beside the full transcript: it
follows the Recording's retention, is deleted with the folder, is never part
of an Export, and is included in a Captured Recording.

Not to be confused with ``views.live_transcript_payload``: that is the
Speaker timeline feed (speaker changes, screenshots), which predates this.

Each line: {recording_id (the Chunk), track ('mic'|'sys'), speaker, start, end,
text, final, engine, seg, lag_ms}. Readers take only complete lines (the writer may be
mid-append), so a cursor is a byte offset just past the last line returned.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import paths

FILE_NAME = "live_transcript.jsonl"
INBOX_SUFFIX = "_live.jsonl"
# Draft notes made from the Live transcript at stop (live_draft_notes.py); shown,
# marked "Draft", until the full notes exist. Same life cycle as the file above.
DRAFT_NAME = "draft_notes.md"
DRAFT_INBOX_SUFFIX = "_draft_notes.md"
MAX_READ_BYTES = 2 * 1024 * 1024


def _valid_id(recording_id: str) -> bool:
    import re
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", recording_id or ""))


def inbox_path(key: str) -> Path:
    return paths.INBOX_DIR / f"{key}{INBOX_SUFFIX}"


def folder_path(folder: Path) -> Path:
    return Path(folder) / FILE_NAME


def path_for(recording_id: str) -> Path | None:
    """The Live transcript of a Recording, wherever it is now: the Recording
    folder once imported, else the inbox (recording, or processing failed
    before import). A live id (meeting_<timestamp>) that was archived under a
    new folder id resolves through the DB, like GET /api/recording does."""
    if not _valid_id(recording_id):
        return None
    candidates = [paths.RECORDINGS_DIR / recording_id / FILE_NAME, inbox_path(recording_id)]
    try:
        import db
        rec = db.get_recording(recording_id) or db.get_recording_by_live_id(recording_id)
    except Exception:
        rec = None
    if rec:
        rec_id = str(rec.get("id") or "")
        meta = rec.get("metadata") or {}
        live_id = str(meta.get("live_recording_id") or "")
        stem = str(meta.get("source_stem") or "")
        # A later Chunk of a pause/resume chain: the file belongs to the first one.
        root = str(meta.get("continues_recording_id") or "")
        for other in (rec_id, live_id, stem, root):
            if other and other != recording_id and _valid_id(other):
                candidates += [paths.RECORDINGS_DIR / other / FILE_NAME, inbox_path(other)]
    root = paths.RECORDINGS_DIR.resolve()
    inbox = paths.INBOX_DIR.resolve()
    for path in candidates:
        resolved = path.resolve()
        if (resolved.is_relative_to(root) or resolved.is_relative_to(inbox)) and resolved.is_file():
            return resolved
    return None


def read(path: Path | None, since: int = 0, *, finals_only: bool = False) -> tuple[list[dict[str, Any]], int]:
    """Lines after byte offset `since`, and the cursor just past them. A
    malformed line is skipped (its bytes still advance the cursor)."""
    if path is None:
        return [], max(0, int(since or 0))
    since = max(0, int(since or 0))
    try:
        size = path.stat().st_size
    except OSError:
        return [], since
    if since >= size:
        return [], min(since, size)
    with path.open("rb") as fh:
        fh.seek(since)
        data = fh.read(MAX_READ_BYTES)
    end = data.rfind(b"\n")
    if end < 0:
        return [], since
    lines = []
    for raw in data[:end].split(b"\n"):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("text"), str):
            continue
        if finals_only and not obj.get("final"):
            continue
        lines.append(obj)
    return lines, since + end + 1


def read_all(recording_id: str) -> list[dict[str, Any]]:
    return read_all_path(path_for(recording_id))


def draft_inbox_path(key: str) -> Path:
    return paths.INBOX_DIR / f"{key}{DRAFT_INBOX_SUFFIX}"


def adopt(source_stem: str, folder: Path) -> bool:
    """Import: move inbox/<stem>_live.jsonl (and its draft notes) into the
    Recording folder. Only the first chunk of a Recording session has them.
    Never raises. True when a Live transcript moved."""
    if not _valid_id(source_stem):
        return False
    moved = False
    for source, target in ((inbox_path(source_stem), folder_path(folder)),
                           (draft_inbox_path(source_stem), Path(folder) / DRAFT_NAME)):
        if not source.is_file():
            continue
        try:
            shutil.copy2(source, target)
            source.unlink(missing_ok=True)
            moved = moved or target.name == FILE_NAME
        except OSError:
            pass
    return moved


def merge_into(child_folder: Path, parent_folder: Path, offset_s: float) -> None:
    """A Continuation merged into its parent: its Live transcript lines are
    appended to the parent's, shifted by where its audio starts, so one call
    keeps one live record. The child folder is deleted by the caller."""
    child = folder_path(child_folder)
    if not child.is_file():
        return
    lines = read_all_path(child)
    if not lines:
        return
    with folder_path(parent_folder).open("a", encoding="utf-8") as out:
        for line in lines:
            for key in ("start", "end"):
                try:
                    line[key] = round(float(line.get(key) or 0) + float(offset_s), 3)
                except (TypeError, ValueError):
                    pass
            out.write(json.dumps(line, ensure_ascii=False) + "\n")


def read_all_path(path: Path | None) -> list[dict[str, Any]]:
    lines, cursor = read(path)
    while path is not None:
        more, nxt = read(path, cursor)
        if nxt == cursor:
            break
        lines += more
        cursor = nxt
    return lines


def draft_notes(recording_id: str) -> str | None:
    """The draft notes of a Recording, if any were made (folder, else inbox)."""
    live = path_for(recording_id)
    if live is None:
        return None
    candidate = live.parent / DRAFT_NAME if live.name == FILE_NAME else draft_inbox_path(live.name[: -len(INBOX_SUFFIX)])
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def transcript_view(status: str | None, *, has_full: bool, has_live: bool, live_on: bool = False) -> dict[str, Any]:
    """Which transcript the UI shows for a Recording, and its label. One rule,
    no user toggle (spec "Which transcript is shown"):
      recording/paused  -> the Live transcript as captions (when live is on or a file exists)
      full transcript   -> the full transcript
      failed            -> the Live transcript as "Draft transcript", with Retry
      still processing  -> the Live transcript as "Draft transcript"
    status: the pending status or the analysis stage ('failed' for a failed run)."""
    if status in ("recording", "paused"):
        if has_live or live_on:
            return {"source": "live", "label": "Live captions", "retry": False}
        return {"source": "none", "label": "Transcript", "retry": False}
    if has_full:
        return {"source": "full", "label": "Transcript", "retry": False}
    if has_live:
        return {"source": "live", "label": "Draft transcript", "retry": status == "failed"}
    return {"source": "none", "label": "Transcript", "retry": False}


def as_text(lines: list[dict[str, Any]], *, you: str = "You", them: str = "Them") -> str:
    """Plain text, one line per caption: '[mm:ss] You: text'. Partials kept."""
    out = []
    for line in sorted(lines, key=lambda l: (float(l.get("start") or 0), l.get("track") != "mic")):
        who = you if line.get("track") == "mic" else (line.get("speaker") or them)
        t = int(float(line.get("start") or 0))
        out.append(f"[{t // 60:02d}:{t % 60:02d}] {who}: {line.get('text', '').strip()}")
    return "\n".join(out)
