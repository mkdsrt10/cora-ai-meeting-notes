"""Usage event store for the beta (see docs/specs/beta-telemetry-and-updates.md).

Usage events are small, fixed-shape facts about how Cora is used. They are
written to the local `usage_events` table whatever the share toggle says; the
toggle (and enterprise lockdown, and the build's receiver config) only decide
whether the sender delivers them. Every payload is checked against CATALOG:
known event name, known keys, scalar values, short strings.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

import db

MAX_STRING = 200
LONG_STRINGS = {("feedback", "comment"): 500}
QUEUE_MAX_AGE_DAYS = 7
QUEUE_MAX_BYTES = 5_000_000

CATALOG: dict[str, frozenset[str]] = {name: frozenset(keys.split()) for name, keys in {
    "app_started": "macos chip ram_gb processing_mode microphone_kind lockdown",
    "recording_started": "recording_id meeting_app surface microphone_kind started_from",
    "recording_stopped": "recording_id meeting_app surface duration_s chunks pauses mic_reconnects ended_by",
    "participants_captured": "recording_id count method warnings linked_people",
    "processing_finished": "recording_id status error_code transcriber_provider transcriber_model text_provider"
                           " text_model transcription_s summarization_s total_s tokens_in tokens_out"
                           " window_fallbacks speech_s silence_s retries peak_rss_mb duration_s",
    "notes_viewed": "recording_id",
    "notes_edited": "recording_id edit_ratio",
    "transcript_corrected": "recording_id corrections",
    "action_items_counted": "recording_id count",
    "notes_exported": "recording_id kind content notepad outcome",
    "manual_notes_written": "recording_id chars phase",
    "screenshot_taken": "recording_id count ocr",
    "person_added": "source",
    "setting_changed": "key value",
    "people_snapshot": "people recordings disk_mb",
    "error": "scope code",
    "feedback": "recording_id target rating reasons comment",
    "events_dropped": "count",
    "capture_dropped": "recording_id reason",
    "update_available": "from_version to_version",
    "update_started": "from_version to_version",
    "update_finished": "from_version to_version status error_code",
    "call_detected": "app trigger confirmed seconds_to_prompt",
    "call_prompt_action": "action",
    "detect_fallback": "reason",
}.items()}


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def validate(name, payload) -> dict:
    if not isinstance(name, str) or name not in CATALOG:
        raise ValueError(f"unknown usage event: {name!r}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    extra = sorted(set(payload) - CATALOG[name])
    if extra:
        raise ValueError(f"{name}: unknown payload keys {extra}")
    for key, value in payload.items():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"{name}.{key}: value must be a string, number, boolean or null")
        limit = LONG_STRINGS.get((name, key), MAX_STRING)
        if isinstance(value, str) and len(value) > limit:
            raise ValueError(f"{name}.{key}: string longer than {limit} characters")
    return dict(payload)


def record(name: str, payload: dict) -> int:
    """Validate and store one Usage event; returns its id. ValueError if invalid."""
    payload = validate(name, payload)
    with db.get_db() as conn:
        cur = conn.execute("INSERT INTO usage_events (created_at, name, payload) VALUES (?, ?, ?)",
                           (_iso(_now()), name, json.dumps(payload, separators=(",", ":"))))
        conn.commit()
        event_id = cur.lastrowid
    if name == "processing_finished":
        _sample_capture(payload)
    return event_id


def _sample_capture(payload: dict) -> None:
    """A finished Recording may fall in the Captured Recording sample
    (python/capture.py). Never lets sampling fail the event."""
    try:
        import capture
        capture.sample(payload)
    except Exception as e:  # noqa: BLE001
        print(f"[usage_events] capture sampling failed: {type(e).__name__}: {e}", flush=True)


def _rows(where: str = "", params: tuple = ()) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(f"SELECT * FROM usage_events {where} ORDER BY id", params).fetchall()
    return [{"id": r["id"], "name": r["name"], "ts": r["created_at"], "payload": json.loads(r["payload"]),
             "sent_at": r["sent_at"]} for r in rows]


def unsent_count() -> int:
    with db.get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM usage_events WHERE sent_at IS NULL").fetchone()[0]


# ---- install identity and settings ---------------------------------------------

def install_id() -> str:
    """This Install's random id, created on first use and kept forever."""
    value = db.get_setting("install_id")
    if not value:
        value = str(uuid.uuid4())
        db.set_setting("install_id", value)
    return value


def build_variant() -> str:
    return "team" if os.environ.get("CORA_BUILD_VARIANT") == "team" else "public"


def share_usage() -> bool:
    """The effective share toggle: the saved choice (default on for team
    builds, off for public ones), always off under enterprise lockdown."""
    import policy
    if policy.lockdown_enabled():
        return False
    saved = db.get_setting("share_usage")
    return build_variant() == "team" if saved is None else bool(saved)


def sharing_enabled() -> bool:
    """Whether the sender may deliver anything: the toggle is on, lockdown is
    off, and this build carries a receiver URL and token."""
    return bool(share_usage() and os.environ.get("CORA_BETA_RECEIVER_URL", "").strip()
                and os.environ.get("CORA_BETA_TOKEN", "").strip())


def _versions() -> tuple[str | None, str | None]:
    """The Electron-stamped version and commit (repo lookup from source)."""
    import ai_trace
    info = ai_trace.app_versions()
    return info.get("app_version"), info.get("git_commit")


# ---- the send queue --------------------------------------------------------------

def pending_batch(limit_bytes: int = 5_000_000) -> dict:
    """Unsent events, oldest first, up to about `limit_bytes` of JSON, wrapped
    with the Install's identity. At least one event when any is pending."""
    version, commit = _versions()
    events, size = [], 0
    for row in _rows("WHERE sent_at IS NULL"):
        row.pop("sent_at")
        size += len(json.dumps(row))
        if events and size > limit_bytes:
            break
        events.append(row)
    return {"install_id": install_id(), "display_name": db.get_setting("beta_display_name"),
            "app_version": version, "git_commit": commit, "build_variant": build_variant(), "events": events}


def mark_sent(ids) -> None:
    ids = list(ids)
    if not ids:
        return
    with db.get_db() as conn:
        conn.execute(f"UPDATE usage_events SET sent_at = ? WHERE id IN ({','.join('?' * len(ids))})",
                     (_iso(_now()), *ids))
        conn.commit()


def prune_local(days: int = 30) -> int:
    """Delete rows, sent or not, older than `days`. Returns how many."""
    cutoff = _iso(_now() - dt.timedelta(days=days))
    with db.get_db() as conn:
        removed = conn.execute("DELETE FROM usage_events WHERE created_at < ?", (cutoff,)).rowcount
        conn.commit()
    return removed


def enforce_queue_limits() -> int:
    """Drop unsent rows older than 7 days, then the oldest unsent rows while
    the unsent payload exceeds 5 MB. If any went, the unsent queue holds one
    `events_dropped` with the running total: an earlier unsent one is folded
    into it (so a long spell with sharing off leaves one row, not one per
    pass). Returns how many events were dropped by this call."""
    cutoff = _iso(_now() - dt.timedelta(days=QUEUE_MAX_AGE_DAYS))
    kept = "sent_at IS NULL AND name != 'events_dropped'"
    with db.get_db() as conn:
        dropped = conn.execute(f"DELETE FROM usage_events WHERE {kept} AND created_at < ?",
                               (cutoff,)).rowcount
        rows = conn.execute("SELECT id, LENGTH(name) + LENGTH(payload) + 64 AS size FROM usage_events"
                            f" WHERE {kept} ORDER BY id DESC").fetchall()
        total, over = 0, []
        for row in rows:
            total += row["size"]
            if total > QUEUE_MAX_BYTES:
                over.append(row["id"])
        if over:
            conn.execute(f"DELETE FROM usage_events WHERE id IN ({','.join('?' * len(over))})", over)
        dropped += len(over)
        earlier = 0
        if dropped:
            for row in conn.execute("SELECT payload FROM usage_events"
                                    " WHERE sent_at IS NULL AND name = 'events_dropped'").fetchall():
                earlier += int(json.loads(row["payload"]).get("count") or 0)
            conn.execute("DELETE FROM usage_events WHERE sent_at IS NULL AND name = 'events_dropped'")
        conn.commit()
    if dropped:
        record("events_dropped", {"count": dropped + earlier})
    return dropped


def export_jsonl(path) -> Path:
    """Every stored row, sent and unsent, one JSON object per line: what
    "Show what Cora shares" reveals."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in _rows()))
    return path
