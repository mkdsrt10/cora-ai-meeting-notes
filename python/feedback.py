"""Feedback for the beta (see docs/specs/beta-telemetry-and-updates.md).

A teammate's thumbs up or down on a Recording, on its notes, or on Cora
overall, with optional reasons and a short comment. The Settings general
message is the same thing with no Recording and target `overall`. Each one
is stored in the local `feedback` table, recorded as a `feedback` Usage
event, asks for the Recording to be captured, and wakes the sender.
"""
from __future__ import annotations

import datetime as dt
import json

import beta_sender
import capture
import db
import usage_events

TARGETS = ("recording", "notes", "overall")
RATINGS = ("up", "down")
REASONS = ("missed_items", "wrong_items", "wrong_speakers", "too_long", "other")
MAX_COMMENT = 500


def _validated(recording_id, target, rating, reasons, comment) -> tuple:
    if recording_id is not None and not isinstance(recording_id, str):
        raise ValueError("recording_id must be a string or null")
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}")
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}")
    reasons = [] if reasons is None else reasons
    if not isinstance(reasons, list) or any(r not in REASONS for r in reasons):
        raise ValueError(f"reasons must be a list drawn from {REASONS}")
    reasons = list(dict.fromkeys(reasons))
    comment = "" if comment is None else comment
    if not isinstance(comment, str):
        raise ValueError("comment must be a string")
    comment = comment.strip()
    if len(comment) > MAX_COMMENT:
        raise ValueError(f"comment longer than {MAX_COMMENT} characters")
    return recording_id or None, target, rating, reasons, comment


def submit(recording_id, target, rating, reasons=None, comment="") -> dict:
    """Store one Feedback; returns {id, capture_requested}. ValueError if
    invalid (including a recording id the receiver would refuse), in which
    case nothing is stored or queued. The row is written first: once the
    input is valid, the rating is kept even if queueing its capture fails."""
    recording_id, target, rating, reasons, comment = _validated(recording_id, target, rating, reasons, comment)
    if recording_id is not None and (not capture.SAFE_ID.fullmatch(recording_id) or recording_id in (".", "..")):
        raise ValueError(f"unsafe recording id {recording_id!r}")
    event = usage_events.validate("feedback", {"recording_id": recording_id, "target": target, "rating": rating,
                                               "reasons": ",".join(reasons), "comment": comment})
    created_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (recording_id, target, rating, reasons, comment, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (recording_id, target, rating, json.dumps(reasons), comment, created_at))
        conn.commit()
        feedback_id = cur.lastrowid
    capture_requested = False
    if recording_id:
        try:
            capture_requested = capture.request(recording_id, "feedback")
        except Exception as e:  # noqa: BLE001 - the rating is stored; the capture is best effort
            print(f"[feedback] capture request failed: {type(e).__name__}: {e}", flush=True)
    usage_events.record("feedback", event)
    try:
        beta_sender.flush_now()  # returns at once; the send happens on the sender's thread
    except Exception as e:  # noqa: BLE001 - a sender hiccup must not lose the user's rating
        print(f"[feedback] flush_now failed: {type(e).__name__}: {e}", flush=True)
    return {"id": feedback_id, "capture_requested": bool(capture_requested)}
