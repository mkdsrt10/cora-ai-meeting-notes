"""The local API must reject cross-site, rebinding, and unauthenticated calls."""
import http.client
import json
import threading

import pytest

import server
from api import auth

TOKEN = "test-token"


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers={"Host": f"127.0.0.1:{port}", **(headers or {})})
    resp = conn.getresponse()
    resp.read()
    return resp


def test_health_is_public(port):
    assert request(port, "GET", "/api/health").status == 200


def test_api_requires_token(port):
    assert request(port, "GET", "/api/auth/check").status == 401
    assert request(port, "GET", "/api/auth/check", {"X-VC-Token": "wrong"}).status == 401
    assert request(port, "GET", "/api/auth/check", {"X-VC-Token": TOKEN}).status == 200
    assert request(port, "GET", "/api/auth/check", {"Cookie": f"a=b; vc_token={TOKEN}"}).status == 200


def test_media_requires_token(port):
    assert request(port, "GET", "/media/x/audio.m4a").status == 401


def test_dns_rebinding_host_rejected(port):
    assert request(port, "GET", "/api/auth/check", {"Host": f"evil.example:{port}", "X-VC-Token": TOKEN}).status == 403


def test_foreign_origin_rejected(port):
    headers = {"Origin": "https://evil.example", "Cookie": f"vc_token={TOKEN}"}
    assert request(port, "GET", "/api/auth/check", headers).status == 403


def test_post_requires_json_content_type(port):
    body = json.dumps({"key": "x", "value": 1})
    headers = {"X-VC-Token": TOKEN, "Content-Type": "text/plain"}
    assert request(port, "POST", "/api/settings", headers, body).status == 400


def test_no_wildcard_cors(port):
    resp = request(port, "GET", "/api/auth/check", {"X-VC-Token": TOKEN})
    assert resp.getheader("Access-Control-Allow-Origin") is None
    assert resp.getheader("X-Frame-Options") == "DENY"
