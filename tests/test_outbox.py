"""Outbox + Connection (T5, ADR 0002/0003) through the plugin host and the HTTP
API, with a test plugin that declares a Proposal kind and a Context source
without touching core modules, and a FakeConnection instead of the network."""
import datetime as dt
import http.client
import json
import re
import threading
from pathlib import Path

import pytest

import action_items
import connections
import db
import outbox
import paths
import plugin_host
import server
from api import auth
from notes_context import ContextBlock, FunctionSource
from outbox import Applied, Field, Proposal
from plugin_host import Plugin

TOKEN = "outbox-test-token"
SECRET_TEXT = "Send the Zanzibar pricing deck"


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


def recording(rec_id, items):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), f"Title {rec_id}", "2026-11-10T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": list(items)})
    action_items.sync(rec_id)


class FakeProposer:
    """Proposes one task.create per Action item; apply writes through the Connection."""
    automatic = True

    def __init__(self):
        self.proposed = 0

    def propose(self, ctx):
        self.proposed += 1
        return [Proposal(key=f"t:create:{i['id']}", kind="task.create", title=f"Create '{i['text']}'",
                         fields=(Field("title", "Title", i["text"]), Field("area", "Area", "", editable=False)),
                         payload={"title": i["text"]}, action_item_ids=(i["id"],),
                         sends=f"Title '{i['text']}' to Test DB") for i in ctx.action_items]

    def apply(self, proposal, edits, conn):
        title = edits.get("title", proposal.payload["title"])
        body = conn.request("POST", "/pages", json={"title": title})
        return Applied("notion", body.get("id", "page-1"), "https://example.invalid/page-1", "task")


@pytest.fixture
def plugin(fake_conn):
    fake = fake_conn("notion")
    fake.on("POST", "/pages", {"id": "page-1"})
    proposer = FakeProposer()
    p = Plugin(id="outbox-test", name="Outbox test", enabled_by_default=True, connection="notion",
               proposer=proposer, context_sources=(FunctionSource("outbox-test.src", lambda req: [
                   ContextBlock("outbox-test.src", "x", 0.5, frozenset({"*"}))]),))
    plugin_host.register(p)
    yield fake, proposer
    plugin_host.unregister("outbox-test")


def keys(port, recording_id):
    return [p["key"] for p in call(port, "GET", f"/api/outbox?recording={recording_id}")[1]["proposals"]]


def test_no_write_without_confirm_then_confirm_writes_once_links_and_audits_a_hash(port, plugin):
    fake, _ = plugin
    recording("ob-1", [SECRET_TEXT, "Book the room"])
    outbox.refresh("ob-1")
    status, body = call(port, "GET", "/api/outbox?recording=ob-1")
    assert status == 200 and body["count"] == 2
    assert fake.requests == []                                     # proposing sends nothing
    first = body["proposals"][0]
    assert first["sends"] == f"Title '{SECRET_TEXT}' to Test DB"   # the 🔒 line

    status, body = call(port, "POST", "/api/outbox/confirm", {"key": first["key"], "edits": {"title": "Edited"}})
    assert status == 200 and body["proposal"]["state"] == "confirmed"
    assert [r["json"] for r in fake.requests] == [{"title": "Edited"}]   # only the confirmed payload

    links = call(port, "GET", "/api/links?recording=ob-1")[1]["links"]
    assert [(lk["action_item_id"], lk["external_id"], lk["service"]) for lk in links] == \
        [(first["action_item_ids"][0], "page-1", "notion")]

    rows = [r for r in outbox.audit_rows() if r["plugin_id"] == "outbox-test"]
    assert [r["outcome"] for r in rows] == ["confirmed"]
    assert re.fullmatch(r"[0-9a-f]{64}", rows[0]["payload_sha256"])
    flat = json.dumps(rows)
    assert SECRET_TEXT not in flat and "Edited" not in flat and first["key"] not in flat

    assert call(port, "POST", "/api/outbox/confirm", {"key": first["key"]})[0] == 409   # once only
    assert call(port, "POST", "/api/outbox/confirm", {"key": body["proposal"]["key"],
                                                      "edits": {"area": "x"}})[0] in (400, 409)


def test_uneditable_field_edit_is_refused(port, plugin):
    recording("ob-edit", ["Draft the plan"])
    outbox.refresh("ob-edit")
    key = keys(port, "ob-edit")[0]
    assert call(port, "POST", "/api/outbox/confirm", {"key": key, "edits": {"area": "x"}}) == \
        (400, {"error": "field_not_editable:area"})


def test_reprocessing_never_duplicates_and_decided_keys_stay_decided(port, plugin):
    recording("ob-dedupe", ["Send the deck", "Book the room", "Draft the plan"])
    outbox.refresh("ob-dedupe")
    a, b, c = keys(port, "ob-dedupe")
    call(port, "POST", "/api/outbox/confirm", {"key": a})
    call(port, "POST", "/api/outbox/dismiss", {"key": b})
    for _ in range(2):   # reprocess twice
        outbox.refresh("ob-dedupe")
    assert keys(port, "ob-dedupe") == [c]
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM outbox WHERE recording_id = 'ob-dedupe'").fetchone()[0] == 3
    assert [r["outcome"] for r in outbox.audit_rows() if r["plugin_id"] == "outbox-test"][-2:] == \
        ["confirmed", "dismissed"]


def test_stale_and_14_day_old_proposals_retire(port, plugin):
    recording("ob-retire", ["Send the deck", "Book the room"])
    outbox.refresh("ob-retire")
    deck, room = keys(port, "ob-retire")
    recording("ob-retire", ["Book the room"])          # the deck item disappeared
    outbox.refresh("ob-retire")
    assert keys(port, "ob-retire") == [room]
    assert outbox.get(deck)["state"] == "retired" and outbox.get(deck)["retired_reason"] == "invalid"

    old = (dt.datetime.now().astimezone() - dt.timedelta(days=15)).isoformat()
    with db.get_db() as conn:
        conn.execute("UPDATE outbox SET created_at = ? WHERE key = ?", (old, room))
        conn.commit()
    assert room not in [p["key"] for p in call(port, "GET", "/api/outbox")[1]["proposals"]]   # cross-meeting list
    outbox.refresh("ob-retire")
    assert outbox.get(room)["retired_reason"] == "expired"           # not revived by reprocessing


def test_lockdown_refuses_confirm_and_audits_blocked(port, plugin, monkeypatch):
    fake, _ = plugin
    recording("ob-lock", ["Send the deck"])
    outbox.refresh("ob-lock")
    key = keys(port, "ob-lock")[0]
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert call(port, "POST", "/api/outbox/confirm", {"key": key}) == (403, {"error": "blocked_policy"})
    assert fake.requests == []
    assert outbox.get(key)["state"] == "pending"
    assert [r["outcome"] for r in outbox.audit_rows() if r["plugin_id"] == "outbox-test"][-1] == "blocked"
    assert call(port, "POST", "/api/connections/connect", {"service": "slack", "token": "not-a-real-token"})[0] == 403


def test_failed_apply_is_kept_retryable_and_audited(port, plugin):
    fake, _ = plugin
    recording("ob-fail", ["Send the deck"])
    outbox.refresh("ob-fail")
    key = keys(port, "ob-fail")[0]
    fake.fail[("POST", "/pages")] = connections.ConnectionFailed("transient", 503)
    assert call(port, "POST", "/api/outbox/confirm", {"key": key}) == (502, {"error": "failed:transient"})
    assert outbox.get(key)["state"] == "failed" and key in keys(port, "ob-fail")
    assert call(port, "POST", "/api/outbox/confirm", {"key": key})[0] == 200


def test_disabled_plugin_has_no_effect(port, plugin):
    fake, proposer = plugin
    recording("ob-off", ["Send the deck"])
    outbox.refresh("ob-off")
    key = keys(port, "ob-off")[0]
    paths.CONFIG_PATH.write_text(json.dumps({"plugins": {"outbox-test": {"enabled": False}}}))
    try:
        before = proposer.proposed
        outbox.refresh("ob-off")
        assert proposer.proposed == before
        assert keys(port, "ob-off") == []
        assert call(port, "POST", "/api/outbox/confirm", {"key": key})[0] == 404
        assert fake.requests == []
    finally:
        paths.CONFIG_PATH.write_text("{}")


def test_a_raising_proposer_is_isolated(port, plugin):
    class Boom:
        automatic = True

        def propose(self, ctx):
            raise RuntimeError(SECRET_TEXT)
    plugin_host.register(Plugin(id="outbox-boom", name="Boom", enabled_by_default=True, proposer=Boom()))
    try:
        recording("ob-boom", ["Send the deck"])
        result = outbox.refresh("ob-boom")
        assert (result["outbox-test"], result["outbox-boom"]) == (1, -1)
        assert len(keys(port, "ob-boom")) == 1
    finally:
        plugin_host.unregister("outbox-boom")


def test_not_connected_plugin_proposes_nothing(port, plugin):
    _, proposer = plugin
    connections.use("notion", None)
    recording("ob-nc", ["Send the deck"])
    before = proposer.proposed
    outbox.refresh("ob-nc")
    assert proposer.proposed == before and keys(port, "ob-nc") == []


def test_confirm_needs_a_user_click_and_only_the_route_makes_one(plugin):
    recording("ob-click", ["Send the deck"])
    outbox.refresh("ob-click")
    key = outbox.pending("ob-click")[0]["key"]
    with pytest.raises(outbox.OutboxError):
        outbox.confirm(key, {}, click=None)
    root = Path(__file__).resolve().parents[1]
    makers = sorted(str(p.relative_to(root)) for d in ("python", "plugins") for p in (root / d).rglob("*.py")
                    if "UserClick(" in p.read_text() or "outbox.confirm(" in p.read_text())
    assert makers == ["python/api/routes/outbox.py"]


# ---- Connection --------------------------------------------------------------

def test_connect_keeps_the_token_in_the_keychain_only(port, keychain, monkeypatch):
    sent = []

    def send(self, method, url, headers, data):
        sent.append((method, url, headers.get("Authorization")))
        return 200, {}, {"ok": True, "team": "Acme", "user": "me"}
    monkeypatch.setattr(connections.Connection, "_send", send)
    status, body = call(port, "POST", "/api/connections/connect", {"service": "slack", "token": "not-a-real-token"})
    assert status == 200 and body["connection"]["account_label"] == "Acme · me"
    assert keychain == {"connection.slack": "not-a-real-token"}
    assert sent == [("POST", "https://slack.com/api/auth.test", "Bearer not-a-real-token")]
    for path in (paths.CONFIG_PATH, paths.DB_PATH, paths.LOGS_DIR / "connections.jsonl"):
        assert b"not-a-real-token" not in path.read_bytes()
    assert call(port, "GET", "/api/connections")[1]["connections"]["slack"]["connected"] is True
    call(port, "POST", "/api/connections/disconnect", {"service": "slack"})
    assert keychain == {} and not connections.status()["slack"]["connected"]


def test_connection_retries_rate_limits_and_logs_no_bodies(keychain, monkeypatch):
    answers = [(429, {"Retry-After": "0"}, {}), (503, {}, {}), (200, {}, {"id": "p"})]
    waits = []
    monkeypatch.setattr(connections.Connection, "_send", lambda self, *a: answers.pop(0))
    monkeypatch.setattr(connections.Connection, "sleep", staticmethod(waits.append))
    conn = connections.Connection(connections.ADAPTERS["notion"], "tok")
    assert conn.request("POST", "/pages/1f2e3d4c5b6a79881f2e3d4c5b6a7988/comments", json={"t": SECRET_TEXT}) == {"id": "p"}
    assert waits == [0.0, 1.0]
    log = (paths.LOGS_DIR / "connections.jsonl").read_text()
    assert SECRET_TEXT not in log and "1f2e3d4c" not in log and "/pages/{id}/comments" in log

    monkeypatch.setattr(connections.Connection, "_send", lambda self, *a: (401, {}, {"code": "unauthorized"}))
    with pytest.raises(connections.ConnectionFailed) as err:
        conn.request("GET", "/users/me")
    assert err.value.kind == "auth" and not err.value.retryable

    monkeypatch.setattr(connections.Connection, "_send", lambda self, *a: (200, {}, {"ok": False, "error": "ratelimited"}))
    with pytest.raises(connections.ConnectionFailed) as err:
        connections.Connection(connections.ADAPTERS["slack"], "tok").request("POST", "/chat.postMessage")
    assert err.value.kind == "rate"


def test_connection_refuses_under_lockdown(keychain, monkeypatch):
    keychain["connection.notion"] = "tok"
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    with pytest.raises(connections.BlockedByPolicy):
        connections.get("notion")
    with pytest.raises(connections.BlockedByPolicy):
        connections.Connection(connections.ADAPTERS["notion"], "tok").request("GET", "/users/me")


def test_a_dismissed_proposal_can_be_brought_back_and_then_confirmed(port, plugin):
    recording("ob-restore", ["Send the deck"])
    outbox.refresh("ob-restore")
    [key] = keys(port, "ob-restore")
    call(port, "POST", "/api/outbox/dismiss", {"key": key})
    assert keys(port, "ob-restore") == []
    status, body = call(port, "GET", "/api/outbox/dismissed")
    assert status == 200 and key in [p["key"] for p in body["proposals"]]
    status, body = call(port, "POST", "/api/outbox/restore", {"key": key})
    assert status == 200 and body["proposal"]["state"] == "pending"
    assert keys(port, "ob-restore") == [key]
    assert key not in [p["key"] for p in call(port, "GET", "/api/outbox/dismissed")[1]["proposals"]]
    assert call(port, "POST", "/api/outbox/restore", {"key": key})[0] == 409      # only a dismissed one
    call(port, "POST", "/api/outbox/confirm", {"key": key})
    assert outbox.get(key)["state"] == "confirmed"
