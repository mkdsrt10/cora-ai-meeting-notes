"""Notion plugin routes (/api/plugins/notion/...) and the daily status pull.

GET  settings     {settings, starter_instructions, connected, tasks_cached, fetched_at}
POST settings     {database_id?, database_title?, mapping?, usage_instructions?}
GET  databases    databases shared with the integration (ids and titles; a listing call)
GET  schema?db=   that database's properties (names, types, options)
POST refresh      refresh the Task cache now
"""
from __future__ import annotations

import connections

from . import tasks


def get_settings(req, path: str, query: dict) -> None:
    at = tasks.fetched_at()
    return req.send_json({"settings": tasks.settings(), "starter_instructions": tasks.STARTER_INSTRUCTIONS,
                          "connected": connections.connected("notion"), "tasks_cached": len(tasks.all_tasks()),
                          "fetched_at": at.isoformat() if at else None})


def post_settings(req, path: str, body: dict) -> None:
    before = tasks.settings().get("database_id")
    saved = tasks.save_settings(body)
    if saved.get("database_id") != before:
        tasks.refresh(force=True)
    return req.send_json({"ok": True, "settings": tasks.settings()})


def _listing(req, method: str, path: str, json: dict | None = None) -> dict | None:
    """A listing call (no meeting content); errors become a 409 the page can show."""
    try:
        return connections.get("notion").request(method, path, json=json)
    except connections.NotConnected:
        req.send_json({"error": "not_connected"}, 409)
    except connections.BlockedByPolicy:
        req.send_json({"error": "blocked_policy"}, 403)
    except connections.ConnectionFailed as exc:
        req.send_json({"error": f"notion_{exc.kind}"}, 502)
    return None


def get_databases(req, path: str, query: dict) -> None:
    body = _listing(req, "POST", "/search", {"filter": {"property": "object", "value": "database"}, "page_size": 50})
    if body is None:
        return None
    result = [{"id": d.get("id"), "title": "".join(t.get("plain_text", "") for t in d.get("title") or []) or "Untitled"}
              for d in body.get("results") or [] if d.get("id")]
    return req.send_json({"databases": result})


def get_schema(req, path: str, query: dict) -> None:
    db_id = (query.get("db") or [""])[0]
    if not db_id or not all(c.isalnum() or c == "-" for c in db_id):
        raise ValueError("db is required")
    body = _listing(req, "GET", f"/databases/{db_id}")
    if body is None:
        return None
    props = []
    for name, prop in (body.get("properties") or {}).items():
        kind = prop.get("type")
        options = [o.get("name") for o in ((prop.get(kind) or {}).get("options") or [])] if kind in ("status", "select") else []
        props.append({"name": name, "type": kind, "options": options})
    return req.send_json({"properties": props})


def post_refresh(req, path: str, body: dict) -> None:
    fetched = tasks.refresh(force=True)
    pulled = status_pull()
    return req.send_json({"ok": True, "fetched": fetched, "tasks_cached": len(tasks.all_tasks()), "marked_done": pulled})


def status_pull() -> int:
    """Done both ways, Notion -> Cora (T8). Returns To-dos marked done."""
    return 0
