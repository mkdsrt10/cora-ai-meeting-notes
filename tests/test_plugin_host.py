"""The Plugin seam: a bundled Plugin declares its View, its data for a
Recording, its routes and its Hooks in one place; the host wires them in.
Tests go through the host's interface (register / HTTP / view model /
run_hook), never through a plugin's internals."""
import http.client
import json
import threading

import pytest

import db
import paths
import plugin_host
import server
from api import auth, views
from plugin_host import Plugin, View

TOKEN = "plugin-host-test-token"


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
    data = resp.read()
    return resp.status, (json.loads(data) if data else {})


@pytest.fixture
def registered():
    """Register plugins for one test and remove them afterwards."""
    ids = []

    def add(plugin):
        plugin_host.register(plugin)
        ids.append(plugin.id)
        return plugin
    yield add
    for plugin_id in ids:
        plugin_host.unregister(plugin_id)


@pytest.fixture
def config():
    """Write config.json for one test, restoring whatever was there."""
    previous = paths.CONFIG_PATH.read_text() if paths.CONFIG_PATH.exists() else None

    def write(value):
        paths.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG_PATH.write_text(json.dumps(value))
    yield write
    if previous is None:
        paths.CONFIG_PATH.unlink(missing_ok=True)
    else:
        paths.CONFIG_PATH.write_text(previous)


def make_recording(rec_id, *, diarized=True, self_speaker=None, coaching=None):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording(rec_id, str(folder), rec_id, "2026-10-01T10:00:00", 60, 1, {})
    if diarized:
        db.update_recording_data(rec_id, "diarization", {
            "segments": [{"speaker_id": "SPEAKER_1", "start": "00:00", "end": "00:10", "text": "hello"}],
        })
    if self_speaker:
        db.update_recording_data(rec_id, "identity", {"speaker_id": self_speaker})
    if coaching:
        db.update_recording_data(rec_id, "coaching", coaching)
    return db.get_recording(rec_id)


def ping(req, path, query):
    req.send_json({"pong": True})


def test_plugin_routes_respond_under_its_namespace(port, registered):
    registered(Plugin(id="fake-routes", name="Fake", enabled_by_default=True, routes=(("GET", "ping", ping),)))
    status, body = call(port, "GET", "/api/plugins/fake-routes/ping")
    assert status == 200 and body == {"pong": True}


def test_enabled_plugin_view_is_listed_for_the_renderer(port, registered):
    registered(Plugin(id="fake-view", name="Fake", enabled_by_default=True,
                      view=View(title="Fake page", subtitle="Things", icon="list")))
    status, body = call(port, "GET", "/api/plugins")
    assert status == 200
    listed = {p["id"]: p for p in body["plugins"]}
    assert listed["fake-view"]["view"] == {"id": "fake-view", "title": "Fake page", "subtitle": "Things", "icon": "list"}
    assert body["stages"]["needs_speaker_confirmation"] == "Identify me"


def test_disabled_plugin_is_absent_everywhere(port, registered):
    calls = []
    registered(Plugin(id="fake-off", name="Off", view=View(title="Off"), routes=(("GET", "ping", ping),),
                      payload=lambda rec: {"x": 1}, hooks={"after_meeting": calls.append}))
    rec = make_recording("rec_plugin_off")
    assert "fake-off" not in {p["id"] for p in call(port, "GET", "/api/plugins")[1]["plugins"]}
    assert call(port, "GET", "/api/plugins/fake-off/ping")[0] == 404
    assert "fake-off" not in views.recording_item(rec)["plugins"]
    assert "fake-off" not in plugin_host.run_hook("after_meeting", rec["id"])
    assert calls == []


def test_config_flag_overrides_the_plugin_default(registered, config):
    registered(Plugin(id="fake-flag", name="Flag"))
    assert "fake-flag" not in {p.id for p in plugin_host.enabled_plugins()}
    config({"plugins": {"fake-flag": {"enabled": True}}})
    assert "fake-flag" in {p.id for p in plugin_host.enabled_plugins()}


def test_payload_appears_in_the_recording_view_model(registered):
    registered(Plugin(id="fake-data", name="Data", enabled_by_default=True,
                      payload=lambda rec: {"seen": rec["id"]}))
    registered(Plugin(id="fake-broken", name="Broken", enabled_by_default=True,
                      payload=lambda rec: 1 / 0))
    item = views.recording_item(make_recording("rec_plugin_payload"))
    assert item["plugins"]["fake-data"] == {"seen": "rec_plugin_payload"}
    assert "fake-broken" not in item["plugins"]


def test_run_hook_calls_every_enabled_plugin_and_isolates_failures(registered, capsys):
    seen = []

    def explode(recording_id):
        raise RuntimeError("secret transcript text")
    registered(Plugin(id="fake-boom", name="Boom", enabled_by_default=True, hooks={"after_meeting": explode}))
    registered(Plugin(id="fake-hook", name="Hook", enabled_by_default=True, hooks={"after_meeting": seen.append}))
    result = plugin_host.run_hook("after_meeting", "rec_hook")
    assert result["fake-boom"] is False and result["fake-hook"] is True
    assert seen == ["rec_hook"]
    out = capsys.readouterr().out
    assert "fake-boom" in out and "secret transcript text" not in out


def test_daily_hook_takes_no_recording(registered):
    ran = []
    registered(Plugin(id="fake-daily", name="Daily", enabled_by_default=True, hooks={"daily": lambda: ran.append(1)}))
    assert plugin_host.run_hook("daily")["fake-daily"] is True and ran == [1]
    with pytest.raises(ValueError):
        plugin_host.run_hook("not_a_hook")


def test_duplicate_plugin_ids_are_rejected(registered):
    registered(Plugin(id="fake-dup", name="Dup"))
    with pytest.raises(ValueError):
        plugin_host.register(Plugin(id="fake-dup", name="Dup again"))


def test_bundled_plugins_are_discovered_with_their_defaults():
    ids = {p.id for p in plugin_host.plugins()}
    assert {"coaching", "todo"} <= ids
    enabled = {p.id for p in plugin_host.enabled_plugins()}
    assert "coaching" not in enabled  # off unless plugins.coaching.enabled
    assert "todo" in enabled


COACHED = {"model": "gemini-3.8-flash", "target_speaker": "SPEAKER_1", "executive_assessment": "Clear.",
           "scores": {"clarity": {"score": 80}}}


@pytest.mark.parametrize("rec_id,kwargs,coaching_on,expected", [
    ("rec_stage_a", dict(diarized=False), False, "needs_diarization"),
    ("rec_stage_b", dict(), False, "needs_speaker_confirmation"),
    ("rec_stage_c", dict(self_speaker="SPEAKER_1"), False, "ready"),
    ("rec_stage_d", dict(self_speaker="SPEAKER_1", coaching=COACHED), False, "ready"),
    ("rec_stage_e", dict(self_speaker="SPEAKER_1"), True, "ready_for_coaching"),
    ("rec_stage_f", dict(self_speaker="SPEAKER_1", coaching=COACHED), True, "coached"),
])
def test_views_and_mcp_agree_on_stage(config, rec_id, kwargs, coaching_on, expected):
    import mcp_server
    config({"plugins": {"coaching": {"enabled": coaching_on}}})
    rec = make_recording(rec_id, **kwargs)
    assert views.recording_item(rec)["analysis_stage"] == expected
    listed = {r["id"]: r["stage"] for r in mcp_server.cora_list_recordings(query=rec_id)}
    assert listed[rec_id] == expected


def test_coaching_payload_carries_its_outputs_when_enabled(config):
    config({"plugins": {"coaching": {"enabled": True}}})
    item = views.recording_item(make_recording("rec_coach_payload", self_speaker="SPEAKER_1", coaching=COACHED), detailed=True)
    coaching = item["plugins"]["coaching"]
    assert coaching["report"]["executive_assessment"] == "Clear."
    assert coaching["scores"] == {"clarity": 80, "overall": 80}


def test_todo_lists_action_items_across_recordings_with_done_state(port):
    rec = make_recording("rec_todo_items", self_speaker="SPEAKER_1")
    db.update_recording_data(rec["id"], "call_summary", {"action_items": ["Send the deck", {"action": "Book the room"}]})
    items = [i for i in call(port, "GET", "/api/plugins/todo/items")[1]["items"] if i["recording_id"] == rec["id"]]
    assert [(i["text"], i["done"]) for i in items] == [("Send the deck", False), ("Book the room", False)]
    assert call(port, "POST", "/api/plugins/todo/done", {"recording_id": rec["id"], "index": 1, "done": True})[0] == 200
    items = [i for i in call(port, "GET", "/api/plugins/todo/items")[1]["items"] if i["recording_id"] == rec["id"]]
    assert [i["done"] for i in items] == [False, True]
    assert call(port, "POST", "/api/plugins/todo/done", {"recording_id": "nope", "index": 0, "done": True})[0] == 400
