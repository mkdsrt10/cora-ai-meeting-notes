"""Structure checks for the API package: core endpoints registered once,
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
                     ("GET", "/api/settings"), ("POST", "/api/settings"),
                     ("GET", "/api/notifications"), ("POST", "/api/notifications/log"),
                     ("GET", "/api/logs"), ("GET", "/api/logs/file"), ("POST", "/api/logs/bundle"),
                     ("POST", "/api/recording/continuation-status"), ("GET", "/api/recording/live-audio")]:
        assert expected in routes, expected


def test_plugin_namespace_is_owned_by_the_plugin_host():
    """Plugins add routes under /api/plugins/<id>/ through plugin_host, never
    as core router entries, so adding a plugin never changes this table."""
    under = {r for r in router.registered() if r[1].startswith("/api/plugins")}
    assert under == {("GET", "/api/plugins"), ("GET", "/api/plugins/"), ("POST", "/api/plugins/")}


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


def test_processing_profile_roundtrip(port):
    import db
    previous = db.get_setting('processing_preferences')
    try:
        status, body = call(port, 'GET', '/api/processing')
        assert status == 200
        payload = json.loads(body)
        assert payload['templates'] and 'recommended_mode' in payload['hardware']
        assert call(port, 'POST', '/api/processing', {'mode':'local_thorough','template':'auto'})[0] == 200
        saved = json.loads(call(port, 'GET', '/api/processing')[1])['preferences']
        assert saved['mode'] == 'local_thorough' and saved['transcription'] == 'local'
        assert call(port, 'POST', '/api/processing', {'mode':'unknown'})[0] == 400
    finally:
        db.set_setting('processing_preferences', previous)


def test_processing_history_endpoint_is_scoped(port):
    import ai_trace
    import paths
    folder = paths.RECORDINGS_DIR / 'history-endpoint'
    folder.mkdir(parents=True, exist_ok=True)
    with ai_trace.run('api-history', recording_id=folder.name):
        with ai_trace.span('llm', 'notes.test', provider='mlx', model='test-model') as span:
            span.set(input_tokens=5, output_tokens=2)
    status, body = call(port, 'GET', '/api/recording/processing?id=history-endpoint')
    assert status == 200
    data = json.loads(body)
    assert any(item['model'] == 'test-model' for item in data['calls'])
    assert call(port, 'GET', '/api/recording/processing?id=..%2F..%2Fetc')[0] in (400, 404)


def test_people_can_be_created_without_overwriting_namesakes(port):
    first_status, first_body = call(port, 'POST', '/api/people/create', {'name':'Namesake Person','role':'Engineer','organization':'Example'})
    assert first_status == 201
    first = json.loads(first_body)['person']
    status, body = call(port, 'POST', '/api/people/create', {'name':'Namesake Person','role':'Designer'})
    second = json.loads(body)['person']
    assert status == 201 and first['id'] != second['id']
    stored = json.loads(call(port, 'GET', '/api/person?id='+first['id'])[1])['person']
    assert stored['role'] == 'Engineer' and stored['organization'] == 'Example'
    assert call(port,'POST','/api/people/create',{'name':None})[0] == 400
