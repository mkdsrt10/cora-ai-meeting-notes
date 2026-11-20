"""Notion plugin routes (/api/plugins/notion/...) and the daily status pull.

GET  settings     {settings, starter_instructions, connected, tasks_cached, fetched_at}
POST settings     {database_id?, database_title?, mapping?, usage_instructions?}
GET  databases    databases shared with the integration (ids and titles; a listing call)
GET  schema?db=   that database's properties (names, types, options)
POST refresh      refresh the Task cache now
"""
from __future__ import annotations

import datetime as dt

import connections
import db

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
    """Done both ways, Notion -> Cora (T8): a Linked To-do whose Task is done in
    Notion (per the cache the daily Hook just refreshed) is marked done, once.
    If the user unticks it afterwards, the pull does not tick it again.
    Returns the number of To-dos marked done."""
    import action_items
    import outbox
    marked = 0
    with db.get_db() as conn:
        conn.execute(PULLED)
        pulled = {(r["action_item_id"], r["task_id"]) for r in conn.execute("SELECT * FROM notion_done_pulled")}
    for link in outbox.links(service="notion"):
        item_id, task_id = link["action_item_id"], link["external_id"]
        if not item_id or link["kind"] != "task" or (item_id, task_id) in pulled:
            continue
        task = tasks.task(task_id)
        if not task or not task["done"]:
            continue
        item = action_items.get(item_id)
        with db.get_db() as conn:
            conn.execute(PULLED)
            conn.execute("INSERT OR IGNORE INTO notion_done_pulled (action_item_id, task_id, at) VALUES (?, ?, ?)",
                         (item_id, task_id, dt.datetime.now().astimezone().isoformat()))
            conn.commit()
        if item and not item["done"]:
            action_items.set_done(item_id, True)
            marked += 1
    return marked


PULLED = ("CREATE TABLE IF NOT EXISTS notion_done_pulled (action_item_id TEXT NOT NULL, task_id TEXT NOT NULL, "
          "at TEXT NOT NULL, PRIMARY KEY (action_item_id, task_id))")
