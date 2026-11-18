"""Export: one Recording saved by its owner as a Markdown file.

The file is the Recording's Notes as generated (enhanced_notes.md), under a
short header, followed by the Notepad when it has text and, only when asked,
the transcript. Building it never leaves the Mac; the Electron main process
shows the save dialog and writes the file. Dependency-light: the API server
and the MCP server both import it.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

import db
from paths import RECORDINGS_DIR

# Lines the notes pipeline writes for itself, not for readers.
_INTERNAL_LINE = re.compile(r"^#+\s*Template:.*$", re.IGNORECASE)
_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f/\\:*?"<>|]+')


def speaker_name(speaker_id: str, speaker_labels: dict[str, Any], identity: dict[str, Any]) -> str:
    """A raw speaker id (speaker_1, You) as a human-friendly name."""
    self_id = identity.get("speaker_id")
    if self_id and speaker_id == self_id:
        self_name = identity.get("identity") or db.get_setting("pending_self_name") or "You"
        return f"{self_name} (Self)"
    entry = (speaker_labels.get("speakers") or {}).get(speaker_id, {})
    if entry.get("name"):
        parts = [entry["name"]]
        if entry.get("role"):
            parts.append(entry["role"])
        if entry.get("organization"):
            parts.append(f"({entry['organization']})")
        return " — ".join(parts)
    return speaker_id


def _recorded(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when.astimezone() if when.tzinfo else when


def _duration(seconds: Any) -> Optional[str]:
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    minutes = max(1, round(total / 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"


def filename(title: str, recorded: Optional[dt.datetime]) -> str:
    """`2026-11-12 Weekly sync.md`: safe on macOS, at most ~100 characters."""
    name = _UNSAFE_FILENAME.sub(" ", title or "").strip(" .") or "Meeting"
    name = re.sub(r"\s+", " ", name)[:90].rstrip(" .")
    return f"{recorded:%Y-%m-%d} {name}.md" if recorded else f"{name}.md"


def _notes(recording_id: str) -> str:
    candidate = (RECORDINGS_DIR / recording_id).resolve()
    if not candidate.is_relative_to(RECORDINGS_DIR.resolve()):
        return ""
    path = candidate / "enhanced_notes.md"
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if not _INTERNAL_LINE.match(line.strip())]
    return "\n".join(lines).strip()


def build(recording_id: str, *, include_transcript: bool) -> dict[str, Any]:
    """{filename, markdown, notepad} for one Recording, or ValueError when
    it is unknown or has nothing to export yet."""
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")
    notes = _notes(recording_id)
    notepad = (db.get_notes(recording_id) or "").strip()
    diarization = rec.get("diarization") or {}
    segments = diarization.get("segments") or []
    if not notes and not notepad and not (include_transcript and segments):
        raise ValueError("This Recording has no notes to export yet.")

    labels = rec.get("speaker_labels") or {}
    identity = rec.get("identity") or {}
    title = (rec.get("title") or "").strip() or "Meeting"
    recorded = _recorded(rec.get("recorded_at"))

    header = []
    if recorded:
        header.append(f"**Date:** {recorded:%Y-%m-%d %H:%M}")
    duration = _duration(rec.get("duration_seconds"))
    if duration:
        header.append(f"**Duration:** {duration}")
    people = [speaker_name(s.get("speaker_id"), labels, identity) for s in diarization.get("speakers") or []]
    people = [p for p in dict.fromkeys(people) if p]
    if people:
        header.append(f"**Participants:** {', '.join(people)}")

    parts = [f"# {title}"]
    if header:
        parts.append("  \n".join(header))
    if notes:
        parts.append(notes)
    if notepad:
        parts.append(f"## My notes\n\n{notepad}")
    if include_transcript and segments:
        turns = []
        for s in segments:
            who = speaker_name(s.get("speaker_id"), labels, identity)
            turns.append(f"**[{s.get('start', '00:00')}] {who}:** {(s.get('text') or '').strip()}")
        parts.append("## Transcript\n\n" + "\n\n".join(turns))

    return {
        "filename": filename(title, recorded),
        "markdown": "\n\n".join(parts).rstrip() + "\n",
        "notepad": bool(notepad),
    }
