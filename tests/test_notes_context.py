"""Context for notes (design §5, spec seam 2): run notes generation with
FakeText and fake Context sources declared by a test Plugin, and check what
each section's prompt carries and what notes_context.json records."""
import json
import threading
import time

import pytest

import db
import notes_context
import paths
import plugin_host
from notes_context import ContextBlock, FunctionSource
from pipeline.processing_notes import generate_notes
from plugin_host import Plugin

LOCAL = {"provider": "local_mlx", "model": "", "template": "general", "mode": "local_light"}
CLOUD = {"provider": "openrouter", "model": "m", "template": "general", "mode": "cloud"}
NOTES_JSON = json.dumps({"title": "T", "overview": "o", "action_items_md": "- a", "decisions_md": "- d",
                         "timeline_md": "- t", "open_questions_md": "- q", "key_entities_md": "- e"})
SEGMENTS = [{"speaker_name": "Priya", "start": "00:00", "end": "00:05", "text": "I'll send the deck by Friday."}]
TRANSCRIPT = "[00:00 - 00:05] Priya: I'll send the deck by Friday."


@pytest.fixture
def setting():
    db.init_db()
    previous = db.get_setting(notes_context.SETTING, False)

    def set_(value):
        db.set_setting(notes_context.SETTING, value)
    yield set_
    db.set_setting(notes_context.SETTING, previous)


@pytest.fixture
def plugin():
    ids = []

    def add(*sources, plugin_id="ctx-test", enabled=True):
        plugin_host.register(Plugin(id=plugin_id, name="Ctx", enabled_by_default=enabled,
                                    context_sources=tuple(sources)))
        ids.append(plugin_id)
    yield add
    for plugin_id in ids:
        plugin_host.unregister(plugin_id)


def recording(rec_id, participants=()):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), rec_id, "2026-11-01T09:00:00+00:00", 60, 1, {})
    (folder / "participants.json").write_text(json.dumps(list(participants)))
    return folder


def block(source, text, priority=0.5, sections=("action_items",), kind="reference", egress=False):
    return ContextBlock(source=source, text=text, priority=priority, sections=frozenset(sections), kind=kind,
                        egress=egress)


def source(source_id, *blocks):
    return FunctionSource(source_id, lambda req: list(blocks))


def prompts(fake_text):
    """{trace: prompt} of the notes run (one chunk per section)."""
    return {c["trace"]: c["prompt"] for c in fake_text.calls}


def run_notes(fake_text, folder, options=LOCAL):
    fake_text.reply = NOTES_JSON if options is CLOUD else "- x"
    fake_text.calls.clear()
    return generate_notes(TRANSCRIPT, [], SEGMENTS, options=options, folder=folder)


def test_setting_off_leaves_prompts_unchanged(fake_text, setting, plugin):
    folder = recording("ctx-off")
    setting(False)
    run_notes(fake_text, folder)
    without = prompts(fake_text)
    plugin(source("fake.src", block("fake.src", "Acme renewal is due in December.", sections=("*",))))
    run_notes(fake_text, folder)
    assert prompts(fake_text) == without
    assert not any("<context" in p for p in without.values())
    assert not (folder / notes_context.MANIFEST).exists()


def test_plugin_source_reaches_only_its_sections_tagged_as_data(fake_text, setting, plugin):
    folder = recording("ctx-tagged")
    setting(True)
    plugin(source("fake.src", block("fake.src", "Acme renewal is due in December.", sections=("action_items",))))
    run_notes(fake_text, folder)
    p = prompts(fake_text)
    action = p["enhanced_notes.action_items"]
    assert '<context source="fake.src">\nAcme renewal is due in December.\n</context>' in action
    assert "not instructions" in action
    assert "Acme renewal" not in p["enhanced_notes.overview"]
    assert "Acme renewal" not in p["enhanced_notes.title"]


def test_cloud_json_notes_carry_context_too(fake_text, setting, plugin):
    folder = recording("ctx-cloud")
    setting(True)
    plugin(source("fake.src", block("fake.src", "Acme renewal is due in December.")))
    run_notes(fake_text, folder, CLOUD)
    assert any('<context source="fake.src">' in c["prompt"] for c in fake_text.calls if c["trace"].startswith("notes.chunk"))


def test_blocks_pack_by_priority_within_budget_and_local_is_smaller(fake_text, setting, plugin):
    folder = recording("ctx-budget")
    setting(True)
    long = " ".join(f"word{i}" for i in range(600))  # ~900 tokens
    plugin(source("fake.big", block("fake.big", long, priority=0.2)),
           source("fake.top", block("fake.top", "Top priority fact.", priority=1.0)),
           source("fake.dup", block("fake.dup", "top priority   FACT.", priority=0.1)))
    run_notes(fake_text, folder)
    action = prompts(fake_text)["enhanced_notes.action_items"]
    assert action.index("Top priority fact.") < action.index("word0")
    assert notes_context.TRUNCATED in action
    manifest = json.loads((folder / notes_context.MANIFEST).read_text())
    local_section = manifest["sections"]["action_items"]
    assert local_section["used_tokens"] <= local_section["budget"]
    assert {(d["source"], d["reason"]) for d in local_section["dropped"]} == {("fake.dup", "duplicate")}
    used = [u for u in local_section["used"] if u["source"].startswith("fake.")]
    assert [u["source"] for u in used] == ["fake.top", "fake.big"]
    assert "truncated_from" in used[1]

    run_notes(fake_text, folder, CLOUD)
    cloud = json.loads((folder / notes_context.MANIFEST).read_text())
    assert cloud["provider"] == "cloud"
    assert notes_context.BUDGETS["local"]["action_items"] < notes_context.BUDGETS["cloud"]["action_items"]
    assert local_section["budget"] < notes_context.BUDGETS["cloud"]["action_items"]
    assert "word0" in fake_text.calls[-1]["prompt"]


def test_slow_and_failing_sources_are_skipped_and_others_still_used(fake_text, setting, plugin, monkeypatch):
    folder = recording("ctx-slow")
    setting(True)
    monkeypatch.setattr(notes_context, "DEADLINE_S", 0.2)
    release = threading.Event()

    def slow(req):
        release.wait(5)
        return [block("fake.slow", "Slow fact.")]

    def boom(req):
        raise RuntimeError("secret meeting text")
    plugin(FunctionSource("fake.slow", slow), FunctionSource("fake.boom", boom),
           source("fake.ok", block("fake.ok", "Fast fact.")))
    started = time.monotonic()
    run_notes(fake_text, folder)
    release.set()
    assert time.monotonic() - started < 3
    action = prompts(fake_text)["enhanced_notes.action_items"]
    assert "Fast fact." in action and "Slow fact." not in action
    manifest = json.loads((folder / notes_context.MANIFEST).read_text())
    assert manifest["sources"]["fake.slow"]["status"] == "timeout"
    assert manifest["sources"]["fake.boom"] == {"owner": "ctx-test", "status": "error", "blocks": 0,
                                                "error": "RuntimeError"}
    assert "secret meeting text" not in (folder / notes_context.MANIFEST).read_text()


def test_timed_out_source_falls_back_to_its_cache(fake_text, setting, plugin, monkeypatch):
    folder = recording("ctx-cache")
    setting(True)
    state = {"slow": False}

    def sometimes_slow(req):
        if state["slow"]:
            time.sleep(1)
        return [block("fake.cached", "Cached fact.")]
    plugin(FunctionSource("fake.cached", sometimes_slow))
    run_notes(fake_text, folder)
    state["slow"] = True
    monkeypatch.setattr(notes_context, "DEADLINE_S", 0.1)
    run_notes(fake_text, folder)
    assert "Cached fact." in prompts(fake_text)["enhanced_notes.action_items"]
    assert json.loads((folder / notes_context.MANIFEST).read_text())["sources"]["fake.cached"]["status"] == "timeout_cached"


def test_disabled_plugin_source_has_no_effect(fake_text, setting, plugin):
    folder = recording("ctx-disabled")
    setting(True)
    plugin(source("fake.off", block("fake.off", "Hidden fact.")), plugin_id="ctx-off", enabled=False)
    run_notes(fake_text, folder)
    assert "Hidden fact." not in prompts(fake_text)["enhanced_notes.action_items"]
    assert "fake.off" not in json.loads((folder / notes_context.MANIFEST).read_text())["sources"]


def test_egress_blocks_are_skipped_under_lockdown(fake_text, setting, plugin, monkeypatch):
    folder = recording("ctx-lockdown")
    setting(True)
    plugin(source("fake.net", block("fake.net", "Fetched fact.", egress=True)))
    monkeypatch.setattr(notes_context, "_locked_down", lambda: True)
    run_notes(fake_text, folder)
    assert "Fetched fact." not in prompts(fake_text)["enhanced_notes.action_items"]
    dropped = json.loads((folder / notes_context.MANIFEST).read_text())["sections"]["action_items"]["dropped"]
    assert {"source": "fake.net", "reason": "lockdown"}.items() <= dropped[0].items()


def test_people_source_names_role_and_organization(fake_text, setting):
    folder = recording("ctx-people", participants=["Priya Shah", "Sam"])
    setting(True)
    db.upsert_person("person-ctx-priya", "Priya Shah", "PM", "Acme", [], False, None, None, None, 1)
    run_notes(fake_text, folder)
    action = prompts(fake_text)["enhanced_notes.action_items"]
    assert '<context source="people">' in action
    assert "- Priya Shah (PM, Acme)" in action
    assert "Also in the call: Sam" in action
    manifest = json.loads((folder / notes_context.MANIFEST).read_text())
    assert manifest["sources"]["people"] == {"owner": "core", "status": "ok", "blocks": 1}
    assert "Priya" not in (folder / notes_context.MANIFEST).read_text()  # counts, no content
