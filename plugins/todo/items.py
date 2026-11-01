"""Action items across Recordings, with done state (todo_state table)."""
from __future__ import annotations

import datetime as dt
from typing import Any

import db


def _text(item: Any) -> str:
    """call_summary.action_items holds plain strings (local notes) or
    {action, owner_speaker_id, due_date} dicts (Gemini diarization)."""
    if isinstance(item, dict):
        return str(item.get("action") or "").strip()
    return str(item or "").strip()


def action_items() -> list[dict[str, Any]]:
    done = {(row["recording_id"], row["item_index"]): row for row in db.get_todo_states()}
    result = []
    for rec in db.get_all_recordings():
        if rec.get("status") or (rec.get("metadata") or {}).get("continues_recording_id"):
            continue  # still recording/processing, or about to merge into its parent
        summary = rec.get("call_summary") or (rec.get("diarization") or {}).get("call_summary") or {}
        for index, item in enumerate(summary.get("action_items") or []):
            text = _text(item)
            if not text:
                continue
            state = done.get((rec["id"], index)) or {}
            result.append({
                "recording_id": rec["id"],
                "recording_title": rec.get("title") or rec["id"],
                "recorded_at": rec.get("recorded_at"),
                "index": index,
                "text": text,
                "done": bool(state.get("done")),
                "done_at": state.get("done_at"),
            })
    return result


def get_items(req, path: str, query: dict) -> None:
    req.send_json({"items": action_items()})


def post_done(req, path: str, body: dict) -> None:
    recording_id = str(body.get("recording_id") or "")
    if not db.get_recording(recording_id):
        raise FileNotFoundError(recording_id)
    try:
        index = int(body.get("index"))
    except (TypeError, ValueError):
        raise ValueError("index must be an integer")
    done = bool(body.get("done"))
    db.set_todo_state(recording_id, index, done, dt.datetime.now().astimezone().isoformat() if done else None)
    req.send_json({"ok": True})
