"""Microphone selector, Python side: GET /api/audio-devices lists input
devices by running the capture helper's `--list-devices` (faked here by a
shell script standing in for capture/dual-capture), and the `microphone`
setting round-trips through the settings routes."""
import http.client
import json
import threading
import time
from types import SimpleNamespace

import pytest

import capture_devices


def call_route(fn, arg):
    out = {}
    req = SimpleNamespace(send_json=lambda payload, status=200: out.update(payload=payload, status=status))
    fn(req, "", arg)
    return out["status"], out["payload"]


@pytest.fixture
def helper(tmp_path, monkeypatch):
    """A fake dual-capture binary; `helper.script(body)` sets what it does."""
    path = tmp_path / "dual-capture"

    def script(body):
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
    monkeypatch.setattr(capture_devices, "HELPER", path)
    return SimpleNamespace(path=path, script=script)


def list_route():
    from api.routes import settings
    return call_route(settings.get_api_audio_devices, {})


def test_route_returns_the_helpers_devices_in_snake_case_with_the_default_marked(helper):
    devices = [{"name": "Shure MV7", "uniqueID": "AppleUSBAudioEngine:Shure:MV7:1", "isDefault": True},
               {"name": "Logitech BRIO", "uniqueID": "AppleUSBAudioEngine:Logi:BRIO:2", "isDefault": False}]
    helper.script(f'[ "$1" = "--list-devices" ] || exit 9\necho \'{json.dumps(devices)}\'')
    assert list_route() == (200, {"devices": [
        {"name": "Shure MV7", "unique_id": "AppleUSBAudioEngine:Shure:MV7:1", "is_default": True},
        {"name": "Logitech BRIO", "unique_id": "AppleUSBAudioEngine:Logi:BRIO:2", "is_default": False}]})


@pytest.mark.parametrize("body", ["exit 1", "echo 'not json'", "echo '{\"name\": \"x\"}'", "echo '[{\"name\": \"x\"}]'"])
def test_a_failing_helper_yields_an_empty_list_not_an_error(helper, body):
    helper.script(body)
    assert list_route() == (200, {"devices": []})


def test_a_missing_helper_yields_an_empty_list(helper):
    assert not helper.path.exists()
    assert list_route() == (200, {"devices": []})


def test_a_hung_helper_is_abandoned_after_the_timeout(helper, monkeypatch):
    assert capture_devices.TIMEOUT_S == 5
    monkeypatch.setattr(capture_devices, "TIMEOUT_S", 0.3)
    helper.script("exec sleep 30")
    started = time.monotonic()
    assert list_route() == (200, {"devices": []})
    assert time.monotonic() - started < 5


# ---- over HTTP, as the web UI calls it ------------------------------------------

TOKEN = "audio-devices-test-token"


@pytest.fixture(scope="module")
def port():
    import server
    from api import auth
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": token}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_device_list_needs_the_api_token_but_not_lockdown_clearance(port, helper, monkeypatch):
    helper.script('echo \'[{"name": "MacBook Pro Microphone", "uniqueID": "BuiltInMicrophoneDevice", "isDefault": true}]\'')
    assert call(port, "GET", "/api/audio-devices", token="wrong")[0] == 401
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert call(port, "GET", "/api/audio-devices") == (200, {"devices": [
        {"name": "MacBook Pro Microphone", "unique_id": "BuiltInMicrophoneDevice", "is_default": True}]})


def test_microphone_setting_round_trips_and_clears_to_system_default(port):
    chosen = {"unique_id": "AppleUSBAudioEngine:Shure:MV7:1", "name": "Shure MV7"}
    assert call(port, "GET", "/api/settings?key=microphone") == (200, {"value": None})
    assert call(port, "POST", "/api/settings", {"key": "microphone", "value": chosen}) == (200, {"ok": True})
    assert call(port, "GET", "/api/settings?key=microphone") == (200, {"value": chosen})
    assert call(port, "POST", "/api/settings", {"key": "microphone"}) == (200, {"value": chosen})
    assert call(port, "POST", "/api/settings", {"key": "microphone", "value": None}) == (200, {"ok": True})
    assert call(port, "GET", "/api/settings?key=microphone") == (200, {"value": None})


def test_a_null_value_clears_only_the_microphone_and_reads_any_other_key(port):
    """`value: null` means "clear" only where null is a meaningful value (the
    Microphone: System default); for any other key it stays a read."""
    assert call(port, "POST", "/api/settings", {"key": "retain_audio", "value": False}) == (200, {"ok": True})
    assert call(port, "POST", "/api/settings", {"key": "retain_audio", "value": None}) == (200, {"value": False})
    assert call(port, "GET", "/api/settings?key=retain_audio") == (200, {"value": False})
    call(port, "POST", "/api/settings", {"key": "retain_audio", "value": True})


@pytest.mark.parametrize("bad", ["Shure MV7", {"unique_id": "x"}, {"unique_id": "", "name": "Shure"},
                                 {"unique_id": "x", "name": "y", "extra": 1}])
def test_a_malformed_microphone_value_is_rejected_and_the_choice_kept(port, bad):
    chosen = {"unique_id": "BuiltInMicrophoneDevice", "name": "MacBook Pro Microphone"}
    call(port, "POST", "/api/settings", {"key": "microphone", "value": chosen})
    status, payload = call(port, "POST", "/api/settings", {"key": "microphone", "value": bad})
    assert status == 400 and "microphone" in payload["error"]
    assert call(port, "GET", "/api/settings?key=microphone") == (200, {"value": chosen})
    call(port, "POST", "/api/settings", {"key": "microphone", "value": None})
