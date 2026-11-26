"""Core Context sources (T3): Prior meetings and Work context, through notes
generation with FakeText; the Profile field over HTTP; terms blocks reaching
the ASR prompt."""
import http.client
import json
import threading

import pytest

import action_items
import db
import notes_context
import paths
import plugin_host
import server
from api import auth
from notes_context import ContextBlock, FunctionSource
from pipeline import context as asr_context
from pipeline.processing_notes import generate_notes
from plugin_host import Plugin

LOCAL = {"provider": "local_mlx", "model": "", "template": "general", "mode": "local_light"}
SEGMENTS = [{"speaker_name": "Priya Shah", "start": "00:00", "end": "00:05", "text": "I'll send the deck by Friday."}]
TOKEN = "context-sources-test-token"


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
def settings():
    db.init_db()
    saved = {k: db.get_setting(k) for k in (notes_context.SETTING, notes_context.WORK_CONTEXT_SETTING)}
    yield db.set_setting
    for key, value in saved.items():
        db.set_setting(key, value)


def recording(rec_id, *, at, participants=(), folder_id=None, items=(), decisions=()):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), rec_id, at, 60, 1, {"folder_id": folder_id} if folder_id else {})
    (folder / "participants.json").write_text(json.dumps(list(participants)))
    db.update_recording_data(rec_id, "call_summary", {"action_items": list(items), "decisions": list(decisions)})
    action_items.sync(rec_id)
    return folder


def notes_prompts(fake_text, folder):
    fake_text.reply = "- x"
    fake_text.calls.clear()
    generate_notes("[00:00 - 00:05] Priya Shah: I'll send the deck by Friday.", [], SEGMENTS, options=LOCAL,
                   folder=folder)
    return {c["trace"]: c["prompt"] for c in fake_text.calls}


def test_prior_meetings_bring_open_items_and_decisions_from_meetings_with_the_same_people(fake_text, settings):
    settings(notes_context.SETTING, True)
    recording("prior-a1", at="2026-11-03T09:00:00+00:00", participants=["Priya Shah"],
              items=["Draft the Q4 plan (Owner: Priya)", "Book the offsite"], decisions=["Pricing stays at $40"])
    done = action_items.for_recording("prior-a1")[1]
    action_items.set_done(done["id"], True)
    recording("prior-a-other", at="2026-11-04T09:00:00+00:00", participants=["Nobody Else"],
              items=["Unrelated thing"], decisions=["Unrelated decision"])
    recording("prior-a-later", at="2026-11-20T09:00:00+00:00", participants=["Priya Shah"],
              items=["Future thing"])
    folder = recording("prior-a-now", at="2026-11-10T09:00:00+00:00", participants=["Priya Shah"])
    p = notes_prompts(fake_text, folder)
    action = p["enhanced_notes.action_items"]
    assert '<context source="prior_meetings">' in action
    assert "Draft the Q4 plan (Owner: Priya)" in action and "Follow-up:" in action
    assert "Book the offsite" not in action          # done items are not open
    assert "Unrelated thing" not in action and "Future thing" not in action
    decisions = p["enhanced_notes.key_discussion_decisions"]
    assert "Pricing stays at $40" in decisions and "Unrelated decision" not in decisions
    assert "Pricing stays at $40" not in action


def test_prior_meetings_match_by_folder_too(fake_text, settings):
    settings(notes_context.SETTING, True)
    recording("prior-f1", at="2026-11-02T09:00:00+00:00", folder_id="fold-x", items=["Ship the release notes"])
    folder = recording("prior-f-now", at="2026-11-05T09:00:00+00:00", folder_id="fold-x")
    assert "Ship the release notes" in notes_prompts(fake_text, folder)["enhanced_notes.action_items"]


def test_work_context_is_an_instruction_in_every_section_not_tagged_data(fake_text, settings):
    settings(notes_context.SETTING, True)
    settings(notes_context.WORK_CONTEXT_SETTING, "I lead the Payments team at Acme. Chunky Action items.")
    folder = recording("work-ctx", at="2026-11-06T09:00:00+00:00")
    p = notes_prompts(fake_text, folder)
    for trace in ("enhanced_notes.overview", "enhanced_notes.action_items", "enhanced_notes.open_questions"):
        assert "About the user's work (follow it when writing): I lead the Payments team" in p[trace]
    assert '<context source="work_context">' not in p["enhanced_notes.action_items"]


def test_profile_about_my_work_is_saved_and_read(port, settings):
    assert call(port, "POST", "/api/settings", {"key": "work_context", "value": "  PM on Cora.  "})[0] == 200
    assert call(port, "POST", "/api/settings", {"key": "work_context"})[1] == {"value": "PM on Cora."}
    assert call(port, "POST", "/api/settings", {"key": "work_context", "value": "x" * 5000})[0] == 400
    assert call(port, "POST", "/api/settings", {"key": "notes_context_enabled", "value": "yes"})[0] == 400
    assert call(port, "POST", "/api/settings", {"key": "notes_context_enabled", "value": True})[0] == 200


def test_terms_blocks_reach_the_asr_prompt_and_only_when_on(settings):
    settings(notes_context.SETTING, True)
    settings(notes_context.WORK_CONTEXT_SETTING, "We ship Zephyrix and the KestrelOps dashboard.")
    folder = recording("asr-terms", at="2026-11-07T09:00:00+00:00")
    plugin_host.register(Plugin(id="terms-test", name="Terms", enabled_by_default=True, context_sources=(
        FunctionSource("terms.src", lambda req: [ContextBlock("terms.src", "Quorvane\nBrimstell", 0.5,
                                                              frozenset({"asr"}), kind="terms")]),)))
    try:
        prompt = asr_context.build_context(folder, "Weekly sync").prompt()
        assert {"Zephyrix", "KestrelOps", "Quorvane", "Brimstell"} <= set(prompt.replace(",", " ").replace(".", " ").split())
        settings(notes_context.SETTING, False)
        assert "Quorvane" not in asr_context.build_context(folder, "Weekly sync").prompt()
    finally:
        plugin_host.unregister("terms-test")
