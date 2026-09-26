"""Structure checks for the API package: every endpoint registered once,
the server imports without the ML stack, and core routes answer."""
import http.client
import json
import sys
import threading

import pytest

import server
from api import auth, router

TOKEN = "routes-test-token"


def test_expected_endpoints_are_registered():
    routes = set(router.registered())
    for expected in [("GET", "/api/dashboard"), ("GET", "/api/recording"), ("POST", "/api/recording/transcript/edit"),
                     ("POST", "/api/process-recording"), ("GET", "/media/"), ("POST", "/api/credentials/save"),
                     ("GET", "/api/settings"), ("POST", "/api/settings")]:
        assert expected in routes, expected
    assert len(routes) >= 70


def test_duplicate_routes_are_rejected():
    with pytest.raises(ValueError):
        router.route("GET", "/api/health")(lambda req, path, query: None)


def test_server_import_does_not_load_mlx():
    import subprocess
    code = "import sys, server; print('mlx.core' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=server.paths.PYTHON_DIR, capture_output=True, text=True)
    assert out.stdout.strip() == "False", out.stderr


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, resp.read()


@pytest.mark.parametrize("path", ["/api/dashboard", "/api/folders", "/api/people", "/api/onboarding/status",
                                  "/api/memory/terms", "/api/recording/summary-formats", "/api/settings?key=x"])
def test_get_endpoints_respond(port, path):
    status, body = call(port, "GET", path)
    assert status == 200, body[:200]
    json.loads(body)


def test_unknown_post_is_404_and_bad_input_is_400(port):
    assert call(port, "POST", "/api/does-not-exist", {})[0] == 404
    assert call(port, "POST", "/api/recording/transcript/edit", {"id": "../../etc", "edits": [{"index": 0}]})[0] == 400


def test_settings_round_trip(port):
    assert call(port, "POST", "/api/settings", {"key": "unit_test_key", "value": 42})[0] == 200
    status, body = call(port, "GET", "/api/settings?key=unit_test_key")
    assert json.loads(body).get("value") == 42, body
    call(port, "POST", "/api/settings", {"key": "unit_test_zero", "value": 0})
    assert json.loads(call(port, "GET", "/api/settings?key=unit_test_zero")[1])["value"] == 0


def test_static_ui_is_served(port):
    status, body = call(port, "GET", "/")
    assert status == 200 and b"Content-Security-Policy" in body
