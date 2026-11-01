"""Live Recording rows written by the Electron Recording session
(src/recording/session.js): pending row, status, continuation status and the
live feed. Capture itself is driven only from Electron."""
from __future__ import annotations
import datetime as dt
from pathlib import Path

from api.router import route
import db
from api.core import ARCHETYPES, safe_id
from api.views import PENDING_TITLES


@route("POST", '/api/recording/start')
def post_api_recording_start(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    started_at = str(body.get("started_at") or dt.datetime.now().astimezone().isoformat())
    archetype_id = body.get("archetype_id")
    archetype = None
    if archetype_id is not None:
        try:
            aid = int(archetype_id)
            archetype = ARCHETYPES.get(aid)
        except (ValueError, TypeError):
            pass
    meeting_tool = str(body.get("meeting_tool") or "").strip() or None
    continues_recording_id = str(body.get("continues_recording_id") or "").strip() or None
    db.create_pending_recording(recording_id, source_stem=recording_id, recorded_at=started_at, status="recording", archetype=archetype, meeting_tool=meeting_tool, continues_recording_id=continues_recording_id)
    return req.send_json({"ok": True, "id": recording_id}, 201)


@route("POST", '/api/recording/status')
def post_api_recording_status(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    status = str(body.get("status", ""))
    if status not in PENDING_TITLES:
        raise ValueError(f"Invalid status: {status}")
    db.set_pending_recording_status(recording_id, status)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/continuation-status')
def post_api_recording_continuation_status(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    status = body.get("status")
    if status is not None and status not in ("recording", "processing"):
        raise ValueError(f"Invalid continuation status: {status}")
    child_id = str(body.get("child_id") or "").strip() or None
    db.set_continuation_status(recording_id, status, child_id=child_id)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/live-entry')
def post_api_recording_live_entry(req, path: str, body: dict) -> None:
    # Called by the Electron main process right after a manual
    # "Snap Meeting Slide" screenshot is captured + OCR'd, so it
    # lands inline in the live chat-style feed at the moment it
    # was actually taken — not bolted on after the fact.
    rec_id = str(body.get("id", ""))
    if not db.get_recording(rec_id):
        raise FileNotFoundError(rec_id)
    db.add_live_transcript_entry(
        rec_id,
        entry_type=str(body.get("type", "screenshot")),
        speaker_id=body.get("speaker_id"),
        start_seconds=body.get("at_seconds"),
        end_seconds=body.get("at_seconds"),
        text=body.get("text"),
        # Bare filename only — resolved to a servable URL later
        # via live_transcript_payload(), against whichever of
        # inbox/ or the archived folder currently has it.
        image_path=Path(str(body.get("image_path", ""))).name or None,
    )
    return req.send_json({"ok": True})
