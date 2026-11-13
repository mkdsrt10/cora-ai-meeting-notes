"""In beta (team) builds the Install's display name defaults, once, to the
user's own name: when onboarding saves it, or on the first start after an
upgrade for someone who onboarded earlier. What is sent is always what
Settings > Beta shows, so clearing it there stops it for good. Driven over
HTTP the way the renderer calls it, plus usage_events.seed_display_name()
as server startup calls it."""
import http.client
import json
import threading

import pytest

TOKEN = "display-name-default-token"
KEYS = ("beta_display_name", "beta_display_name_seeded", "pending_self_name", "onboarding_complete")


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
        conn.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(KEYS))})", KEYS)
        conn.execute("UPDATE people SET is_self = 0")
        conn.commit()
    for var in ("CORA_BUILD_VARIANT", "VOICECOACH_ENTERPRISE_LOCKDOWN"):
        monkeypatch.delenv(var, raising=False)


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def display_name(port):
    status, payload = call(port, "GET", "/api/settings?key=beta_display_name")
    assert status == 200
    return payload["value"]


def onboard(port, name):
    assert call(port, "POST", "/api/onboarding/name", {"name": name}) == (200, {"ok": True})


def test_beta_build_onboarding_name_becomes_the_display_name(port, monkeypatch):
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    onboard(port, "  Aarish Ali ")
    assert display_name(port) == "Aarish Ali"


def test_public_build_never_copies_the_name(port):
    onboard(port, "Aarish Ali")
    assert display_name(port) is None


def test_a_name_already_typed_in_settings_is_kept(port, monkeypatch):
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": "Aarish"})
    onboard(port, "Aarish Ali")
    assert display_name(port) == "Aarish"


def test_clearing_the_name_in_settings_stays_cleared(port, monkeypatch):
    import usage_events
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    onboard(port, "Aarish Ali")
    call(port, "POST", "/api/settings", {"key": "beta_display_name", "value": None})
    onboard(port, "Aarish Ali")       # onboarding again
    usage_events.seed_display_name()  # and a restart
    assert display_name(port) is None


def test_upgrade_copies_the_current_own_name_once_for_someone_already_onboarded(port, monkeypatch):
    import db
    import usage_events
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    db.set_setting("pending_self_name", "Neeraj Yadav")  # onboarded on 0.4.3: nothing seeded yet
    usage_events.seed_display_name()
    assert display_name(port) == "Neeraj Yadav"
    db.set_setting("pending_self_name", "Neeraj Y")
    usage_events.seed_display_name()
    assert display_name(port) == "Neeraj Yadav", "seeded once; later renames are the user's to copy"


def test_start_before_onboarding_waits_for_the_name(port, monkeypatch):
    import usage_events
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    usage_events.seed_display_name()  # first launch: no name yet
    assert display_name(port) is None
    onboard(port, "Chandan Gowda")
    assert display_name(port) == "Chandan Gowda"


def test_lockdown_copies_nothing(port, monkeypatch):
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    onboard(port, "Aarish Ali")
    assert display_name(port) is None


def test_a_long_name_is_cut_to_the_settings_limit(port, monkeypatch):
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    onboard(port, "A" * 150)
    assert display_name(port) == "A" * 100
