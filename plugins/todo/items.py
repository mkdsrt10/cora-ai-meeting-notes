"""The To-dos page's routes and the after_meeting Hook (see store.py)."""
from __future__ import annotations

from . import store


def after_meeting(recording_id: str) -> None:
    store.sync(recording_id)


def action_items() -> list[dict]:
    return store.listed()


def get_items(req, path: str, query: dict) -> None:
    req.send_json({"items": store.listed()})


def post_done(req, path: str, body: dict) -> None:
    """Body: {"id", "done"}; or, for older pages, {"recording_id", "index", "done"}
    where index is the item's listed index."""
    key = str(body.get("id") or "")
    if not key:
        recording_id = str(body.get("recording_id") or "")
        try:
            index = int(body.get("index"))
        except (TypeError, ValueError):
            raise ValueError("index must be an integer")
        key = store.find(recording_id, index) or ""
    if not key or not store.set_done(key, bool(body.get("done"))):
        raise FileNotFoundError(key or "to-do")
    req.send_json({"ok": True})
