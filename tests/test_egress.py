"""Egress gate (spec §13.5): local processing with Notion and Slack connected
makes no outbound connection; the only external write happens on a Confirm
click, and it carries the confirmed payload only. Uses the real Connection
class with its transport recorded, and a socket guard for everything else."""
import http.client
import json
import socket
import threading

import pytest

import action_items
import connections
import db
import notes_context
import outbox
import paths
import post_processing
import server
from api import auth
from pipeline.processing_notes import generate_notes

TOKEN = "egress-test-token"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


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
    data = resp.read()
    return resp.status, (json.loads(data) if data else {})


@pytest.fixture
def wire(monkeypatch, keychain):
    """Record every Connection request and every non-loopback socket connect."""
    sent, sockets = [], []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in LOOPBACK:
            sockets.append(host)
            raise OSError("outbound blocked in test")
        return real_connect(self, address)
    monkeypatch.setattr(socket.socket, "connect", guarded)

    def send(self, method, url, headers, data):
        sent.append({"service": self.service, "method": method, "url": url,
                     "body": json.loads(data) if data else None})
        if url.endswith("/auth.test"):
            return 200, {}, {"ok": True, "team": "T", "user": "u", "user_id": "U0ME"}
        if url.endswith("/pages"):
            return 200, {}, {"id": "new-page", "url": "https://www.notion.so/new-page"}
        return 200, {}, {"ok": True, "results": [], "has_more": False, "bot": {}}
    monkeypatch.setattr(connections.Connection, "_send", send)
    for service in ("notion", "slack"):
        connections.connect(service, f"test-{service}-value")
    db.set_setting("plugin_settings.notion", {"database_id": "db1", "database_title": "Tasks", "mapping": {
        "title": "Name", "status": "Status", "done_value": "Done"}})
    from plugins.notion import tasks
    tasks.upsert({"id": "t-1", "title": "Ship the pricing page", "url": "https://www.notion.so/t-1"})
    sent.clear()
    yield sent, sockets
    db.set_setting("plugin_settings.notion", {})
    for service in ("notion", "slack"):
        connections.disconnect(service)


def test_local_processing_makes_no_outbound_call_and_confirm_makes_one(port, wire, fake_text):
    sent, sockets = wire
    fake_text.reply = lambda prompt, **kw: (json.dumps([{"action_item_id": i, "decision": "create", "confidence": 0.9}
                                                        for i in __import__("re").findall(r'<item id="([^"]+)">', prompt)])
                                            if "Answer with JSON only" in prompt else "- Ship the pricing page copy")
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "egress-1"
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording("egress-1"):
        db.create_recording("egress-1", str(folder), "Pricing sync", "2026-11-14T09:00:00+00:00", 60, 1, {})
    saved = db.get_setting(notes_context.SETTING)
    db.set_setting(notes_context.SETTING, True)
    try:
        generate_notes("[00:00 - 00:05] Ana: I'll ship the pricing page copy.", [],
                       [{"speaker_name": "Ana", "start": "00:00", "end": "00:05", "text": "I'll ship it."}],
                       options={"provider": "local_mlx", "model": "", "template": "general", "mode": "local_light"},
                       folder=folder)
    finally:
        db.set_setting(notes_context.SETTING, saved)
    db.update_recording_data("egress-1", "call_summary", {"action_items": ["Write the pricing FAQ"],
                                                          "processing": {"provider": "local_mlx", "model": ""}})
    post_processing.finish("egress-1")
    pending = outbox.pending("egress-1")
    assert pending and sent == [] and sockets == []          # processed and proposed, nothing left the Mac

    assert call(port, "POST", "/api/outbox/confirm", {"key": pending[0]["key"]})[0] == 200
    assert [(r["service"], r["method"], r["url"]) for r in sent] == [("notion", "POST", "https://api.notion.com/v1/pages")]
    assert "Write the pricing FAQ" in json.dumps(sent[0]["body"]) and sockets == []
    assert action_items.for_recording("egress-1")[0]["id"] in pending[0]["action_item_ids"]
