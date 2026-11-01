"""Coaching's after_meeting Hook uploads audio to Gemini only when the user
enabled Coaching, and coaches a Recording once per diarization: a repeated
Hook call for the same diarization makes no Gemini call and keeps the report."""
import json

import pytest

import db
import paths
import plugin_host


class FakeGemini:
    """Stands in for the Gemini audio call (engine.interact_with_audio)."""

    def __init__(self):
        self.calls = []

    def __call__(self, audio, prompt, schema, model=None, client=None):
        self.calls.append(audio.name)
        return {"executive_assessment": f"report {len(self.calls)}", "scores": {}}


@pytest.fixture
def gemini(monkeypatch):
    plugin_host.discover()
    from plugins.coaching import engine
    fake = FakeGemini()
    monkeypatch.setattr(engine, "interact_with_audio", fake)
    monkeypatch.setattr(engine, "analyze_delivery", lambda *a, **k: {})
    return fake


@pytest.fixture
def coaching_enabled():
    previous = paths.CONFIG_PATH.read_text() if paths.CONFIG_PATH.exists() else None

    def write(enabled):
        paths.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG_PATH.write_text(json.dumps({"plugins": {"coaching": {"enabled": enabled}}}))
    yield write
    if previous is None:
        paths.CONFIG_PATH.unlink(missing_ok=True)
    else:
        paths.CONFIG_PATH.write_text(previous)


def _diarized_recording(rec_id, analyzed_at="2026-11-01T10:00:00+00:00"):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.m4a").write_bytes(b"")
    db.create_recording(rec_id, str(folder), rec_id, "2026-11-01T09:00:00+00:00", 60, 1,
                        {"archetype": {"archetype_id": 2, "archetype_name": "Standup"}})
    diarize(rec_id, analyzed_at)
    db.update_recording_data(rec_id, "identity", {"speaker_id": "speaker_1"})
    return folder


def diarize(rec_id, analyzed_at):
    db.update_recording_data(rec_id, "diarization", {
        "model": "gemini-3.8-flash", "analyzed_at": analyzed_at,
        "speakers": [{"speaker_id": "speaker_1"}],
        "segments": [{"speaker_id": "speaker_1", "start": "00:00", "end": "00:05", "text": "hi"}],
    })


def test_coaches_once_per_diarization(gemini, coaching_enabled):
    coaching_enabled(True)
    _diarized_recording("coach-once")
    assert plugin_host.run_hook("after_meeting", "coach-once")["coaching"] is True
    assert gemini.calls == ["audio.m4a"]
    first = db.get_recording_data("coach-once", "coaching")
    assert first["executive_assessment"] == "report 1"

    assert plugin_host.run_hook("after_meeting", "coach-once")["coaching"] is True
    assert gemini.calls == ["audio.m4a"]  # no second upload
    assert db.get_recording_data("coach-once", "coaching") == first


def test_new_diarization_is_coached_again(gemini, coaching_enabled):
    coaching_enabled(True)
    _diarized_recording("coach-rediarized")
    plugin_host.run_hook("after_meeting", "coach-rediarized")
    diarize("coach-rediarized", "2026-11-01T11:00:00+00:00")
    plugin_host.run_hook("after_meeting", "coach-rediarized")
    assert len(gemini.calls) == 2


def test_disabled_coaching_never_uploads(gemini, coaching_enabled):
    coaching_enabled(False)
    _diarized_recording("coach-disabled")
    assert "coaching" not in plugin_host.run_hook("after_meeting", "coach-disabled")
    from plugins.coaching import plugin
    plugin.after_meeting("coach-disabled")  # even called directly
    assert gemini.calls == []
