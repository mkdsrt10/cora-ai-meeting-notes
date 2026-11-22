"""Notion plugin routes (/api/plugins/notion/...) and the daily status pull.

GET  settings     {settings, starter_instructions, connected, tasks_cached, fetched_at}
POST settings     {database_link? or database_id?, mapping?, usage_instructions?} (a pasted link picks the database;
                  Cora never lists every database the integration can see)
GET  schema?db=   that database's properties (names, types, options)
POST refresh      refresh the Task cache now
"""
from __future__ import annotations

import re

import datetime as dt
from typing import Any

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
    body = dict(body)
    link = str(body.pop("database_link", "") or "").strip()
    if link:
        found = _listing(req, database_from_link, link)
        if found is None:
            return None
        body.update(database_id=found["id"], database_title=found["title"], mapping={})
    saved = tasks.save_settings(body)
    if saved.get("database_id") != before:
        tasks.refresh(force=True)
    return req.send_json({"ok": True, "settings": tasks.settings()})


_DB_ID = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}")


def database_from_link(conn, link: str) -> dict[str, str]:
    """A database picked by pasting its Notion link (or id), for workspaces where
    several shared databases have the same name. One read of that database."""
    ids = _DB_ID.findall(str(link or "").split("?", 1)[0])
    if not ids:
        raise ValueError("Paste the database's link from Notion (⋯ → Copy link)")
    db_id = ids[-1].replace("-", "")
    try:
        body = conn.request("GET", f"/databases/{db_id}")
    except connections.ConnectionFailed as exc:
        if exc.kind == "permanent":
            raise ValueError("Notion can't find that database with your token. Check the link, and that your Notion account can open it.") from None
        raise
    title = "".join(t.get("plain_text", "") for t in body.get("title") or []) or "Untitled"
    return {"id": body.get("id") or db_id, "title": title}


def schema(conn, db_id: str) -> list[dict[str, Any]]:
    """One database's properties: names, types, options (a listing call)."""
    if not db_id or not all(c.isalnum() or c == "-" for c in db_id):
        raise ValueError("db is required")
    body = conn.request("GET", f"/databases/{db_id}")
    props = []
    for name, prop in (body.get("properties") or {}).items():
        kind = prop.get("type")
        options = [o.get("name") for o in ((prop.get(kind) or {}).get("options") or [])] if kind in ("status", "select") else []
        props.append({"name": name, "type": kind, "options": options})
    return props


def _listing(req, fn, *args) -> Any:
    """A listing call (no meeting content); errors become a status the page can show."""
    try:
        return fn(connections.get("notion"), *args)
    except connections.NotConnected:
        req.send_json({"error": "not_connected"}, 409)
    except connections.BlockedByPolicy:
        req.send_json({"error": "blocked_policy"}, 403)
    except connections.ConnectionFailed as exc:
        req.send_json({"error": f"notion_{exc.kind}"}, 502)
    return None


def get_schema(req, path: str, query: dict) -> None:
    db_id = (query.get("db") or [""])[0]
    if not db_id or not all(c.isalnum() or c == "-" for c in db_id):
        raise ValueError("db is required")
    props = _listing(req, schema, db_id)
    if props is None:
        return None
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
