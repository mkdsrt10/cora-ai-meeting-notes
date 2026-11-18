"""Activity counters for the beta: Effort and Active time per local day
(see GLOSSARY.md and docs/TRACING.md).

The one owner of the counters. Every counted action, from the renderer,
Electron main or an existing Usage event, lands in the `ui_activity_counts`
table, keyed by local day and action id; the Cora main window's active
minutes sit in the same table under ACTIVE_MIN. Counts are atomic upserts, so
a crash or restart loses nothing, and several processes may count at once.

When a day is over (the sender's housekeeping tick, and on quit), its rows
become one `ui_action_count` per action and one `ui_activity` with the
totals, written to `usage_events` and deleted in the same transaction, so a
day is never emitted twice. Today's partial counts stay local until the day
is over; quitting only emits days that already ended.

Only action ids and counts leave this module: never text, names or ids.
"""
from __future__ import annotations

import datetime as dt

import db

DOING, BROWSING = "doing", "browsing"

# The fixed action list: id -> kind. Effort is the day's count of DOING.
ACTIONS: dict[str, str] = {
    # doing
    "start_recording": DOING,     # any source: the recording_started event
    "stop_recording": DOING,
    "pause_recording": DOING,
    "resume_recording": DOING,
    "save_notepad": DOING,        # one per save: the manual_notes_written event
    "correct_transcript": DOING,  # the transcript_corrected event
    "rename_meeting": DOING,
    "rename_speaker": DOING,
    "link_person": DOING,
    "add_person": DOING,          # the person_added event
    "rate": DOING,                # the feedback event
    "export_notes": DOING,        # the notes_exported event (not a copy)
    "copy_notes": DOING,          # the notes_exported event, kind copy
    "tick_todo": DOING,
    "file_to_folder": DOING,
    "reprocess": DOING,
    "retry": DOING,
    "change_setting": DOING,      # the setting_changed event
    # browsing
    "open_recording": BROWSING,
    "switch_view": BROWSING,
    "search": BROWSING,
    "filter": BROWSING,
    "toggle_enhanced_raw": BROWSING,
    "open_person": BROWSING,
    "open_settings": BROWSING,
}

ACTIVE_MIN = "@active_min"  # the reserved row holding the day's active minutes


def _today() -> str:
    return dt.date.today().isoformat()


def _add(action: str, amount: int = 1, day: str | None = None) -> None:
    with db.get_db() as conn:
        conn.execute("INSERT INTO ui_activity_counts (day, action, count) VALUES (?, ?, ?)"
                     " ON CONFLICT(day, action) DO UPDATE SET count = count + excluded.count",
                     (day or _today(), action, amount))
        conn.commit()


def count(action: str, day: str | None = None) -> None:
    """Count one action today. ValueError for an id not in ACTIONS."""
    if action not in ACTIONS:
        raise ValueError(f"unknown activity action: {action!r}")
    _add(action, 1, day)


def active_minute(day: str | None = None) -> None:
    """Count one active minute of the Cora main window today."""
    _add(ACTIVE_MIN, 1, day)


def action_for_event(name: str, payload: dict) -> str | None:
    """The action an existing Usage event already marks, if any. notes_edited
    rides along with the Notepad save's manual_notes_written, so it is not
    counted again."""
    if name == "notes_exported":
        return "copy_notes" if payload.get("kind") == "copy" else "export_notes"
    return {
        "recording_started": "start_recording",
        "manual_notes_written": "save_notepad",
        "transcript_corrected": "correct_transcript",
        "feedback": "rate",
        "person_added": "add_person",
        "setting_changed": "change_setting",
    }.get(name)


def count_event(name: str, payload: dict) -> None:
    """Count the action an existing Usage event marks (no-op for others)."""
    action = action_for_event(name, payload)
    if action:
        count(action)


def pending(day: str | None = None) -> dict:
    """The stored counts of `day` (default today): {active_min, doing,
    browsing, actions: {id: count}}. For tests and diagnostics."""
    day = day or _today()
    with db.get_db() as conn:
        rows = conn.execute("SELECT action, count FROM ui_activity_counts WHERE day = ?", (day,)).fetchall()
    return _summary({r["action"]: r["count"] for r in rows})


def _summary(counts: dict[str, int]) -> dict:
    actions = {a: n for a, n in sorted(counts.items()) if a in ACTIONS and n > 0}
    return {"active_min": int(counts.get(ACTIVE_MIN, 0)),
            "doing": sum(n for a, n in actions.items() if ACTIONS[a] == DOING),
            "browsing": sum(n for a, n in actions.items() if ACTIONS[a] == BROWSING),
            "actions": actions}


def emit_closed_days(today: str | None = None) -> list[str]:
    """Turn every stored day before `today` into its usage events and delete
    its rows, in one transaction. Returns the days emitted, oldest first."""
    import usage_events
    today = today or _today()
    with db.get_db() as conn:
        rows = conn.execute("SELECT day, action, count FROM ui_activity_counts WHERE day < ?"
                            " ORDER BY day, action", (today,)).fetchall()
        days: dict[str, dict[str, int]] = {}
        for r in rows:
            days.setdefault(r["day"], {})[r["action"]] = r["count"]
        for day, counts in days.items():
            s = _summary(counts)
            if s["active_min"] or s["actions"]:
                usage_events.insert(conn, "ui_activity", {"day": day, "active_min": s["active_min"],
                                                          "doing": s["doing"], "browsing": s["browsing"]})
                for action, n in s["actions"].items():
                    usage_events.insert(conn, "ui_action_count",
                                        {"day": day, "action": action, "kind": ACTIONS[action], "count": n})
        conn.execute("DELETE FROM ui_activity_counts WHERE day < ?", (today,))
        conn.commit()
    return list(days)


def emit_closed_days_safely() -> None:
    """emit_closed_days for the sender's housekeeping: never raises."""
    try:
        emit_closed_days()
    except Exception as e:  # noqa: BLE001 - telemetry never stops the sender
        print(f"[activity] emit failed: {type(e).__name__}: {e}", flush=True)


def post(body: dict) -> None:
    """POST /api/activity: {action: id} counts one action, {active_min: 1}
    one active minute. ValueError on anything else."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    action, minute = body.get("action"), body.get("active_min")
    if action is not None:
        count(action)
    elif minute == 1:
        active_minute()
    else:
        raise ValueError("expected action or active_min: 1")

