"""Usage event store, beta settings and the beta routes, driven over HTTP the
way Electron main and the renderer call them (POST /api/events, GET
/api/events/export, GET /api/beta/status, the settings routes)."""
import http.client
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "usage-events-test-token"
BETA_KEYS = ("install_id", "beta_display_name", "share_usage", "audio_retention_days", "audio_cap_mb")


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
def fresh_store(monkeypatch):
    """Each test starts with no events and no beta settings, outside lockdown,
    on a public build with no receiver configured."""
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(BETA_KEYS))})", BETA_KEYS)
        conn.commit()
    for var in ("CORA_BUILD_VARIANT", "CORA_BETA_RECEIVER_URL", "CORA_BETA_TOKEN", "CORA_APP_VERSION",
                "CORA_GIT_COMMIT", "VOICECOACH_ENTERPRISE_LOCKDOWN"):
        monkeypatch.delenv(var, raising=False)


def call(port, method, path, body=None, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def exported(port):
    status, payload = call(port, "GET", "/api/events/export")
    assert status == 200
    lines = Path(payload["path"]).read_text().splitlines()
    return [json.loads(line) for line in lines]


# ---- recording events -----------------------------------------------------------

def test_a_valid_event_is_stored_and_appears_in_the_export(port):
    status, payload = call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {"recording_id": "r1"}})
    assert status == 200 and payload["ok"] is True and isinstance(payload["id"], int)
    [row] = exported(port)
    assert row["id"] == payload["id"]
    assert row["name"] == "notes_viewed" and row["payload"] == {"recording_id": "r1"}
    assert row["ts"] and row["sent_at"] is None


def test_a_sparse_payload_is_accepted_and_stored_as_given(port):
    body = {"name": "processing_finished", "payload": {"recording_id": "r2", "status": "ok", "total_s": 41.5,
                                                         "error_code": None}}
    assert call(port, "POST", "/api/events", body)[0] == 200
    assert call(port, "POST", "/api/events", {"name": "person_added", "payload": {}})[0] == 200
    rows = exported(port)
    assert [r["payload"] for r in rows] == [body["payload"], {}]


@pytest.mark.parametrize("body, complaint", [
    ({"name": "made_up", "payload": {}}, "unknown usage event"),
    ({"payload": {}}, "unknown usage event"),
    ({"name": "notes_viewed", "payload": {"recording_id": "r1", "title": "Board sync"}}, "title"),
    ({"name": "notes_viewed", "payload": {"recording_id": ["r1"]}}, "recording_id"),
    ({"name": "error", "payload": {"scope": "main", "code": {"errno": 2}}}, "code"),
    ({"name": "notes_viewed", "payload": "r1"}, "payload"),
    ({"name": "error", "payload": {"scope": "main", "code": "x" * 201}}, "200"),
    ({"name": "feedback", "payload": {"comment": "x" * 501}}, "500"),
])
def test_an_event_outside_the_catalog_is_refused_and_nothing_is_stored(port, body, complaint):
    status, payload = call(port, "POST", "/api/events", body)
    assert status == 400 and complaint in payload["error"]
    assert exported(port) == []


def test_strings_up_to_the_limits_are_accepted(port):
    assert call(port, "POST", "/api/events", {"name": "error", "payload": {"scope": "main", "code": "x" * 200}})[0] == 200
    assert call(port, "POST", "/api/events", {"name": "feedback", "payload": {"comment": "y" * 500}})[0] == 200
    assert len(exported(port)) == 2


def test_events_need_the_api_token(port):
    assert call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {}}, token="wrong")[0] == 401


# ---- install identity and beta settings ------------------------------------------

def setting(port, key):
    status, payload = call(port, "GET", f"/api/settings?key={key}")
    assert status == 200
    return payload["value"]


def test_install_id_is_created_once_and_survives_a_server_restart(port):
    first = setting(port, "install_id")
    assert len(first) == 36 and first == setting(port, "install_id")
    assert call(port, "POST", "/api/settings", {"key": "install_id"}) == (200, {"value": first})
    restarted = subprocess.run(
        [sys.executable, "-c", "import usage_events; print(usage_events.install_id())"],
        cwd=ROOT / "python", env={**os.environ}, capture_output=True, text=True, timeout=30)
    assert restarted.stdout.strip() == first, restarted.stderr


def test_install_id_cannot_be_changed_through_the_api(port):
    first = setting(port, "install_id")
    status, payload = call(port, "POST", "/api/settings", {"key": "install_id", "value": "someone-else"})
    assert status == 400 and "install_id" in payload["error"]
    assert setting(port, "install_id") == first


@pytest.mark.parametrize("variant, default", [("team", True), ("public", False), (None, False)])
def test_share_usage_defaults_on_for_team_builds_only(port, monkeypatch, variant, default):
    if variant:
        monkeypatch.setenv("CORA_BUILD_VARIANT", variant)
    assert setting(port, "share_usage") is default
    assert call(port, "POST", "/api/settings", {"key": "share_usage", "value": not default}) == (200, {"ok": True})
    assert setting(port, "share_usage") is (not default)


def test_lockdown_turns_sharing_off_whatever_the_toggle_says(port, monkeypatch):
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", "https://receiver.example.ts.net")
    monkeypatch.setenv("CORA_BETA_TOKEN", "t0ken")
    call(port, "POST", "/api/settings", {"key": "share_usage", "value": True})
    assert call(port, "GET", "/api/beta/status")[1]["sharing_enabled"] is True
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert setting(port, "share_usage") is False
    assert call(port, "GET", "/api/beta/status")[1]["sharing_enabled"] is False
    # Events are still kept locally under lockdown; only sending is off.
    assert call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {}})[0] == 200


@pytest.mark.parametrize("url, token", [("", "t0ken"), ("https://receiver.example.ts.net", ""), ("", "")])
def test_sharing_needs_a_receiver_url_and_token_in_the_build(port, monkeypatch, url, token):
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", url)
    monkeypatch.setenv("CORA_BETA_TOKEN", token)
    call(port, "POST", "/api/settings", {"key": "share_usage", "value": True})
    assert call(port, "GET", "/api/beta/status")[1]["sharing_enabled"] is False


def test_beta_status_counts_unsent_events_and_leaves_sender_fields_empty(port):
    for _ in range(3):
        call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {}})
    assert call(port, "GET", "/api/beta/status") == (200, {
        "sharing_enabled": False, "unsent_events": 3, "pending_captures": None,
        "last_flush_at": None, "last_error": None})


def test_display_name_is_saved_trimmed_and_clears_to_null(port):
    assert setting(port, "beta_display_name") is None
    assert call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": "  Priya  "}) == (200, {"ok": True})
    assert setting(port, "beta_display_name") == "Priya"
    assert call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": None}) == (200, {"ok": True})
    assert setting(port, "beta_display_name") is None
    call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": "Priya"})
    assert call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": "  "}) == (200, {"ok": True})
    assert setting(port, "beta_display_name") is None


def test_audio_retention_defaults_to_30_days_and_500_mb(port):
    assert setting(port, "audio_retention_days") == 30
    assert setting(port, "audio_cap_mb") == 500
    assert call(port, "POST", "/api/settings", {"key": "audio_retention_days", "value": 7}) == (200, {"ok": True})
    assert call(port, "POST", "/api/settings", {"key": "audio_cap_mb", "value": 50}) == (200, {"ok": True})
    assert (setting(port, "audio_retention_days"), setting(port, "audio_cap_mb")) == (7, 50)


@pytest.mark.parametrize("key, bad", [
    ("audio_retention_days", 0), ("audio_retention_days", "30"), ("audio_retention_days", 1.5),
    ("audio_retention_days", True), ("audio_cap_mb", 49), ("audio_cap_mb", "big"),
    ("share_usage", "yes"), ("share_usage", 1), ("beta_display_name", 42), ("beta_display_name", "x" * 101),
])
def test_invalid_beta_settings_are_refused_and_the_value_kept(port, key, bad):
    before = setting(port, key)
    status, payload = call(port, "POST", "/api/settings", {"key": key, "value": bad})
    assert status == 400 and key in payload["error"]
    assert setting(port, key) == before


def test_the_batch_carries_the_install_identity_and_build_stamp(port, monkeypatch):
    import usage_events
    monkeypatch.setenv("CORA_APP_VERSION", "0.4.0")
    monkeypatch.setenv("CORA_GIT_COMMIT", "abc1234")
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    import ai_trace  # the stamp is read once per process; Electron sets it at spawn
    ai_trace.app_versions.cache_clear()
    monkeypatch.setattr(ai_trace, "app_versions", ai_trace.app_versions.__wrapped__)
    call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": "Priya"})
    _, first = call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {"recording_id": "r1"}})
    _, second = call(port, "POST", "/api/events", {"name": "person_added", "payload": {"source": "people_page"}})
    batch = usage_events.pending_batch()
    assert {k: v for k, v in batch.items() if k != "events"} == {
        "install_id": setting(port, "install_id"), "display_name": "Priya",
        "app_version": "0.4.0", "git_commit": "abc1234", "build_variant": "team"}
    assert [(e["id"], e["name"], e["payload"]) for e in batch["events"]] == [
        (first["id"], "notes_viewed", {"recording_id": "r1"}), (second["id"], "person_added", {"source": "people_page"})]
    assert all(set(e) == {"id", "name", "ts", "payload"} for e in batch["events"])

    usage_events.mark_sent([first["id"]])
    assert [e["id"] for e in usage_events.pending_batch()["events"]] == [second["id"]]
    assert call(port, "GET", "/api/beta/status")[1]["unsent_events"] == 1
    assert [bool(r["sent_at"]) for r in exported(port)] == [True, False]


# ---- keeping the store small -----------------------------------------------------

@pytest.fixture
def clock(monkeypatch):
    """`clock.days_ago(n)` makes events recorded from then on n days old."""
    import datetime as dt
    import usage_events
    real_now = usage_events._now
    state = {"offset": dt.timedelta(0)}
    monkeypatch.setattr(usage_events, "_now", lambda: real_now() - state["offset"])

    class Clock:
        def days_ago(self, days):
            state["offset"] = dt.timedelta(days=days)
    return Clock()


def post_viewed(port, recording_id):
    return call(port, "POST", "/api/events", {"name": "notes_viewed", "payload": {"recording_id": recording_id}})[1]["id"]


def test_rows_older_than_30_days_are_pruned_sent_or_not(port, clock):
    import usage_events
    clock.days_ago(31)
    old_sent, old_unsent = post_viewed(port, "old-sent"), post_viewed(port, "old-unsent")
    clock.days_ago(29)
    recent = post_viewed(port, "recent")
    clock.days_ago(0)
    usage_events.mark_sent([old_sent])
    assert usage_events.prune_local() == 2
    assert [r["id"] for r in exported(port)] == [recent]
    assert old_unsent not in [e["id"] for e in usage_events.pending_batch()["events"]]


def test_unsent_rows_older_than_7_days_are_dropped_and_counted_once(port, clock):
    import usage_events
    clock.days_ago(8)
    post_viewed(port, "stale-1")
    sent_long_ago = post_viewed(port, "stale-but-sent")
    post_viewed(port, "stale-2")
    clock.days_ago(6)
    fresh = post_viewed(port, "fresh")
    clock.days_ago(0)
    usage_events.mark_sent([sent_long_ago])
    assert usage_events.enforce_queue_limits() == 2
    rows = exported(port)
    assert [r["id"] for r in rows[:2]] == [sent_long_ago, fresh]
    assert [(r["name"], r["payload"]) for r in rows[2:]] == [("events_dropped", {"count": 2})]
    assert usage_events.enforce_queue_limits() == 0
    assert len(exported(port)) == 3


def test_unsent_rows_beyond_5_mb_are_dropped_oldest_first(port, monkeypatch):
    import usage_events
    assert usage_events.QUEUE_MAX_BYTES == 5_000_000  # shrunk below so the test stays small
    ids = [call(port, "POST", "/api/events", {"name": "error", "payload": {"scope": "main", "code": "x" * 190}})[1]["id"]
           for _ in range(6)]
    one_row = len(json.dumps({"scope": "main", "code": "x" * 190}))
    monkeypatch.setattr(usage_events, "QUEUE_MAX_BYTES", one_row * 4 + 300)  # room for four of them, not five
    assert usage_events.enforce_queue_limits() == 2
    rows = exported(port)
    assert [r["id"] for r in rows[:-1]] == ids[2:]
    assert rows[-1]["name"] == "events_dropped" and rows[-1]["payload"] == {"count": 2}


def test_a_batch_stops_at_the_byte_limit_but_always_carries_one_event(port):
    import usage_events
    ids = [post_viewed(port, f"r{i}") for i in range(3)]
    assert [e["id"] for e in usage_events.pending_batch(limit_bytes=1)["events"]] == ids[:1]
    assert [e["id"] for e in usage_events.pending_batch()["events"]] == ids
