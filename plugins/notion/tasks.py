"""Notion plugin settings and the local Task cache.

Settings (outbox.plugin_settings("notion")):
    database_id, database_title       the database the user pasted the link of
    data_source_id, data_sources      the data source holding the Tasks, and the
                                      database's sources [{id, name}] to pick from
    mapping: {title, status, done_value, assignee, due, area, meeting}
    usage_instructions: free text (starter template below)

The cache holds the Tasks database's pages (id, title, status, done,
assignee ids, area, url, created/edited times) on this Mac. It is refreshed
by the daily Hook, when the database is picked, and on demand (Refresh
Tasks), never during processing. Its requests list the database only: no
meeting content.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

import connections
import db
import outbox

PLUGIN_ID = "notion"
TTL = dt.timedelta(minutes=15)
MAX_PAGES = 10   # x100 Tasks

STARTER_INSTRUCTIONS = """\
How I use my Notion Tasks (edit to match how you work):
- Granularity: chunky Tasks. Fold sub-steps from the same meeting into one Task's checklist.
- Create a Task only for work someone committed to; skip FYIs and vague ideas.
- Link instead of create when an open Task already covers the item.
- Areas: pick the Area option that matches the meeting's topic; leave it empty when unsure.
- Owners: never assign generic speaker labels (You, Participant, Speaker 1) or meeting-app
  UI text (video settings, share with audio); leave those unassigned.
- Titles: start with a verb, under 80 characters, no meeting name.
"""

_SCHEMA = """CREATE TABLE IF NOT EXISTS notion_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    assignee_ids TEXT NOT NULL DEFAULT '[]',
    area TEXT,
    url TEXT,
    created_time TEXT,
    last_edited TEXT,
    fetched_at TEXT NOT NULL
)"""


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _ensure(conn) -> None:
    conn.execute(_SCHEMA)


def settings() -> dict[str, Any]:
    value = outbox.plugin_settings(PLUGIN_ID)
    value.setdefault("mapping", {})
    value.setdefault("usage_instructions", "")
    return value


def configured() -> bool:
    s = settings()
    return bool(s.get("database_id") and s["mapping"].get("title"))


def source_id(conn) -> str:
    """The data source the Tasks live in. Settings saved before data sources
    (only a database_id) resolve to the database's first source, once."""
    s = settings()
    if s.get("data_source_id"):
        return s["data_source_id"]
    body = conn.request("GET", f"/databases/{s['database_id']}")
    sources = [{"id": d.get("id"), "name": str(d.get("name") or "")[:200]} for d in body.get("data_sources") or [] if d.get("id")]
    if not sources:
        raise connections.ConnectionFailed("permanent", None, "no_data_source")
    outbox.save_plugin_settings(PLUGIN_ID, {"data_source_id": sources[0]["id"], "data_sources": sources})
    return sources[0]["id"]


def save_settings(body: dict[str, Any]) -> dict[str, Any]:
    allowed = {"title", "status", "done_value", "assignee", "due", "area", "meeting"}
    values: dict[str, Any] = {}
    if "database_id" in body:
        values["database_id"] = str(body.get("database_id") or "").strip()
        values["database_title"] = str(body.get("database_title") or "")[:200]
        sources = [{"id": str(d.get("id")), "name": str(d.get("name") or "")[:200]}
                   for d in body.get("data_sources") or [] if isinstance(d, dict) and d.get("id")]
        values["data_sources"] = sources
        values["data_source_id"] = sources[0]["id"] if sources else ""
    if body.get("data_source_id"):
        chosen = str(body["data_source_id"]).strip()
        known = values.get("data_sources", settings().get("data_sources") or [])
        if known and chosen not in {d["id"] for d in known}:
            raise ValueError("Pick one of this database's data sources")
        values["data_source_id"] = chosen
    if "mapping" in body:
        mapping = body.get("mapping") or {}
        if not isinstance(mapping, dict):
            raise ValueError("mapping must be an object")
        values["mapping"] = {k: str(v)[:200] for k, v in mapping.items() if k in allowed and v}
    if "usage_instructions" in body:
        text = str(body.get("usage_instructions") or "")
        if len(text) > 4000:
            raise ValueError("Usage instructions must be at most 4000 characters")
        values["usage_instructions"] = text.strip()
    return outbox.save_plugin_settings(PLUGIN_ID, values)


# ---- reading Notion page properties -----------------------------------------

def _plain(rich: list | None) -> str:
    return "".join(str(part.get("plain_text") or (part.get("text") or {}).get("content") or "") for part in rich or [])


def _prop(page: dict, name: str | None) -> dict:
    return (page.get("properties") or {}).get(name or "", {}) if name else {}


def _value(prop: dict) -> Any:
    kind = prop.get("type")
    if kind in ("title", "rich_text"):
        return _plain(prop.get(kind))
    if kind in ("status", "select"):
        return (prop.get(kind) or {}).get("name")
    if kind == "checkbox":
        return bool(prop.get("checkbox"))
    if kind == "people":
        return [p.get("id") for p in prop.get("people") or [] if p.get("id")]
    if kind == "date":
        return (prop.get("date") or {}).get("start")
    if kind == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select") or [])
    return None


def is_done(status: Any, done_value: str | None) -> bool:
    if isinstance(status, bool):
        return status
    return bool(status) and bool(done_value) and str(status).strip().lower() == str(done_value).strip().lower()


def parse_page(page: dict, mapping: dict[str, str]) -> dict[str, Any]:
    status = _value(_prop(page, mapping.get("status")))
    assignees = _value(_prop(page, mapping.get("assignee")))
    return {
        "id": page.get("id"), "title": _value(_prop(page, mapping.get("title"))) or "",
        "status": status if not isinstance(status, bool) else ("done" if status else "open"),
        "done": is_done(status, mapping.get("done_value")),
        "assignee_ids": assignees if isinstance(assignees, list) else [],
        "area": _value(_prop(page, mapping.get("area"))), "url": page.get("url"),
        "created_time": page.get("created_time"), "last_edited": page.get("last_edited_time"),
    }


# ---- the cache -----------------------------------------------------------------

def fetched_at() -> dt.datetime | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT MAX(fetched_at) AS at FROM notion_tasks").fetchone()
    return dt.datetime.fromisoformat(row["at"]) if row and row["at"] else None


def refresh(*, force: bool = False) -> bool:
    """Fetch the Tasks database into the cache. Returns True when it fetched.
    A network failure keeps the old cache (and is not raised)."""
    s = settings()
    if not configured() or not connections.connected("notion"):
        return False
    last = fetched_at()
    if not force and last and _now() - last < TTL:
        return False
    try:
        conn = connections.get("notion")
        pages: list[dict] = []
        cursor = None
        for _ in range(MAX_PAGES):
            body = conn.request("POST", f"/data_sources/{source_id(conn)}/query",
                                json={"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            pages.extend(body.get("results") or [])
            cursor = body.get("next_cursor")
            if not body.get("has_more") or not cursor:
                break
    except (connections.ConnectionFailed, connections.NotConnected, connections.BlockedByPolicy):
        return False
    now = _now().isoformat()
    rows = [parse_page(p, s["mapping"]) for p in pages if p.get("id") and not p.get("archived")]
    with db.get_db() as c:
        _ensure(c)
        c.execute("DELETE FROM notion_tasks")
        c.executemany("INSERT OR REPLACE INTO notion_tasks (id, title, status, done, assignee_ids, area, url, "
                      "created_time, last_edited, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      [(r["id"], r["title"], r["status"], int(r["done"]), json.dumps(r["assignee_ids"]), r["area"],
                        r["url"], r["created_time"], r["last_edited"], now) for r in rows if r["title"]])
        c.commit()
    return True


def _public(row) -> dict[str, Any]:
    r = dict(row)
    r["done"] = bool(r["done"])
    r["assignee_ids"] = json.loads(r["assignee_ids"])
    return r


def all_tasks() -> list[dict[str, Any]]:
    with db.get_db() as conn:
        _ensure(conn)
        return [_public(r) for r in conn.execute("SELECT * FROM notion_tasks ORDER BY last_edited DESC")]


def open_tasks() -> list[dict[str, Any]]:
    return [t for t in all_tasks() if not t["done"]]


def task(task_id: str) -> dict[str, Any] | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT * FROM notion_tasks WHERE id = ?", (task_id,)).fetchone()
    return _public(row) if row else None


def upsert(task_row: dict[str, Any]) -> None:
    """Add a Task Cora just created, so the next propose sees it."""
    with db.get_db() as c:
        _ensure(c)
        c.execute("INSERT OR REPLACE INTO notion_tasks (id, title, status, done, assignee_ids, area, url, created_time, "
                  "last_edited, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (task_row["id"], task_row["title"], task_row.get("status"), int(bool(task_row.get("done"))),
                   json.dumps(task_row.get("assignee_ids") or []), task_row.get("area"), task_row.get("url"),
                   task_row.get("created_time") or _now().isoformat(), _now().isoformat(), _now().isoformat()))
        c.commit()


def set_done(task_id: str, done: bool) -> None:
    with db.get_db() as c:
        _ensure(c)
        c.execute("UPDATE notion_tasks SET done = ? WHERE id = ?", (int(done), task_id))
        c.commit()
