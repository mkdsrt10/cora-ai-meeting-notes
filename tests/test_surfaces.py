"""Surface contract over HTTP (ADR 0005; spec seam 1): which contributions a
context gets, filtered for disabled plugins, lockdown and Recordings
excluded from plugins; one chip per Action item; the action endpoint runs
only the named plugin's handler. Test plugins are registered through the
plugin host without touching core modules; Notion and Slack run against a
FakeConnection. Made-up meetings only."""
import http.client
import json
import threading

import pytest

import action_items
import db
import outbox
import paths
import plugin_host
import server
import surfaces
from api import auth
from outbox import Field, Proposal
from plugin_host import Plugin
from surfaces import Action, Contribution

TOKEN = "surfaces-test-token"


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
        db.create_recording(rec_id, str(folder), f"Planning sync {rec_id}", "2026-11-10T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": list(items)})
    action_items.sync(rec_id)
    return [i["id"] for i in action_items.for_recording(rec_id)]


def config(plugins=None):
    paths.CONFIG_PATH.write_text(json.dumps({"plugins": plugins or {}}))


def only(port, context, plugin_id, target=None):
    q = f"/api/surfaces?context={context}" + (f"&id={target}" if target else "")
    status, body = call(port, "GET", q)
    assert status == 200, body
    return [c for c in body["contributions"] if c["plugin_id"] == plugin_id]


calls = []


def surf_a(ctx):
    if ctx.context == "app":
        return [Contribution("app.nav", "action", "Alpha", id="alpha", icon="check"),
                Contribution("app.page", "panel", "Alpha", id="alpha", panel={"title": "Alpha", "blocks": [{"type": "text", "text": "hi"}]}),
                Contribution("recording.tab", "panel", "Wrong place"),             # not an app surface: dropped
                Contribution("app.made_up", "annotation", "Not in the catalog")]  # dropped
    if ctx.context == "recording":
        out = []
        for item in ctx.action_items:
            out.append(Contribution("action_item.chip", "annotation", "Alpha other", target=item["id"]))
            out.append(Contribution("action_item.chip", "annotation", "Alpha link", target=item["id"], state="link", url="https://example.invalid/a"))
        out.append(Contribution("recording.tab", "panel", "Alpha tab", panel={"title": "Alpha", "blocks": [{"type": "kv", "rows": [["a", "b"]]}]}))
        out.append(Contribution("recording.property", "annotation", "Alpha", detail="ok"))
        out.append(Contribution("selection.action", "action", "Do alpha", action=Action("go", "selection")))
        return out
    if ctx.context == "person":
        return [Contribution("person.accounts", "annotation", "Alpha", target=ctx.id, state="confirmed", detail="A. Person")]
    if ctx.context == "folder":
        return [Contribution("folder.defaults", "annotation", "Alpha default", target=ctx.id)]
    return []


def surf_b(ctx):
    if ctx.context == "recording":
        return [Contribution("action_item.chip", "annotation", "Beta pending", target=i["id"], state="pending", proposal_key=f"b:{i['id']}")
                for i in ctx.action_items[:1]]
    return []


def boom(ctx):
    raise RuntimeError("Planning sync secret text")


def handler(name):
    def run(ctx):
        calls.append((name, ctx.action_id, ctx.context, ctx.id, list(ctx.action_item_ids), dict(ctx.values)))
        return {"toast": f"{name} ran"}
    return run


@pytest.fixture
def plugins():
    calls.clear()
    config({"notion": {"enabled": False}, "slack": {"enabled": False}, "todo": {"enabled": False}})
    regs = [Plugin(id="surf-a", name="A", enabled_by_default=True, surfaces=surf_a, actions={"go": handler("a")}),
            Plugin(id="surf-b", name="B", enabled_by_default=True, surfaces=surf_b, actions={"go": handler("b")}),
            Plugin(id="surf-boom", name="Boom", enabled_by_default=True, surfaces=boom)]
    for p in regs:
        plugin_host.register(p)
    yield
    for p in regs:
        plugin_host.unregister(p.id)
    config()


def test_contributions_per_context(port, plugins):
    app = only(port, "app", "surf-a")
    assert [(c["surface"], c["kind"], c["label"]) for c in app] == [("app.nav", "action", "Alpha"), ("app.page", "panel", "Alpha")]
    ids = recording("sf-1", ["Send the pricing draft", "Book the room"])
    rec = only(port, "recording", "surf-a", "sf-1")
    assert {c["surface"] for c in rec} == {"action_item.chip", "recording.tab", "recording.property", "selection.action"}
    assert next(c for c in rec if c["surface"] == "selection.action")["action"] == {"id": "go", "applies_to": "selection"}
    assert only(port, "person", "surf-a", "p-1")[0]["detail"] == "A. Person"
    assert only(port, "folder", "surf-a", "f-1")[0]["label"] == "Alpha default"
    assert ids and call(port, "GET", "/api/surfaces?context=nowhere")[0] == 400
    assert call(port, "GET", "/api/surfaces?context=recording")[0] == 400          # id required
    assert call(port, "GET", "/api/surfaces?context=recording&id=missing")[0] == 404


def test_raising_plugin_costs_only_itself_and_logs_no_content(port, plugins, capfd):
    recording("sf-boom", ["Send the pricing draft"])
    status, body = call(port, "GET", "/api/surfaces?context=recording&id=sf-boom")
    assert status == 200 and {c["plugin_id"] for c in body["contributions"]} == {"surf-a", "surf-b"}
    out = capfd.readouterr().out
    assert "surf-boom: surfaces failed (RuntimeError)" in out and "secret" not in out


def test_one_chip_per_action_item_pending_then_link_then_plugin_order(port, plugins):
    first, second = recording("sf-chips", ["Send the pricing draft", "Book the room"])
    status, body = call(port, "GET", "/api/surfaces?context=recording&id=sf-chips")
    chips = [c for c in body["contributions"] if c["surface"] == "action_item.chip"]
    one = [(c["label"], c["shown"], c.get("more")) for c in chips if c["target"] == first]
    assert one == [("Beta pending", True, 2), ("Alpha link", False, None), ("Alpha other", False, None)]
    two = [(c["label"], c["shown"], c.get("more")) for c in chips if c["target"] == second]
    assert two == [("Alpha link", True, 1), ("Alpha other", False, None)]


def test_empty_when_plugin_off_under_lockdown_and_for_excluded_recordings(port, plugins, monkeypatch):
    recording("sf-off", ["Send the pricing draft"])
    config({"surf-a": {"enabled": False}, "notion": {"enabled": False}, "slack": {"enabled": False}, "todo": {"enabled": False}})
    assert only(port, "app", "surf-a") == [] and only(port, "recording", "surf-a", "sf-off") == []
    assert only(port, "recording", "surf-b", "sf-off")                               # the other plugin still shows
    config({"notion": {"enabled": False}, "slack": {"enabled": False}, "todo": {"enabled": False}})

    assert call(port, "POST", "/api/recording/plugins-excluded", {"id": "sf-off", "excluded": True})[0] == 200
    assert call(port, "GET", "/api/surfaces?context=recording&id=sf-off")[1]["contributions"] == []
    assert only(port, "app", "surf-a")                                               # app surfaces unaffected
    call(port, "POST", "/api/recording/plugins-excluded", {"id": "sf-off", "excluded": False})
    assert only(port, "recording", "surf-a", "sf-off")

    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    for ctx, target in (("app", None), ("recording", "sf-off"), ("person", "p-1"), ("folder", "f-1")):
        q = f"/api/surfaces?context={ctx}" + (f"&id={target}" if target else "")
        assert call(port, "GET", q)[1]["contributions"] == [], ctx


def test_action_endpoint_runs_only_the_named_plugin(port, plugins, monkeypatch):
    ids = recording("sf-act", ["Send the pricing draft", "Book the room"])
    status, body = call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-b", "action_id": "go", "context": "recording",
                                                               "id": "sf-act", "action_item_ids": ids, "values": {"x": "1"}})
    assert status == 200 and body["toast"] == "b ran"
    assert calls == [("b", "go", "recording", "sf-act", ids, {"x": "1"})]
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "nope"}) == (404, {"error": "unknown_action"})
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "nobody", "action_id": "go"})[0] == 404
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "go", "action_item_ids": ["ai_missing"]})[0] == 404
    config({"surf-a": {"enabled": False}, "notion": {"enabled": False}, "slack": {"enabled": False}, "todo": {"enabled": False}})
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "go"})[0] == 404
    config({"notion": {"enabled": False}, "slack": {"enabled": False}, "todo": {"enabled": False}})
    surfaces.set_excluded("sf-act", True)
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "go", "context": "recording",
                                                       "id": "sf-act"}) == (409, {"error": "excluded"})
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "go", "action_item_ids": ids[:1]})[0] == 409
    surfaces.set_excluded("sf-act", False)
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert call(port, "POST", "/api/surfaces/action", {"plugin_id": "surf-a", "action_id": "go"}) == (403, {"error": "blocked_policy"})
    assert [c[0] for c in calls] == ["b"]


def test_no_contribution_can_carry_a_shortcut():
    """ADR 0005: Cora owns every key; the contract has no field for one."""
    fields = set(Contribution.__dataclass_fields__) | set(Action.__dataclass_fields__)
    assert not fields & {"key", "keys", "shortcut", "accelerator", "hotkey"}


# ---- Notion and Slack declare their current UI as contributions ----------------

@pytest.fixture
def bundled(fake_conn):
    config({"todo": {"enabled": False}, "coaching": {"enabled": False}})
    notion, slack = fake_conn("notion"), fake_conn("slack")
    yield notion, slack
    for plugin_id in ("notion", "slack"):
        db.set_setting(f"plugin_settings.{plugin_id}", {})
    with db.get_db() as conn:
        conn.execute("DELETE FROM outbox WHERE recording_id LIKE 'sf-%'")
        conn.commit()
    config()


def test_notion_and_slack_chips_footer_and_selection_action(port, bundled):
    notion, slack = bundled
    first, second = recording("sf-ns", ["Send the pricing draft", "Book the room"])
    outbox.submit("notion", "sf-ns", [Proposal(key="n:link:1", kind="task.link", title="Link to Pricing v2",
                                               action_item_ids=(first,), target={"id": "t1", "title": "Pricing v2", "url": "https://example.invalid/t1"},
                                               fields=(Field("comment", "Comment", "x"),))])
    with db.get_db() as conn:
        outbox._ensure(conn)
        conn.execute("INSERT INTO links (recording_id, action_item_id, plugin_id, service, external_id, url, kind, created_at) "
                     "VALUES ('sf-ns', ?, 'slack', 'slack', 'C1:1', 'https://example.invalid/m', 'message', '2026-11-10')", (second,))
        conn.commit()
    status, body = call(port, "GET", "/api/surfaces?context=recording&id=sf-ns")
    rows = body["contributions"]
    chip = next(c for c in rows if c["surface"] == "action_item.chip" and c["target"] == first)
    assert (chip["plugin_id"], chip["label"], chip["state"], chip["proposal_key"], chip["shown"]) == \
        ("notion", "Link to task: Pricing v2", "pending", "n:link:1", True)
    sent = next(c for c in rows if c["surface"] == "action_item.chip" and c["target"] == second)
    assert (sent["plugin_id"], sent["label"], sent["state"], sent["url"]) == ("slack", "Slack", "link", "https://example.invalid/m")
    footer = next(c for c in rows if c["surface"] == "recording.footer")
    assert footer["plugin_id"] == "notion" and footer["badge"] == 1
    assert any(c["surface"] == "recording.menu" and c["action"]["id"] == "suggest_again" for c in rows)
    assert any(c["plugin_id"] == "slack" and c["surface"] == "selection.action" and c["label"] == "Send to Slack" for c in rows)
    assert notion.requests == [] and slack.requests == []          # reading surfaces makes no network call

    app = call(port, "GET", "/api/surfaces?context=app")[1]["contributions"]
    sections = {c["plugin_id"]: c for c in app if c["surface"] == "app.settings_section"}
    assert sections["notion"]["panel"]["load"] == "settings_form" and sections["slack"]["panel"]["submit"] == "save_settings"
    assert notion.requests == [], "the Notion database list is fetched only when its section is opened"


def test_notion_settings_section_loads_by_listing_calls_and_saves(port, bundled):
    notion, _ = bundled
    notion.on("POST", "/search", {"results": [{"id": "db-1", "title": [{"plain_text": "Team tasks"}]}]})
    notion.on("GET", "/databases/db-1", {"properties": {"Name": {"type": "title"}, "State": {"type": "status", "status": {"options": [{"name": "Done"}]}}}})
    notion.on("POST", "/databases/db-1/query", {"results": [], "has_more": False})
    status, body = call(port, "POST", "/api/surfaces/action", {"plugin_id": "notion", "action_id": "settings_form", "values": {"database_id": "db-1"}})
    assert status == 200, body
    names = [b.get("name") for b in body["panel"]["blocks"] if b["type"] == "field"]
    assert names[:3] == ["database_id", "mapping.title", "mapping.status"] and "usage_instructions" in names
    status, body = call(port, "POST", "/api/surfaces/action", {"plugin_id": "notion", "action_id": "save_settings", "values": {
        "database_id": "db-1", "mapping.title": "Name", "mapping.status": "State", "usage_instructions": "Small tasks only"}})
    assert status == 200 and body["toast"] == "Notion settings saved."
    s = outbox.plugin_settings("notion")
    assert s["mapping"] == {"title": "Name", "status": "State"} and s["usage_instructions"] == "Small tasks only"
    assert all(r["path"] in ("/search", "/databases/db-1", "/databases/db-1/query") for r in notion.requests)


def test_slack_send_makes_one_proposal_and_nothing_when_disconnected(port, bundled, monkeypatch):
    _, slack = bundled
    slack.on("GET", "/conversations.list", {"channels": [{"id": "C1", "name": "standup", "is_member": True}]})
    slack.on("GET", "/users.list", {"members": []})
    slack.on("POST", "/auth.test", {"user_id": "U1"})
    slack.on("GET", "/auth.test", {"user_id": "U1"})
    ids = recording("sf-slack", ["Send the pricing draft"])
    status, body = call(port, "POST", "/api/surfaces/action", {"plugin_id": "slack", "action_id": "send", "context": "recording",
                                                               "id": "sf-slack", "action_item_ids": ids})
    assert status == 200, body
    assert body["proposal"]["kind"] == "message.post" and body["proposal"]["action_item_ids"] == ids
    assert not any(r["path"] == "/chat.postMessage" for r in slack.requests), "nothing is posted before Confirm"
    import connections
    connections.use("slack", None)
    assert [c for c in call(port, "GET", "/api/surfaces?context=recording&id=sf-slack")[1]["contributions"] if c["plugin_id"] == "slack"] == []


# ---- Settings in the v2 shell draws from data (T5) ------------------------------

def test_plugin_states_turn_a_plugin_off_everywhere(port, plugins):
    status, body = call(port, "GET", "/api/plugin-states")
    states = {p["id"]: p["enabled"] for p in body["plugins"]}
    assert states["surf-a"] is True and states["notion"] is False
    assert call(port, "POST", "/api/plugin-states", {"id": "surf-a", "enabled": False})[0] == 200
    assert only(port, "app", "surf-a") == []
    assert call(port, "POST", "/api/plugin-states", {"id": "nobody", "enabled": True})[0] == 400
    assert call(port, "POST", "/api/plugin-states", {"id": "surf-a", "enabled": True})[0] == 200
    assert only(port, "app", "surf-a")


def test_connections_carry_their_own_label_and_token_hint(port):
    status, body = call(port, "GET", "/api/connections")
    for service, c in body["connections"].items():
        assert c["label"] and c["token_hint"], service
