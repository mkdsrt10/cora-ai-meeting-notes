"""Core Action items (ADR 0004): records, not text parsed out of the Notes.

Each record is {id, recording_id, text, owner, due, done, provenance} with
provenance "ai" (written by notes generation) or "user" (added or edited by
the user). Identity:

- an AI item's id is a hash of its Recording id and its normalized text, so
  the same Action item keeps its id (and done mark) across reprocessing;
- an AI item that comes back reworded but close enough (token overlap >= 0.8)
  keeps the id of the one it replaces;
- records the user added or edited are never superseded or rewritten by
  reprocessing; AI records the user deleted stay deleted (kept as tombstones);
- AI items that no longer appear are superseded (hidden, done mark kept,
  revived if they return).

Ids are the same as the To-dos plugin's older store (plugins/todo/store.py
before core records), whose rows migrate here once. Fully local: reads the
notes already saved for a Recording and calls no model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

import db

REWORD_OVERLAP = 0.8

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS action_items (
        id TEXT PRIMARY KEY,
        recording_id TEXT NOT NULL,
        text TEXT NOT NULL,
        owner TEXT,
        due TEXT,
        position INTEGER NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        provenance TEXT NOT NULL DEFAULT 'ai' CHECK (provenance IN ('ai', 'user')),
        superseded_at TEXT,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS action_items_recording ON action_items (recording_id)",
    # Recordings whose Action items have been stored at least once (so an
    # empty list is not mistaken for "never synced").
    "CREATE TABLE IF NOT EXISTS action_items_synced (recording_id TEXT PRIMARY KEY, synced_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS core_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)",
)

_META = re.compile(r"\s*\(((?:owner|due)\s*:[^)]*)\)\s*$", re.IGNORECASE)
_UNASSIGNED = {"", "unassigned", "none", "n/a", "unknown", "tbd", "-"}
_ensured = False


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _ensure(conn) -> None:
    global _ensured
    for statement in _SCHEMA:
        conn.execute(statement)
    if not _ensured:
        _ensured = True
        _migrate(conn)


# ---- text ------------------------------------------------------------------

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".!;,").strip().lower()


def item_id(recording_id: str, text: str) -> str:
    return hashlib.sha256(f"{recording_id}\0{normalize(text)}".encode()).hexdigest()[:16]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap(a: str, b: str) -> float:
    """Shared tokens over the larger token set: 1.0 same words, 0 none."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def parse_item(item: Any) -> dict[str, Any]:
    """{text, owner, due} from one saved Action item: a bullet string, with an
    optional "(Owner: X, Due: Y)" suffix (local notes), or a
    {action, owner_speaker_id|owner, due_date} dict (Gemini)."""
    if isinstance(item, dict):
        text = str(item.get("action") or item.get("text") or "").strip()
        owner = str(item.get("owner") or item.get("owner_speaker_id") or "").strip()
        due = str(item.get("due_date") or item.get("due") or "").strip()
    else:
        text = str(item or "").strip().lstrip("-*• ").strip()
        owner = due = ""
        match = _META.search(text)
        if match:
            text = text[: match.start()].strip()
            for part in match.group(1).split(","):
                key, _, value = part.partition(":")
                key, value = key.strip().lower(), value.strip()
                if key == "owner":
                    owner = value
                elif key == "due":
                    due = value
    return {"text": text, "owner": None if owner.lower() in _UNASSIGNED else owner,
            "due": None if due.lower() in _UNASSIGNED else due}


def text_of(item: Any) -> str:
    return parse_item(item)["text"]


def raw_action_items(recording: dict[str, Any]) -> list[Any]:
    summary = recording.get("call_summary") or (recording.get("diarization") or {}).get("call_summary") or {}
    return list(summary.get("action_items") or [])


def eligible(recording: dict[str, Any] | None) -> bool:
    """Processed and not about to merge into its parent Recording."""
    return bool(recording) and not recording.get("status") and \
        not (recording.get("metadata") or {}).get("continues_recording_id")


# ---- reprocessing ----------------------------------------------------------

def sync(recording_id: str) -> None:
    """Store the Recording's current AI Action items (see module docstring)."""
    recording = db.get_recording(recording_id)
    if not eligible(recording):
        return
    raw = raw_action_items(recording)
    current: dict[str, dict[str, Any]] = {}
    for item in raw:
        parsed = parse_item(item)
        if parsed["text"] and normalize(parsed["text"]):
            current.setdefault(item_id(recording_id, parsed["text"]), parsed)
    now = _now()
    with db.get_db() as conn:
        _ensure(conn)
        first_sync = conn.execute("SELECT 1 FROM action_items_synced WHERE recording_id = ?",
                                  (recording_id,)).fetchone() is None
        rows = {row["id"]: dict(row) for row in conn.execute(
            "SELECT * FROM action_items WHERE recording_id = ?", (recording_id,))}
        claimed: set[str] = set()
        for position, (key, parsed) in enumerate(current.items()):
            target = key if key in rows else _reworded(rows, parsed["text"], set(current) | claimed)
            if target is None:
                conn.execute("INSERT INTO action_items (id, recording_id, text, owner, due, position, provenance, "
                             "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'ai', ?, ?)",
                             (key, recording_id, parsed["text"], parsed["owner"], parsed["due"], position, now, now))
                claimed.add(key)
                continue
            claimed.add(target)
            row = rows[target]
            if row["provenance"] == "user" or row["deleted_at"]:
                continue  # the user's record wins; a deletion sticks
            conn.execute("UPDATE action_items SET text = ?, owner = ?, due = ?, position = ?, superseded_at = NULL, "
                         "updated_at = ? WHERE id = ?",
                         (parsed["text"], parsed["owner"], parsed["due"], position, now, target))
        gone = [key for key, row in rows.items() if key not in claimed and row["provenance"] == "ai"
                and not row["superseded_at"]]
        if gone:
            conn.executemany("UPDATE action_items SET superseded_at = ? WHERE id = ?", [(now, key) for key in gone])
        if first_sync:
            _migrate_index_marks(conn, recording_id, raw)
        conn.execute("INSERT INTO action_items_synced (recording_id, synced_at) VALUES (?, ?) "
                     "ON CONFLICT(recording_id) DO UPDATE SET synced_at = excluded.synced_at", (recording_id, now))
        conn.commit()


def _reworded(rows: dict[str, dict[str, Any]], text: str, taken: set[str]) -> str | None:
    """The existing AI record this text rewords, if one is close enough and
    not already claimed by another current item."""
    best, best_score = None, REWORD_OVERLAP
    for key, row in rows.items():
        if key in taken or row["provenance"] != "ai":
            continue
        score = overlap(row["text"], text)
        if score >= best_score:
            best, best_score = key, score
    return best


def _migrate_index_marks(conn, recording_id: str, raw: list[Any]) -> None:
    """Done marks from the oldest todo_state table, keyed by position in the
    Recording's action_items list, carried over on the first sync only."""
    try:
        rows = conn.execute("SELECT item_index, done, done_at FROM todo_state WHERE recording_id = ? AND done",
                            (recording_id,)).fetchall()
    except Exception:  # no legacy table
        return
    for row in rows:
        index = row["item_index"]
        if isinstance(index, int) and 0 <= index < len(raw) and text_of(raw[index]):
            conn.execute("UPDATE action_items SET done = 1, done_at = ? WHERE id = ?",
                         (row["done_at"], item_id(recording_id, text_of(raw[index]))))


def _migrate(conn, force: bool = False) -> None:
    """Once per database: copy the To-dos plugin's own store (todo_items,
    todo_synced) into core records, keeping ids and done marks."""
    if not force and conn.execute("SELECT 1 FROM core_migrations WHERE name = 'todo_items'").fetchone():
        return
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "todo_items" in tables:
        conn.execute("""INSERT OR IGNORE INTO action_items (id, recording_id, text, position, done, done_at,
                        provenance, superseded_at, created_at, updated_at)
                        SELECT id, recording_id, text, position, done, done_at, 'ai', superseded_at, created_at, created_at
                        FROM todo_items""")
    if "todo_synced" in tables:
        conn.execute("INSERT OR IGNORE INTO action_items_synced SELECT recording_id, synced_at FROM todo_synced")
    conn.execute("INSERT OR REPLACE INTO core_migrations (name, applied_at) VALUES ('todo_items', ?)", (_now(),))
    conn.commit()


def migrate_from_todo_store(force: bool = False) -> None:
    with db.get_db() as conn:
        for statement in _SCHEMA:
            conn.execute(statement)
        _migrate(conn, force=force)


def backfill() -> None:
    """Store Action items for processed Recordings never synced."""
    with db.get_db() as conn:
        _ensure(conn)
        conn.commit()
        synced = {row["recording_id"] for row in conn.execute("SELECT recording_id FROM action_items_synced")}
    for recording in db.get_all_recordings():
        if recording["id"] not in synced and eligible(recording):
            sync(recording["id"])


# ---- reading ---------------------------------------------------------------

def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "recording_id": row["recording_id"], "text": row["text"], "owner": row["owner"],
            "due": row["due"], "done": bool(row["done"]), "done_at": row["done_at"], "provenance": row["provenance"],
            "position": row["position"]}


def for_recording(recording_id: str) -> list[dict[str, Any]]:
    """Current Action items of one Recording, in order (AI items by their
    place in the notes, user-added ones after)."""
    with db.get_db() as conn:
        _ensure(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM action_items WHERE recording_id = ? AND superseded_at IS NULL AND deleted_at IS NULL "
            "ORDER BY position, created_at", (recording_id,))]
    return [_public(r) for r in rows]


def current() -> list[dict[str, Any]]:
    """Every current Action item across Recordings (backfilling first)."""
    backfill()
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM action_items WHERE superseded_at IS NULL AND deleted_at IS NULL "
            "ORDER BY recording_id, position, created_at")]
    return [_public(r) for r in rows]


def get(key: str) -> dict[str, Any] | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT * FROM action_items WHERE id = ?", (key,)).fetchone()
    return _public(dict(row)) if row else None


def find(recording_id: str, position: int) -> str | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT id FROM action_items WHERE recording_id = ? AND position = ? "
                           "AND superseded_at IS NULL AND deleted_at IS NULL", (recording_id, position)).fetchone()
    return row["id"] if row else None


# ---- user changes ----------------------------------------------------------

def set_done(key: str, done: bool) -> bool:
    """Mark one Action item done or not; False when no such item. A done mark
    does not change provenance (reprocessing may still refresh the text)."""
    with db.get_db() as conn:
        _ensure(conn)
        cur = conn.execute("UPDATE action_items SET done = ?, done_at = ?, updated_at = ? WHERE id = ?",
                           (int(done), _now() if done else None, _now(), key))
        conn.commit()
    if cur.rowcount > 0:
        _notify("done", key)
    return cur.rowcount > 0


def edit(key: str, *, text: str | None = None, owner: str | None = None, due: str | None = None,
         clear: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """The user's edit: the record becomes theirs (provenance "user")."""
    item = get(key)
    if item is None:
        return None
    values = {"text": item["text"], "owner": item["owner"], "due": item["due"]}
    for name, value in (("text", text), ("owner", owner), ("due", due)):
        if value is not None:
            values[name] = value.strip() or None
    for name in clear:
        if name in ("owner", "due"):
            values[name] = None
    if not values["text"]:
        raise ValueError("text must not be empty")
    with db.get_db() as conn:
        conn.execute("UPDATE action_items SET text = ?, owner = ?, due = ?, provenance = 'user', updated_at = ? "
                     "WHERE id = ?", (values["text"], values["owner"], values["due"], _now(), key))
        conn.commit()
    return get(key)


def add(recording_id: str, text: str, owner: str | None = None, due: str | None = None) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("text must not be empty")
    if db.get_recording(recording_id) is None:
        raise FileNotFoundError(recording_id)
    now = _now()
    key = hashlib.sha256(f"user\0{recording_id}\0{now}\0{text}".encode()).hexdigest()[:16]
    with db.get_db() as conn:
        _ensure(conn)
        position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM action_items WHERE recording_id = ?",
                                (recording_id,)).fetchone()[0]
        conn.execute("INSERT INTO action_items (id, recording_id, text, owner, due, position, provenance, created_at, "
                     "updated_at) VALUES (?, ?, ?, ?, ?, ?, 'user', ?, ?)",
                     (key, recording_id, text, (owner or "").strip() or None, (due or "").strip() or None,
                      position, now, now))
        conn.commit()
    return get(key)  # type: ignore[return-value]


def delete(key: str) -> bool:
    """The user deletes an Action item. Kept as a tombstone so the same AI
    item does not return on reprocessing."""
    with db.get_db() as conn:
        _ensure(conn)
        cur = conn.execute("UPDATE action_items SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                           (_now(), _now(), key))
        conn.commit()
    return cur.rowcount > 0


# ---- listeners -------------------------------------------------------------

_listeners: list[Any] = []


def on_change(fn) -> None:
    """Call fn(event, item_id) after a user change ("done"). Used by core
    modules that react to To-dos (e.g. the Outbox); a listener failing never
    fails the change."""
    if fn not in _listeners:
        _listeners.append(fn)


def _notify(event: str, key: str) -> None:
    for fn in list(_listeners):
        try:
            fn(event, key)
        except Exception as exc:
            print(f"[action_items] listener failed ({type(exc).__name__})", flush=True)
