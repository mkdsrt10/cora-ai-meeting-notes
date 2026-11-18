"""Feedback (POST /api/feedback): a teammate's thumbs up or down on a
Recording, its notes, or Cora overall, plus the general message from the
Settings Beta panel. Driven over HTTP the way the renderer calls it, with a
stub receiver standing in for the Cora team. Observations: the response,
the stored feedback row, the "Show what Cora shares" export, the capture
queue, and what reached the receiver."""
import json

import pytest
from test_beta_sender import api, exported, port, stub, team_build, wait_for  # noqa: F401 - fixtures

RECORDING = "2026-11-10_14-00-00_meeting_feedback1"


@pytest.fixture
def clean(team_build):
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM captures")
        conn.commit()
    yield team_build
    with db.get_db() as conn:
        conn.execute("DELETE FROM captures")
        conn.commit()


def feedback_rows():
    import db
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM feedback ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def feedback_events():
    return [e["payload"] for e in exported() if e["name"] == "feedback"]


def test_a_rating_on_a_recording_is_stored_recorded_captured_and_sent_right_away(clean, port):
    status, reply = api(port, "POST", "/api/feedback", {
        "recording_id": RECORDING, "target": "notes", "rating": "down",
        "reasons": ["missed_items", "wrong_speakers"], "comment": "Missed the pricing decision"})

    assert status == 200
    assert reply["ok"] is True and isinstance(reply["id"], int) and reply["capture_requested"] is True
    [row] = feedback_rows()
    assert row["id"] == reply["id"]
    assert (row["recording_id"], row["target"], row["rating"]) == (RECORDING, "notes", "down")
    assert json.loads(row["reasons"]) == ["missed_items", "wrong_speakers"]
    assert row["comment"] == "Missed the pricing decision" and row["created_at"]
    assert feedback_events() == [{"recording_id": RECORDING, "target": "notes", "rating": "down",
                                  "reasons": "missed_items,wrong_speakers",
                                  "comment": "Missed the pricing decision"}]
    import capture
    assert capture.has_pending(RECORDING)
    assert wait_for(lambda: any(e["name"] == "feedback" for b in clean.batches() for e in b["events"]))


def test_a_general_message_from_settings_has_no_recording_and_captures_nothing(clean, port):
    status, reply = api(port, "POST", "/api/feedback", {
        "recording_id": None, "target": "overall", "rating": "up", "reasons": [],
        "comment": "Loving the speaker labels"})

    assert status == 200 and reply["ok"] is True and reply["capture_requested"] is False
    [row] = feedback_rows()
    assert (row["recording_id"], row["target"], row["rating"], json.loads(row["reasons"])) == (None, "overall", "up", [])
    assert feedback_events() == [{"recording_id": None, "target": "overall", "rating": "up", "reasons": "",
                                  "comment": "Loving the speaker labels"}]
    import capture
    assert capture.pending_count() == 0


def test_thumbs_up_needs_no_reasons_or_comment(clean, port):
    status, reply = api(port, "POST", "/api/feedback", {"recording_id": RECORDING, "target": "recording",
                                                       "rating": "up"})
    assert status == 200
    [row] = feedback_rows()
    assert (json.loads(row["reasons"]), row["comment"]) == ([], "")


def test_rating_a_recording_again_is_stored_but_captures_it_only_once(clean, port):
    first = api(port, "POST", "/api/feedback", {"recording_id": RECORDING, "target": "notes", "rating": "down",
                                                "reasons": ["too_long"]})[1]
    second = api(port, "POST", "/api/feedback", {"recording_id": RECORDING, "target": "recording", "rating": "up"})[1]

    assert (first["capture_requested"], second["capture_requested"]) == (True, False)
    assert [r["target"] for r in feedback_rows()] == ["notes", "recording"]
    assert len(feedback_events()) == 2


def test_with_sharing_off_the_rating_is_kept_locally_and_nothing_is_captured(clean, port):
    import db
    db.set_setting("share_usage", False)
    status, reply = api(port, "POST", "/api/feedback", {"recording_id": RECORDING, "target": "notes",
                                                       "rating": "down", "reasons": ["other"]})
    assert status == 200 and reply["capture_requested"] is False
    assert len(feedback_rows()) == 1 and len(feedback_events()) == 1
    import capture
    assert not capture.has_pending(RECORDING)


def test_a_general_message_may_have_no_rating(clean, port):
    status, reply = api(port, "POST", "/api/feedback", {
        "recording_id": None, "target": "overall", "rating": None, "reasons": [],
        "comment": "Export to Notion would help"})

    assert status == 200 and reply["ok"] is True
    [row] = feedback_rows()
    assert (row["recording_id"], row["target"], row["rating"]) == (None, "overall", None)
    assert feedback_events() == [{"recording_id": None, "target": "overall", "rating": None, "reasons": "",
                                  "comment": "Export to Notion would help"}]


@pytest.mark.parametrize("body, complaint", [
    ({"recording_id": None, "target": "overall", "rating": None, "comment": ""}, "comment"),
    ({"recording_id": RECORDING, "target": "notes", "rating": None, "comment": "words"}, "rating"),
])
def test_without_a_rating_only_a_general_message_with_words_is_accepted(clean, port, body, complaint):
    status, reply = api(port, "POST", "/api/feedback", body)
    assert status == 400 and complaint in reply["error"]
    assert feedback_rows() == []


def test_an_old_feedback_table_with_a_required_rating_is_migrated(clean):
    import db
    with db.get_db() as conn:
        conn.execute("DROP TABLE feedback")
        conn.execute("CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id TEXT,"
                     " target TEXT NOT NULL, rating TEXT NOT NULL, reasons TEXT NOT NULL DEFAULT '[]',"
                     " comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)")
        conn.execute("INSERT INTO feedback (target, rating, created_at) VALUES ('overall', 'up', 'then')")
        conn.commit()
    db.init_db()
    with db.get_db() as conn:
        notnull = {r["name"]: r["notnull"] for r in conn.execute("PRAGMA table_info(feedback)")}
        rows = [dict(r) for r in conn.execute("SELECT target, rating FROM feedback")]
    assert notnull["rating"] == 0
    assert rows == [{"target": "overall", "rating": "up"}]


VALID = {"recording_id": RECORDING, "target": "notes", "rating": "down", "reasons": ["missed_items"], "comment": ""}


@pytest.mark.parametrize("change, complaint", [
    ({"target": "summary"}, "target"),
    ({"target": None}, "target"),
    ({"rating": "meh"}, "rating"),
    ({"rating": None}, "rating"),
    ({"reasons": ["bad_vibes"]}, "reasons"),
    ({"reasons": "missed_items"}, "reasons"),
    ({"comment": "x" * 501}, "500"),
    ({"comment": 42}, "comment"),
    ({"recording_id": "../../etc"}, "unsafe recording id"),
    ({"recording_id": 7}, "recording_id"),
])
def test_invalid_feedback_is_refused_and_nothing_is_stored_or_queued(clean, port, change, complaint):
    status, reply = api(port, "POST", "/api/feedback", {**VALID, **change})

    assert status == 400 and complaint in reply["error"]
    assert feedback_rows() == [] and feedback_events() == []
    import capture
    assert capture.pending_count() == 0


def test_a_comment_of_exactly_500_characters_is_accepted(clean, port):
    status, _ = api(port, "POST", "/api/feedback", {**VALID, "comment": "x" * 500})
    assert status == 200
    assert feedback_events()[0]["comment"] == "x" * 500


def test_a_rating_is_kept_and_recorded_even_when_queueing_the_capture_fails(clean, port, monkeypatch):
    import sqlite3

    import capture

    def locked(recording_id, reason):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(capture, "request", locked)

    status, reply = api(port, "POST", "/api/feedback", VALID)

    assert status == 200 and reply["ok"] is True and reply["capture_requested"] is False
    [row] = feedback_rows()
    assert row["id"] == reply["id"] and row["recording_id"] == RECORDING
    assert [e["recording_id"] for e in feedback_events()] == [RECORDING]
