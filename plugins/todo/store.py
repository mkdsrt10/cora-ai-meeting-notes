"""Stored To-dos: a Recording's Action items with stable ids and done marks.

An item's id is a hash of its Recording id and its normalized text, so the
same Action item keeps its id (and done mark) across reprocessing, whatever
its position. Items that disappear on reprocessing are marked superseded
(hidden, done mark kept, revived if they return). Fully local, no model call:
the Action items are read from the Recording's saved notes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

import db

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS todo_items (
        id TEXT PRIMARY KEY,
        recording_id TEXT NOT NULL,
        text TEXT NOT NULL,
        position INTEGER NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_at TEXT,
        superseded_at TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS todo_items_recording ON todo_items (recording_id)",
    # Recordings whose Action items have been stored at least once (so an
    # empty list is not mistaken for "never synced").
    "CREATE TABLE IF NOT EXISTS todo_synced (recording_id TEXT PRIMARY KEY, synced_at TEXT NOT NULL)",
)


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _ensure(conn) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def text_of(item: Any) -> str:
    """call_summary.action_items holds plain strings (local notes) or
    {action, owner_speaker_id, due_date} dicts (Gemini diarization)."""
    if isinstance(item, dict):
        return str(item.get("action") or "").strip()
    return str(item or "").strip()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".!;,").strip().lower()


def item_id(recording_id: str, text: str) -> str:
    return hashlib.sha256(f"{recording_id}\0{normalize(text)}".encode()).hexdigest()[:16]


def raw_action_items(recording: dict[str, Any]) -> list[Any]:
    summary = recording.get("call_summary") or (recording.get("diarization") or {}).get("call_summary") or {}
    return list(summary.get("action_items") or [])


def eligible(recording: dict[str, Any] | None) -> bool:
    """Processed and not about to merge into its parent Recording."""
    return bool(recording) and not recording.get("status") and \
        not (recording.get("metadata") or {}).get("continues_recording_id")


def sync(recording_id: str) -> None:
    """Store the Recording's current Action items. Same text keeps its id and
    done mark; items no longer present are superseded; duplicates collapse."""
    recording = db.get_recording(recording_id)
    if not eligible(recording):
        return
    raw = raw_action_items(recording)
    current: dict[str, tuple[str, int]] = {}
    for item in raw:
        text = text_of(item)
        if text and normalize(text):
            current.setdefault(item_id(recording_id, text), (text, len(current)))
    now = _now()
    with db.get_db() as conn:
        _ensure(conn)
        first_sync = conn.execute("SELECT 1 FROM todo_synced WHERE recording_id = ?", (recording_id,)).fetchone() is None
        existing = {row["id"] for row in conn.execute("SELECT id FROM todo_items WHERE recording_id = ?", (recording_id,))}
        for key, (text, position) in current.items():
            if key in existing:
                conn.execute("UPDATE todo_items SET text = ?, position = ?, superseded_at = NULL WHERE id = ?",
                             (text, position, key))
            else:
                conn.execute("INSERT INTO todo_items (id, recording_id, text, position, created_at) VALUES (?, ?, ?, ?, ?)",
                             (key, recording_id, text, position, now))
        gone = existing - set(current)
        if gone:
            conn.executemany("UPDATE todo_items SET superseded_at = COALESCE(superseded_at, ?) WHERE id = ?",
                             [(now, key) for key in gone])
        if first_sync:
            _migrate_index_marks(conn, recording_id, raw)
        conn.execute("INSERT INTO todo_synced (recording_id, synced_at) VALUES (?, ?) "
                     "ON CONFLICT(recording_id) DO UPDATE SET synced_at = excluded.synced_at", (recording_id, now))
        conn.commit()


def _migrate_index_marks(conn, recording_id: str, raw: list[Any]) -> None:
    """Done marks from the old todo_state table, keyed by position in the
    Recording's action_items list, carried over on the first sync only."""
    try:
        rows = conn.execute("SELECT item_index, done, done_at FROM todo_state WHERE recording_id = ? AND done",
                            (recording_id,)).fetchall()
    except Exception:  # no legacy table
        return
    for row in rows:
        index = row["item_index"]
        if isinstance(index, int) and 0 <= index < len(raw) and text_of(raw[index]):
            conn.execute("UPDATE todo_items SET done = 1, done_at = ? WHERE id = ?",
                         (row["done_at"], item_id(recording_id, text_of(raw[index]))))


def backfill() -> None:
    """Store Action items for processed Recordings never synced (processed
    before this plugin stored To-dos, or while it was disabled)."""
    with db.get_db() as conn:
        _ensure(conn)
        conn.commit()
        synced = {row["recording_id"] for row in conn.execute("SELECT recording_id FROM todo_synced")}
    for recording in db.get_all_recordings():
        if recording["id"] not in synced and eligible(recording):
            sync(recording["id"])


def listed() -> list[dict[str, Any]]:
    """Current (not superseded) To-dos of processed Recordings, in Recording
    order then each Recording's Action item order."""
    backfill()
    recordings = {r["id"]: r for r in db.get_all_recordings() if eligible(r)}
    with db.get_db() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM todo_items WHERE superseded_at IS NULL ORDER BY recording_id, position")]
    result = []
    for row in rows:
        rec = recordings.get(row["recording_id"])
        if rec is None:
            continue
        result.append({
            "id": row["id"],
            "recording_id": row["recording_id"],
            "recording_title": rec.get("title") or rec["id"],
            "recorded_at": rec.get("recorded_at"),
            "index": row["position"],
            "text": row["text"],
            "done": bool(row["done"]),
            "done_at": row["done_at"],
        })
    order = {rid: i for i, rid in enumerate(recordings)}
    result.sort(key=lambda item: (order[item["recording_id"]], item["index"]))
    return result


def find(recording_id: str, position: int) -> str | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT id FROM todo_items WHERE recording_id = ? AND position = ? AND superseded_at IS NULL",
                           (recording_id, position)).fetchone()
    return row["id"] if row else None


def set_done(key: str, done: bool) -> bool:
    """Mark one To-do done or not; False when no such item."""
    with db.get_db() as conn:
        _ensure(conn)
        cur = conn.execute("UPDATE todo_items SET done = ?, done_at = ? WHERE id = ?",
                           (int(done), _now() if done else None, key))
        conn.commit()
        return cur.rowcount > 0
