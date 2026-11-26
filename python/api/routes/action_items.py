"""Core Action items over HTTP (ADR 0004; see action_items.py).

GET  /api/action-items?recording=<id>    current records of one Recording
POST /api/action-items                   {recording_id, text, owner?, due?}: the user adds one
POST /api/action-items/<id>              {text?, owner?, due?, done?}: edit (makes it the user's) or tick
POST /api/action-items/<id>/delete       the user deletes one (stays deleted)
"""
from __future__ import annotations

import action_items
from api.router import route


def _opt(body: dict, name: str) -> str | None:
    value = body.get(name)
    return None if value is None else str(value)


@route("GET", "/api/action-items")
def get_action_items(req, path: str, query: dict) -> None:
    recording_id = (query.get("recording") or [""])[0]
    items = action_items.for_recording(recording_id) if recording_id else action_items.current()
    return req.send_json({"items": items})


@route("POST", "/api/action-items")
def post_action_item_add(req, path: str, body: dict) -> None:
    item = action_items.add(str(body.get("recording_id") or ""), str(body.get("text") or ""),
                            _opt(body, "owner"), _opt(body, "due"))
    return req.send_json({"ok": True, "item": item})


@route("POST", "/api/action-items/", prefix=True)
def post_action_item(req, path: str, body: dict) -> None:
    key, _, verb = path[len("/api/action-items/"):].partition("/")
    if verb == "delete":
        if not action_items.delete(key):
            return req.send_json({"error": "Unknown Action item"}, 404)
        return req.send_json({"ok": True})
    if verb or action_items.get(key) is None:
        return req.send_json({"error": "Unknown Action item"}, 404)
    if any(name in body for name in ("text", "owner", "due")):
        action_items.edit(key, text=_opt(body, "text"), owner=_opt(body, "owner"), due=_opt(body, "due"))
    if "done" in body:
        action_items.set_done(key, bool(body.get("done")))
    return req.send_json({"ok": True, "item": action_items.get(key)})
