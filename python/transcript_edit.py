"""Human edits to a finished transcript: who spoke each turn, and what was said.

Edits are applied to the stored diarization (DB + diarization.json) and the
rendered transcript_diarized.md, and every change is logged to the local AI
trace store (ai_trace.record_correction) as labelled training data. The
original AI value is kept on each segment (original_speaker_*,
original_text) so edits are auditable and reversible.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import ai_trace
import db

SELF_ID = "You"
ROLES = {"self", "participant"}


def render_transcript_md(overview: str, segments: list[dict[str, Any]], heading: str) -> str:
    """Same format the pipelines write (and the UI/MCP parse)."""
    lines = [heading, "", overview or "", ""]
    if not segments:
        lines.append("_No speech was detected in this recording._")
    for seg in segments:
        lines += [f"**{seg.get('start', '')}–{seg.get('end', '')} · {seg.get('speaker_name') or seg.get('speaker_id')}**",
                  "", seg.get("text", ""), ""]
    return "\n".join(lines)


def _assign_speaker(seg: dict[str, Any], name: str, role: str, self_name: str | None) -> tuple[str, str]:
    before = seg.get("speaker_name") or seg.get("speaker_id") or ""
    seg.setdefault("original_speaker_id", seg.get("speaker_id"))
    seg.setdefault("original_speaker_name", seg.get("speaker_name"))
    if role == "self":
        seg["speaker_id"] = SELF_ID
        seg["speaker_name"] = self_name or SELF_ID
    else:
        seg["speaker_id"] = name
        seg["speaker_name"] = name
    seg["speaker_role"] = role
    seg["speaker_source"] = "manual"
    return before, seg["speaker_name"]


def apply_edits(recording_id: str, folder: Path, edits: list[dict[str, Any]], self_name: str | None = None) -> dict[str, Any]:
    """Apply a batch of edits. Each edit is one of:

      {"index": 3, "speaker": "Priya", "role": "participant"}   # one turn
      {"index": 3, "text": "corrected words"}                    # one turn's text
      {"rename_from": "Participant", "speaker": "Priya", "role": "participant"}  # every turn with that label
    """
    diarization = db.get_recording_data(recording_id, "diarization") or {}
    segments: list[dict[str, Any]] = diarization.get("segments") or []
    if not segments:
        raise ValueError("This recording has no transcript to edit.")
    source_model = diarization.get("model")

    for edit in edits:
        role = edit.get("role", "participant")
        if "speaker" in edit and role not in ROLES:
            raise ValueError(f"role must be one of {sorted(ROLES)}")
        name = str(edit.get("speaker", "")).strip()[:120]
        if "speaker" in edit and role == "participant" and not name:
            raise ValueError("Speaker name cannot be empty.")

        if "rename_from" in edit:
            target = str(edit["rename_from"])
            for i, seg in enumerate(segments):
                if (seg.get("speaker_name") or seg.get("speaker_id")) == target or seg.get("speaker_id") == target:
                    before, after = _assign_speaker(seg, name, role, self_name)
                    ai_trace.record_correction(recording_id, i, "speaker", before, after, seg.get("start"),
                                               seg.get("end"), source_model)
            continue

        index = edit.get("index")
        if not isinstance(index, int) or not 0 <= index < len(segments):
            raise ValueError(f"Invalid segment index: {index!r}")
        seg = segments[index]
        if "speaker" in edit:
            before, after = _assign_speaker(seg, name, role, self_name)
            ai_trace.record_correction(recording_id, index, "speaker", before, after, seg.get("start"),
                                       seg.get("end"), source_model)
        if "text" in edit:
            text = str(edit["text"]).strip()
            if text != seg.get("text", ""):
                seg.setdefault("original_text", seg.get("text", ""))
                ai_trace.record_correction(recording_id, index, "text", seg.get("text", ""), text,
                                           seg.get("start"), seg.get("end"), source_model)
                seg["text"] = text
                seg["text_source"] = "manual"

    speakers: dict[str, dict[str, Any]] = {}
    for seg in segments:
        sid = seg.get("speaker_id") or ""
        speakers.setdefault(sid, {"speaker_id": sid, "name": seg.get("speaker_name") or sid,
                                  "description": "You" if sid == SELF_ID else "Participant"})
    diarization["speakers"] = list(speakers.values())
    diarization["segments"] = segments
    diarization["edited_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    db.update_recording_data(recording_id, "diarization", diarization)
    payload = json.dumps(diarization, indent=2, ensure_ascii=False) + "\n"
    for name in ("diarization.json", "gemini_diarization.json"):
        if (folder / name).exists() or name == "diarization.json":
            (folder / name).write_text(payload)
    heading = "# Meeting Transcript (edited)"
    (folder / "transcript_diarized.md").write_text(
        render_transcript_md(diarization.get("summary", ""), segments, heading), encoding="utf-8")
    return {"ok": True, "segments": len(segments), "speakers": [s["name"] for s in speakers.values()]}
