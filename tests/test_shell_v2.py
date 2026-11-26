"""UI shell v2 is a second page on the same server (docs/specs/ui-shell-v2.md,
T1): /v2/ serves it beside the classic page, and the ui_shell / ui_theme
settings that pick the page and its theme are validated and default to the
classic look."""
import http.client
import json
import threading

import pytest

import server
from api import auth

TOKEN = "shell-v2-test-token"


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, resp.read()


def test_both_pages_are_served(port):
    status, classic = call(port, "GET", "/")
    assert status == 200 and b'id="settingsTryNewLook"' in classic
    for path in ("/v2/", "/v2"):
        status, v2 = call(port, "GET", path)
        assert status == 200, path
        assert b'data-shell="v2"' in v2
    status, css = call(port, "GET", "/v2/shell.css")
    assert status == 200 and b"--accent" in css


def test_shell_and_theme_settings_default_and_validate(port):
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key IN ('ui_shell', 'ui_theme')")
        conn.commit()
    for key, default in (("ui_shell", "v2"), ("ui_theme", "system")):     # the new look by default since 1.0.1
        status, body = call(port, "GET", f"/api/settings?key={key}")
        assert json.loads(body)["value"] == default
    assert call(port, "POST", "/api/settings", {"key": "ui_shell", "value": "classic"})[0] == 200
    assert json.loads(call(port, "GET", "/api/settings?key=ui_shell")[1])["value"] == "classic"   # a choice is kept
    assert call(port, "POST", "/api/settings", {"key": "ui_shell", "value": "v2"})[0] == 200
    assert call(port, "POST", "/api/settings", {"key": "ui_shell", "value": "fancy"})[0] == 400
    assert call(port, "POST", "/api/settings", {"key": "ui_theme", "value": "dark"})[0] == 200
    assert call(port, "POST", "/api/settings", {"key": "ui_theme", "value": "purple"})[0] == 400
    call(port, "POST", "/api/settings", {"key": "ui_shell", "value": "classic"})


def test_v2_page_loads_no_plugin_code():
    """ADR 0005: no plugin JavaScript runs in the v2 window."""
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "src/ui/web/v2/index.html").read_text()
    assert "/plugins/" not in html
