"""What's new and the satisfaction survey (CSAT): what the app should ask the
person right now, and recording their answers as Usage events.

What's new: once per version that has an entry in ``whats-new.json`` (beside
this module), the first time the app opens after an update. A new install
(no meeting processed yet) never sees it; it starts from its own version.

CSAT ("How satisfied are you with Cora?", 1-5 plus an optional comment): only
after CSAT_MIN_MEETINGS processed meetings, at most once every CSAT_EVERY_DAYS,
never again after "Don't ask again". Not while recording (the UI checks).

State lives in settings: whats_new_seen, csat_last_asked, csat_never. Answers
are Usage events (whats_new, csat): sent like every other event, so the share
toggle and enterprise lockdown decide whether they leave the Mac.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from pathlib import Path

import db
import usage_events

CSAT_MIN_MEETINGS = 3
CSAT_EVERY_DAYS = 30
COMMENT_MAX = 500


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def app_version() -> str:
    import ai_trace
    return str(ai_trace.app_versions().get("app_version") or "")


def _vkey(version: str) -> tuple:
    """1.0.0 > 0.4.6 > 0.4.6-beta.9: release before its prereleases."""
    core, _, pre = str(version).partition("-")
    nums = tuple(int(n) for n in re.findall(r"\d+", core)[:3])
    return nums + ((1,) if not pre else (0, *[int(n) for n in re.findall(r"\d+", pre)]))


def notes_file() -> Path:
    return Path(__file__).resolve().parent / "whats-new.json"


def whats_new_entry(version: str) -> dict[str, Any] | None:
    """The entry for `version`, else for its release (1.0.0 for 1.0.0-beta.2)."""
    try:
        notes = json.loads(notes_file().read_text())
    except (OSError, ValueError):
        return None
    for key in (version, version.partition("-")[0]):
        entry = notes.get(key)
        if isinstance(entry, dict) and entry.get("items"):
            return {"version": key, "title": str(entry.get("title") or f"What's new in Cora {key}"),
                    "items": [str(i) for i in entry["items"]][:8]}
    return None


def processed_meetings() -> int:
    with db.get_db() as conn:
        rows = conn.execute("SELECT payload FROM usage_events WHERE name = 'processing_finished'").fetchall()
    return sum(1 for r in rows if json.loads(r["payload"]).get("status") == "ok")


def state() -> dict[str, Any]:
    """GET /api/pulse: {whats_new: {version, title, items} | null, csat_due: bool}."""
    version = app_version()
    seen = db.get_setting("whats_new_seen")
    meetings = processed_meetings()
    whats_new = None
    if version:
        if not seen and meetings == 0:
            db.set_setting("whats_new_seen", version)   # a new install: nothing is new to it
        elif not seen or _vkey(seen) < _vkey(version):
            whats_new = whats_new_entry(version)
    return {"whats_new": whats_new, "csat_due": csat_due(meetings)}


def csat_due(meetings: int | None = None) -> bool:
    if db.get_setting("csat_never"):
        return False
    if (processed_meetings() if meetings is None else meetings) < CSAT_MIN_MEETINGS:
        return False
    last = db.get_setting("csat_last_asked")
    if last:
        try:
            if _now() - dt.datetime.fromisoformat(last) < dt.timedelta(days=CSAT_EVERY_DAYS):
                return False
        except ValueError:
            pass
    return True


def whats_new_closed(version: str, helpful: str | None) -> None:
    """POST /api/pulse/whats-new {version, helpful: up|down|null}: seen; never shown again for it."""
    version = str(version or app_version())[:32]
    current = db.get_setting("whats_new_seen")
    if not current or _vkey(current) < _vkey(version):
        db.set_setting("whats_new_seen", version)
    usage_events.record("whats_new", {"version": version,
                                      "helpful": helpful if helpful in ("up", "down") else None})


def csat_answer(score: Any = None, comment: str = "", outcome: str = "answered", trigger: str = "periodic") -> None:
    """POST /api/pulse/csat {score 1-5, comment} or {outcome: later|never}."""
    if outcome not in ("answered", "later", "never"):
        raise ValueError("outcome must be answered, later or never")
    if outcome == "answered":
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ValueError("score must be 1-5")
    db.set_setting("csat_last_asked", _now().isoformat())
    if outcome == "never":
        db.set_setting("csat_never", True)
    usage_events.record("csat", {"score": score if outcome == "answered" else None,
                                 "comment": str(comment or "").strip()[:COMMENT_MAX] if outcome == "answered" else "",
                                 "outcome": outcome, "trigger": str(trigger)[:32], "version": app_version()[:32],
                                 "meetings": processed_meetings()})
