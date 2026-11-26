"""What's new and the satisfaction survey (python/pulse.py, /api/pulse): who
sees what when, and that answers become Usage events with fixed fields only."""
import datetime as dt
import http.client
import json
import threading

import pytest

TOKEN = "pulse-test-token"


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
    import pulse
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.execute("DELETE FROM settings WHERE key IN ('whats_new_seen', 'csat_last_asked', 'csat_never')")
        conn.commit()
    monkeypatch.setattr(pulse, "app_version", lambda: "1.0.0")


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def processed(n):
    import usage_events
    for i in range(n):
        usage_events.record("processing_finished", {"recording_id": f"r{i}", "status": "ok"})


def events(name):
    import usage_events
    return [r["payload"] for r in usage_events._rows() if r["name"] == name]


def test_the_bundled_notes_have_an_entry_for_this_release():
    import pulse
    entry = pulse.whats_new_entry("1.0.0")
    assert entry and entry["version"] == "1.0.0" and 3 <= len(entry["items"]) <= 8
    assert pulse.whats_new_entry("1.0.0-beta.3")["version"] == "1.0.0"    # a prerelease shows its release's notes
    assert pulse.whats_new_entry("9.9.9") is None


def test_a_new_install_never_sees_whats_new(port):
    status, body = call(port, "GET", "/api/pulse")
    assert status == 200 and body["whats_new"] is None and body["csat_due"] is False
    import db
    assert db.get_setting("whats_new_seen") == "1.0.0"


def test_an_update_shows_whats_new_once_and_records_if_it_helped(port):
    import db
    processed(1)
    db.set_setting("whats_new_seen", "0.4.5")
    body = call(port, "GET", "/api/pulse")[1]
    assert body["whats_new"]["version"] == "1.0.0" and body["whats_new"]["items"]
    assert call(port, "POST", "/api/pulse/whats-new", {"version": "1.0.0", "helpful": "up"})[0] == 200
    assert call(port, "GET", "/api/pulse")[1]["whats_new"] is None
    assert events("whats_new") == [{"version": "1.0.0", "helpful": "up"}]


def test_someone_updating_from_before_this_feature_also_sees_it(port):
    processed(2)                                      # no whats_new_seen yet, but meetings exist
    assert call(port, "GET", "/api/pulse")[1]["whats_new"]["version"] == "1.0.0"


def test_csat_after_three_meetings_then_not_for_30_days(port):
    import db
    processed(2)
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is False
    processed(1)
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is True
    assert call(port, "POST", "/api/pulse/csat", {"score": 4, "comment": " faster notes please "})[0] == 200
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is False
    [answer] = events("csat")
    assert answer == {"score": 4, "comment": "faster notes please", "outcome": "answered", "trigger": "periodic",
                      "version": "1.0.0", "meetings": 3}
    db.set_setting("csat_last_asked", (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=31)).isoformat())
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is True


def test_csat_later_waits_and_never_stops_it(port):
    processed(3)
    call(port, "POST", "/api/pulse/csat", {"outcome": "later"})
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is False
    import db
    db.set_setting("csat_last_asked", "2000-01-01T00:00:00+00:00")
    call(port, "POST", "/api/pulse/csat", {"outcome": "never"})
    db.set_setting("csat_last_asked", "2000-01-01T00:00:00+00:00")
    assert call(port, "GET", "/api/pulse")[1]["csat_due"] is False
    assert [e["outcome"] for e in events("csat")] == ["later", "never"]
    assert all(e["score"] is None and e["comment"] == "" for e in events("csat"))


def test_bad_answers_are_refused(port):
    processed(3)
    for body in ({"score": 0}, {"score": 6}, {"score": "5"}, {"score": True}, {"outcome": "maybe"}):
        assert call(port, "POST", "/api/pulse/csat", body)[0] == 400
    assert events("csat") == []
