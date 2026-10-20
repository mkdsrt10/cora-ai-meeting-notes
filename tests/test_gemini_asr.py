"""Windowed hosted transcription: the Gemini call, and the retry/split ladder.
No network: a fake client stands in for Gemini, and ffmpeg makes real audio."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from pipeline import gemini_asr, windowed
from pipeline.context import MeetingContext
from pipeline.windowed import WindowedASRError, transcribe_windows

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "mix.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=200",
                    "-ac", "1", "-ar", "16000", str(path)], check=True)
    return path


class FakeClient:
    def __init__(self, text=None, finish="STOP", error=None):
        self.calls, self._text, self._finish, self._error = [], text, finish, error
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, model, contents, config):
        self.calls.append({"model": model, "config": config, "contents": contents})
        if self._error:
            raise self._error
        return SimpleNamespace(text=self._text, candidates=[SimpleNamespace(finish_reason=self._finish)])


def clip(tmp_path):
    p = tmp_path / "c.flac"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=3", "-ac", "1", str(p)], check=True)
    return p


def test_window_call_parses_turns_and_never_sets_temperature(tmp_path):
    client = FakeClient(json.dumps({"turns": [{"start": 0.5, "end": 2.0, "text": "hello there"}]}))
    out = gemini_asr.transcribe_window(clip(tmp_path), 3.0, "ctx", client=client, model="gemini-3.7-flash")
    assert out == [{"start": 0.5, "end": 2.0, "text": "hello there"}]
    config = client.calls[0]["config"]
    assert getattr(config, "temperature", None) is None
    assert config.response_mime_type == "application/json"


def test_window_call_errors_are_typed(tmp_path):
    with pytest.raises(gemini_asr.AsrCallError, match="output tokens"):
        gemini_asr.transcribe_window(clip(tmp_path), 3.0, "c", client=FakeClient("{}", finish="FinishReason.MAX_TOKENS"), model="m")
    with pytest.raises(gemini_asr.AsrCallError, match="no text"):
        gemini_asr.transcribe_window(clip(tmp_path), 3.0, "c", client=FakeClient(""), model="m")
    with pytest.raises(gemini_asr.AsrCallError, match="request failed"):
        gemini_asr.transcribe_window(clip(tmp_path), 3.0, "c", client=FakeClient(error=RuntimeError("429")), model="m")


def test_thinking_config_is_dropped_when_the_model_rejects_it(tmp_path):
    class Picky(FakeClient):
        def _gen(self, model, contents, config):
            if getattr(config, "thinking_config", None):
                raise RuntimeError("thinking_level is not supported by this model")
            return super()._gen(model, contents, config)
    client = Picky(json.dumps({"turns": []}))
    assert gemini_asr.transcribe_window(clip(tmp_path), 3.0, "c", client=client, model="gemini-3.7-flash") == []


SPEECH = [(0.0, 60.0), (62.0, 130.0), (140.0, 195.0)]   # one window each side of the 8 s pause rule
CONTEXT = MeetingContext(title="Weekly", attendees=["Priya Shah"])


def good_caller(clip_path, duration, block):
    return [{"start": 1.0, "end": duration - 1.0, "text": "some real words were said in this window"}]


def test_windows_become_absolute_segments(audio, monkeypatch):
    segs = transcribe_windows(audio, SPEECH, CONTEXT, caller=good_caller, strict=SPEECH)
    assert segs and segs == sorted(segs, key=lambda s: s["start"])
    assert segs[0]["start"] >= 0 and segs[-1]["end"] <= 200


def test_context_block_reaches_the_model_with_names_not_in_the_system_prompt(audio):
    seen = []
    def spy(clip_path, duration, block):
        seen.append(block)
        return good_caller(clip_path, duration, block)
    CONTEXT.add("Northwind", "title")
    transcribe_windows(audio, SPEECH, CONTEXT, caller=spy, strict=SPEECH)
    assert "Priya Shah" in seen[0] and "Northwind" in seen[0]
    assert "Priya" not in gemini_asr.SYSTEM_INSTRUCTION


def test_transient_failure_is_retried(audio, monkeypatch):
    monkeypatch.setattr(windowed, "_sleep", lambda s: None)
    state = {"n": 0}
    def flaky(clip_path, duration, block):
        state["n"] += 1
        if state["n"] == 1:
            raise gemini_asr.AsrCallError("429")
        return good_caller(clip_path, duration, block)
    segs = transcribe_windows(audio, [(0.0, 50.0)], CONTEXT, caller=flaky, strict=[(0.0, 50.0)], workers=1)
    assert segs and state["n"] == 2


def test_a_failing_window_is_split_and_the_halves_retried(audio, monkeypatch):
    monkeypatch.setattr(windowed, "_sleep", lambda s: None)
    def only_short_windows(clip_path, duration, block):
        if duration > 100:
            raise gemini_asr.AsrCallError("too long for me")
        return good_caller(clip_path, duration, block)
    speech = [(0.0, 60.0), (66.0, 130.0)]             # one 130 s window with a 6 s pause
    segs = transcribe_windows(audio, speech, CONTEXT, caller=only_short_windows, strict=speech, workers=1)
    assert len(segs) == 2


def test_unfixable_window_fails_the_run_instead_of_dropping_it(audio, monkeypatch):
    monkeypatch.setattr(windowed, "_sleep", lambda s: None)
    def always_bad(clip_path, duration, block):
        raise gemini_asr.AsrCallError("blocked")
    with pytest.raises(WindowedASRError, match="failed for"):
        transcribe_windows(audio, [(0.0, 50.0)], CONTEXT, caller=always_bad, strict=[(0.0, 50.0)], workers=1)


def test_temp_clips_are_deleted(audio, tmp_path, monkeypatch):
    import tempfile
    made = []
    real = windowed.extract_clip_flac
    def tracking(*a, **k):
        p = real(*a, **k); made.append(p); return p
    monkeypatch.setattr(windowed, "extract_clip_flac", tracking)
    transcribe_windows(audio, SPEECH, CONTEXT, caller=good_caller, strict=SPEECH)
    assert made and not any(p.exists() for p in made)
    assert tempfile.gettempdir()
