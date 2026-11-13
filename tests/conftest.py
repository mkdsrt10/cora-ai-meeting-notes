"""Point every test at a throwaway data dir *before* any app module imports
paths.py, so tests never read or modify a real user's recordings or DB."""
import os
import sys
import tempfile
from pathlib import Path

_DATA = tempfile.mkdtemp(prefix="cora-test-")
os.environ["VOICECOACH_DATA_DIR"] = _DATA
os.environ.pop("VOICECOACH_ENTERPRISE_LOCKDOWN", None)
# No background audio pruning against other suites' fixture Recordings;
# tests/test_audio_pruning.py turns it back on where it needs it.
os.environ["CORA_AUDIO_PRUNING_DISABLED"] = "1"
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))


import pytest  # noqa: E402


@pytest.fixture
def fake_text(monkeypatch):
    """Every text_model(profile) built during the test uses one FakeText adapter.
    Set `fake_text.reply` (str, list or callable) before the code under test runs."""
    from pipeline import text_model

    class Fake(text_model.FakeText):
        reply = ""

        def complete(self, prompt, **kwargs):
            self._reply = self.reply
            return super().complete(prompt, **kwargs)

    fake = Fake()
    monkeypatch.setattr(text_model, "_adapter", lambda preset, model, settings: fake)
    monkeypatch.setattr(text_model, "_saved", lambda preset: {"model": "saved-" + preset})
    return fake


@pytest.fixture
def fake_transcriber(monkeypatch):
    """Every transcriber(profile) built during the test is a FakeTranscriber
    returning `fake_transcriber.segments`; `profiles` records what was asked for."""
    from pipeline import transcriber

    recorder = type("Recorder", (), {})()
    recorder.segments, recorder.profiles = [], []

    def make(profile):
        recorder.profiles.append(dict(profile))
        return transcriber.FakeTranscriber(recorder.segments, engine=profile.get("transcription") or "local")
    monkeypatch.setattr(transcriber, "_make", make)
    return recorder
