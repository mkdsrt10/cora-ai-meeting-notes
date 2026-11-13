"""Effort and Active time (python/activity.py): actions and active minutes are
counted per local day, existing Usage events that mark a doing action count
once, and a day that ended becomes one `ui_activity` plus one
`ui_action_count` per action, exactly once, visible in the export and sent
only under the usual sharing rules."""
import http.client
import json
import threading
from pathlib import Path

import pytest

TOKEN = "activity-test-token"


@pytest.fixture(scope="module")
def port():
    import server
    from api import auth
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.execute("DELETE FROM ui_activity_counts")
        conn.execute("DELETE FROM settings WHERE key IN ('share_usage', 'install_id')")
        conn.commit()
    for var in ("CORA_BUILD_VARIANT", "CORA_BETA_RECEIVER_URL", "CORA_BETA_TOKEN", "VOICECOACH_ENTERPRISE_LOCKDOWN"):
        monkeypatch.delenv(var, raising=False)


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def events(name=None):
    import usage_events
    rows = usage_events._rows()
    return [r["payload"] for r in rows if name is None or r["name"] == name]


# ---- the action list -----------------------------------------------------------------

def test_the_action_list_is_a_fixed_set_of_snake_case_ids_each_doing_or_browsing():
    import activity
    assert 20 <= len(activity.ACTIONS) <= 30
    assert all(a.replace("_", "").isalpha() and a == a.lower() for a in activity.ACTIONS)
    assert set(activity.ACTIONS.values()) == {"doing", "browsing"}
    assert {a for a, k in activity.ACTIONS.items() if k == "browsing"} == {
        "open_recording", "switch_view", "search", "filter", "toggle_enhanced_raw", "open_person", "open_settings"}


def test_renderer_and_main_only_count_ids_in_the_list():
    """Every literal id the JS counts (trackAction, data-track, countAction)
    is in ACTIONS, so no click is silently refused with a 400."""
    import re
    import activity
    root = Path(__file__).resolve().parents[1] / "src"
    used = set()
    for path in list(root.rglob("*.js")):
        text = path.read_text()
        used |= set(re.findall(r"trackAction(?:Settled)?\('([a-z_]+)'", text))
        used |= set(re.findall(r'data-track="([a-z_]+)"', text))
        used |= set(re.findall(r"countAction\('([a-z_]+)'\)", text))
        for pair in re.findall(r"trackAction\([^)]*\?'([a-z_]+)':'([a-z_]+)'\)", text):
            used |= set(pair)
    assert used, "no counted actions found"
    assert used <= set(activity.ACTIONS), used - set(activity.ACTIONS)


# ---- counting --------------------------------------------------------------------------

def test_actions_and_active_minutes_accumulate_per_day():
    import activity
    for action in ("rename_meeting", "rename_meeting", "tick_todo", "search"):
        activity.count(action, day="2026-11-10")
    activity.active_minute(day="2026-11-10")
    activity.active_minute(day="2026-11-10")
    activity.count("search", day="2026-11-11")
    assert activity.pending("2026-11-10") == {
        "active_min": 2, "doing": 3, "browsing": 1,
        "actions": {"rename_meeting": 2, "search": 1, "tick_todo": 1}}
    assert activity.pending("2026-11-11")["browsing"] == 1


def test_an_unknown_action_is_refused():
    import activity
    with pytest.raises(ValueError):
        activity.count("read_the_notes_aloud")


@pytest.mark.parametrize("name, payload, action", [
    ("recording_started", {"recording_id": "r1"}, "start_recording"),
    ("manual_notes_written", {"recording_id": "r1", "chars": 10, "phase": "after"}, "save_notepad"),
    ("transcript_corrected", {"recording_id": "r1", "corrections": 3}, "correct_transcript"),
    ("feedback", {"recording_id": "r1", "rating": "up"}, "rate"),
    ("notes_exported", {"recording_id": "r1", "kind": "markdown"}, "export_notes"),
    ("notes_exported", {"recording_id": "r1", "kind": "copy"}, "copy_notes"),
    ("person_added", {"source": "people_page"}, "add_person"),
    ("setting_changed", {"key": "retain_audio", "value": "true"}, "change_setting"),
])
def test_an_existing_event_that_marks_a_doing_action_counts_it_once(name, payload, action):
    import activity
    import usage_events
    usage_events.record(name, payload)
    assert activity.pending()["actions"] == {action: 1}
    assert activity.pending()["doing"] == 1


def test_a_notepad_save_with_its_notes_edited_counts_one_save():
    import activity
    import usage_events
    usage_events.record("manual_notes_written", {"recording_id": "r1", "chars": 10, "phase": "after"})
    usage_events.record("notes_edited", {"recording_id": "r1", "edit_ratio": 0.2})
    usage_events.record("notes_viewed", {"recording_id": "r1"})
    assert activity.pending()["actions"] == {"save_notepad": 1}


# ---- emitting a day ------------------------------------------------------------------

def test_a_day_that_ended_is_emitted_once_with_totals_and_per_action_counts():
    import activity
    for action in ("start_recording", "stop_recording", "rename_meeting", "open_recording", "open_recording"):
        activity.count(action, day="2026-11-10")
    for _ in range(7):
        activity.active_minute(day="2026-11-10")
    activity.count("tick_todo", day="2026-11-11")  # today: stays local

    assert activity.emit_closed_days(today="2026-11-11") == ["2026-11-10"]
    assert events("ui_activity") == [{"day": "2026-11-10", "active_min": 7, "doing": 3, "browsing": 2}]
    assert sorted(events("ui_action_count"), key=lambda p: p["action"]) == [
        {"day": "2026-11-10", "action": "open_recording", "kind": "browsing", "count": 2},
        {"day": "2026-11-10", "action": "rename_meeting", "kind": "doing", "count": 1},
        {"day": "2026-11-10", "action": "start_recording", "kind": "doing", "count": 1},
        {"day": "2026-11-10", "action": "stop_recording", "kind": "doing", "count": 1},
    ]
    # Never twice: a second pass (another tick, the quit, a restart) sends nothing.
    assert activity.emit_closed_days(today="2026-11-11") == []
    assert activity.emit_closed_days(today="2026-11-12") == ["2026-11-11"]
    assert [p["day"] for p in events("ui_activity")] == ["2026-11-10", "2026-11-11"]


def test_counts_survive_a_restart_because_they_live_in_the_database():
    import activity
    import importlib
    activity.count("reprocess", day="2026-11-10")
    importlib.reload(activity)
    assert activity.pending("2026-11-10")["actions"] == {"reprocess": 1}


def test_a_day_with_only_active_time_still_reports_it():
    import activity
    activity.active_minute(day="2026-11-09")
    activity.emit_closed_days(today="2026-11-10")
    assert events("ui_activity") == [{"day": "2026-11-09", "active_min": 1, "doing": 0, "browsing": 0}]
    assert events("ui_action_count") == []


def test_the_senders_housekeeping_emits_ended_days_before_a_flush(monkeypatch):
    import activity
    import beta_sender
    activity.count("retry", day="2000-01-01")
    beta_sender._housekeeping()
    assert events("ui_activity") == [{"day": "2000-01-01", "active_min": 0, "doing": 1, "browsing": 0}]


def test_activity_events_are_unsent_rows_in_the_queue_like_any_other():
    """Recorded locally whatever the toggle; the sender (and lockdown) decide delivery."""
    import activity
    import usage_events
    activity.count("search", day="2026-11-01")
    activity.emit_closed_days(today="2026-11-02")
    assert usage_events.sharing_enabled() is False
    assert {e["name"] for e in usage_events.pending_batch()["events"]} == {"ui_activity", "ui_action_count"}


def test_lockdown_still_records_locally_but_never_shares(monkeypatch):
    import activity
    import usage_events
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", "https://example.invalid")
    monkeypatch.setenv("CORA_BETA_TOKEN", "t")
    activity.count("search", day="2026-11-01")
    activity.emit_closed_days(today="2026-11-02")
    assert events("ui_activity")
    assert usage_events.sharing_enabled() is False


# ---- the route --------------------------------------------------------------------------

def test_post_api_activity_counts_an_action_or_an_active_minute(port):
    import activity
    assert call(port, "POST", "/api/activity", {"action": "open_settings"}) == (200, {"ok": True})
    assert call(port, "POST", "/api/activity", {"active_min": 1}) == (200, {"ok": True})
    assert activity.pending() == {"active_min": 1, "doing": 0, "browsing": 1, "actions": {"open_settings": 1}}


@pytest.mark.parametrize("body", [{"action": "Board sync"}, {"active_min": 5}, {}, {"action": None}])
def test_post_api_activity_refuses_anything_else(port, body):
    import activity
    status, payload = call(port, "POST", "/api/activity", body)
    assert status == 400 and payload["error"]
    assert activity.pending()["actions"] == {} and activity.pending()["active_min"] == 0


def test_onboarding_completed_and_the_activity_events_are_in_the_catalog_and_the_export(port):
    import activity
    assert call(port, "POST", "/api/events", {"name": "onboarding_completed",
                                              "payload": {"processing_mode": "local"}})[0] == 200
    activity.count("search", day="2026-11-01")
    activity.emit_closed_days(today="2026-11-02")
    status, out = call(port, "GET", "/api/events/export")
    assert status == 200
    names = [json.loads(line)["name"] for line in Path(out["path"]).read_text().splitlines()]
    assert names == ["onboarding_completed", "ui_activity", "ui_action_count"]
    # No content can ride along: the activity events take only their fixed keys.
    assert call(port, "POST", "/api/events", {"name": "ui_action_count",
                                              "payload": {"action": "search", "query": "q3 budget"}})[0] == 400
