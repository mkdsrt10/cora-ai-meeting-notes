"""The after_meeting Hook runs once per processed Recording, after its notes
and Action items are saved, while the source audio still exists, outside the
processing lock and outside the pipeline's trace run. Audio cleanup
(retain_audio off) happens after the Hook, even when a Plugin fails."""
import json

import pytest

import ai_trace
import db
import paths
import plugin_host
import processing
from plugin_host import Plugin


@pytest.fixture
def hook(monkeypatch):
    """Register one after_meeting Hook for the test; `hook.fn(recording_id)` runs inside it."""
    class Holder:
        fn = staticmethod(lambda recording_id: None)
        calls: list = []
    holder = Holder()
    holder.calls = []

    def run(recording_id):
        holder.calls.append(recording_id)
        holder.fn(recording_id)
    plugin_host.register(Plugin(id="fake-after", name="After", enabled_by_default=True, hooks={"after_meeting": run}))
    yield holder
    plugin_host.unregister("fake-after")


@pytest.fixture
def retain_off():
    db.init_db()
    db.set_setting("retain_audio", False)
    yield
    db.set_setting("retain_audio", True)


def _local_recording(name, fake_text, fake_transcriber, monkeypatch):
    from pipeline import runner
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    db.create_recording(name, str(folder), name, "2026-11-01T09:00:00+00:00", 1.0, 1, {})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "You")
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."}]

    def reply(prompt, trace, **kwargs):
        if trace == "template.select":
            return "general"
        return json.dumps(dict(title="Sync", overview="Deck.", action_items_md="- Send the deck by Friday",
                               decisions_md="- None noted.", timeline_md="- Deck", open_questions_md="- None noted.",
                               key_entities_md="- Deck"))
    fake_text.reply = reply
    return folder


PROFILE = {"mode": "cloud", "provider": "openai", "transcription": "gemini"}


def test_hook_sees_saved_notes_and_audio_then_audio_is_deleted(fake_text, fake_transcriber, monkeypatch, hook, retain_off):
    from pipeline import runner
    folder = _local_recording("hook-audio", fake_text, fake_transcriber, monkeypatch)
    seen = {}

    def inspect(recording_id):
        seen["audio"] = (folder / "audio.wav").exists()
        seen["action_items"] = (db.get_recording_data(recording_id, "call_summary") or {}).get("action_items")
    hook.fn = inspect
    runner.process_recording_local(folder, PROFILE)
    assert hook.calls == ["hook-audio"]
    assert seen == {"audio": True, "action_items": ["Send the deck by Friday"]}
    assert not (folder / "audio.wav").exists()


def test_hook_runs_outside_the_processing_lock_and_trace_run(fake_text, fake_transcriber, monkeypatch, hook):
    from pipeline import runner
    folder = _local_recording("hook-lock", fake_text, fake_transcriber, monkeypatch)
    monkeypatch.setattr(ai_trace, "enabled", lambda: True)
    seen = {}

    def take_lock(recording_id):
        with processing.scope(processing.validate({}), wait=False):  # raises "busy" if still held
            seen["locked"] = True
        seen["trace_run"] = ai_trace._run_id.get()
    hook.fn = take_lock
    runner.process_recording_local(folder, PROFILE)
    assert seen == {"locked": True, "trace_run": None}
    assert (folder / "audio.wav").exists()  # retain_audio defaults on


def test_failing_hook_does_not_block_audio_cleanup(fake_text, fake_transcriber, monkeypatch, hook, retain_off):
    from pipeline import runner
    folder = _local_recording("hook-fails", fake_text, fake_transcriber, monkeypatch)

    def explode(recording_id):
        raise RuntimeError("plugin broke")
    hook.fn = explode
    runner.process_recording_local(folder, PROFILE)
    assert hook.calls == ["hook-fails"]
    assert not (folder / "audio.wav").exists()


def test_merged_continuation_reports_its_parent(fake_text, fake_transcriber, monkeypatch, hook, retain_off):
    from pipeline import runner
    parent = paths.RECORDINGS_DIR / "hook-parent"
    parent.mkdir(parents=True, exist_ok=True)
    db.init_db()
    db.create_recording("hook-parent", str(parent), "p", "2026-11-01T08:00:00+00:00", 1.0, 1, {})
    child = _local_recording("hook-child", fake_text, fake_transcriber, monkeypatch)
    db.update_recording_data("hook-child", "metadata", {"continues_recording_id": "hook-parent"})
    seen = {}
    hook.fn = lambda recording_id: seen.update(parts=sorted(p.name for p in parent.glob("audio_part*")))
    result = runner.process_recording_local(child, PROFILE)
    assert result["recording_id"] == "hook-parent"
    assert hook.calls == ["hook-parent"]
    assert seen == {"parts": ["audio_part2.mov"]}  # the merged chunk's audio is readable in the Hook
    assert not child.exists() and not list(parent.glob("audio_part*"))


def test_gemini_diarization_runs_hook_before_cleanup_outside_trace(monkeypatch, hook, retain_off):
    import diarization
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "hook-gemini"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.m4a").write_bytes(b"")
    db.create_recording("hook-gemini", str(folder), "g", "2026-11-01T09:00:00+00:00", 1.0, 1, {})
    monkeypatch.setattr(ai_trace, "enabled", lambda: True)
    monkeypatch.setattr(diarization, "_diarize", lambda f, model, client: {"segments": []})
    seen = {}
    hook.fn = lambda recording_id: seen.update(audio=(folder / "audio.m4a").exists(), trace_run=ai_trace._run_id.get())
    diarization.diarize(folder, client=object())
    assert hook.calls == ["hook-gemini"]
    assert seen == {"audio": True, "trace_run": None}
    assert not (folder / "audio.m4a").exists()
