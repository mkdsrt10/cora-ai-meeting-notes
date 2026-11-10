"""Windowed hosted transcription: the Gemini call, and the retry/split ladder.
No network: a fake client stands in for Gemini, and ffmpeg makes real audio."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from pipeline import gemini_asr, windowed
from pipeline.context import MeetingContext
from pipeline.windowed import transcribe_windows

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture(autouse=True)
def genai_types(monkeypatch):
    """google-genai is an optional extra; stand in for its `types` when absent."""
    try:
        from google.genai import types  # noqa: F401
        return
    except ImportError:
        pass
    import sys
    import types as pytypes

    class Obj:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    fake = SimpleNamespace(Part=SimpleNamespace(from_bytes=lambda data, mime_type: Obj(data=data, mime_type=mime_type)),
                           Schema=Obj, GenerateContentConfig=Obj, ThinkingConfig=Obj,
                           Type=SimpleNamespace(OBJECT="OBJECT", NUMBER="NUMBER", STRING="STRING", ARRAY="ARRAY"))
    module = pytypes.ModuleType("google.genai")
    module.types = fake
    monkeypatch.setitem(sys.modules, "google.genai", module)


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


def test_unfixable_window_is_kept_as_a_marked_gap_instead_of_dropped(audio, monkeypatch):
    monkeypatch.setattr(windowed, "_sleep", lambda s: None)
    def always_bad(clip_path, duration, block):
        raise gemini_asr.AsrCallError("blocked")
    segs = transcribe_windows(audio, [(0.0, 50.0)], CONTEXT, caller=always_bad, strict=[(0.0, 50.0)], workers=1)
    assert [(s["start"], s["end"], s["engine"]) for s in segs] == [(0.0, 50.0, "gap")]


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


def test_timestamp_overrun_in_continuous_speech_recovers_by_recursive_split(tmp_path, monkeypatch):
    # Regression for 720–1004s: model returns 302.6s for a 284s clip.
    monkeypatch.setattr(windowed, '_sleep', lambda _: None)
    clips, durations = [], []
    def extract(_, start, end):
        path = tmp_path / f'clip-{len(clips)}.flac'
        path.touch()
        clips.append(path)
        return path
    monkeypatch.setattr(windowed, 'extract_clip_flac', extract)
    def caller(clip, duration, block):
        durations.append(duration)
        if duration > 90:
            return [{'start':0,'end':duration/2,'text':'beginning'},
                    {'start':duration+18.6,'end':duration+20,'text':'invalid late turn'}]
        return [{'start':0,'end':duration,'text':'real speech throughout the smaller clip'}]
    speech = [(720.0,1004.0)]
    segments = transcribe_windows(tmp_path/'unused.wav', speech, CONTEXT, caller=caller, strict=speech, workers=1)
    assert [(s['start'],s['end']) for s in segments] == [(720,791),(791,862),(862,933),(933,1004)]
    assert durations.count(284) == 3 and durations.count(142) == 6 and durations.count(71) == 4
    assert not any(p.exists() for p in clips)


def test_continuous_invalid_windows_become_gaps_with_bounded_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(windowed, '_sleep', lambda _: None)
    calls = []
    def extract(*args):
        path = tmp_path/'retry.flac'
        path.touch()
        return path
    monkeypatch.setattr(windowed, 'extract_clip_flac', extract)
    def invalid(clip, duration, block):
        calls.append(duration)
        return [{'start':duration+18.6,'end':duration+20,'text':'invalid turn'}]
    segs = transcribe_windows(tmp_path/'unused.wav',[(720,1004)],CONTEXT,caller=invalid,strict=[(720,1004)],workers=1)
    assert calls == [284]*3 + [142]*3 + [71]*3 + [71]*3 + [142]*3 + [71]*3 + [71]*3
    assert [(s['start'], s['end'], s['engine']) for s in segs] == [(720, 791, 'gap'), (791, 862, 'gap'),
                                                                 (862, 933, 'gap'), (933, 1004, 'gap')]


def test_parallel_asr_keeps_meeting_context_and_failed_attempt_history(audio, tmp_path, monkeypatch):
    import sqlite3
    import ai_trace
    trace_db = tmp_path / 'parallel-traces.db'
    monkeypatch.setattr(ai_trace, 'TRACE_DB', trace_db)
    monkeypatch.setattr(ai_trace, '_schema_ready', False)
    monkeypatch.setattr(ai_trace, 'enabled', lambda: True)
    monkeypatch.setattr(windowed, '_sleep', lambda _: None)
    seen = []
    def caller(clip, duration, block):
        with ai_trace.span('transcription','gemini.window',provider='gemini',model='fake-cloud') as span:
            span.set(input_tokens=100,output_tokens=20)
            seen.append(duration)
            # One window fails validation after a successful provider request.
            if duration == 30 and seen.count(30) == 1:
                return [{'start':0,'end':duration+18.6,'text':'timestamp overrun'}]
            return good_caller(clip,duration,block)
    with ai_trace.run('parallel-asr',recording_id='meeting-with-retries') as run_id:
        segments = transcribe_windows(audio,[(0,30),(60,100)],CONTEXT,caller=caller,
                                      strict=[(0,30),(60,100)],workers=2)
    assert len(segments) == 2
    with sqlite3.connect(trace_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM spans').fetchall()
    assert rows and all(row['recording_id'] == 'meeting-with-retries' and row['run_id'] == run_id for row in rows)
    attempts = [row for row in rows if row['kind'] == 'asr_attempt']
    assert len(attempts) == 3 and sum(row['status']=='error' for row in attempts) == 1
    failed = next(row for row in attempts if row['status']=='error')
    assert 'outside' in failed['error'] and '0.0-30.0' in failed['name']
    attempt_ids = {row['id'] for row in attempts}
    model_calls = [row for row in rows if row['name']=='gemini.window']
    assert len(model_calls) == 3
    assert all(row['parent_id'] in attempt_ids and row['input_tokens'] == 100 for row in model_calls)


def test_empty_response_reports_candidate_and_block_diagnostics(tmp_path):
    client = FakeClient('')
    def empty(**kwargs):
        return SimpleNamespace(text=None,candidates=[],prompt_feedback=SimpleNamespace(block_reason='SAFETY'),
                               usage_metadata=SimpleNamespace(prompt_token_count=10,candidates_token_count=0,
                                                              thoughts_token_count=20,total_token_count=30))
    client.models.generate_content = empty
    with pytest.raises(gemini_asr.AsrCallError,match='candidates=0, block_reason=SAFETY'):
        gemini_asr.transcribe_window(clip(tmp_path),3,'context',client=client,model='test-model')


def _empty_reply(tmp_path, candidates, block_reason=None):
    client = FakeClient('')
    client.models.generate_content = lambda **kwargs: SimpleNamespace(
        text=None, candidates=candidates, prompt_feedback=SimpleNamespace(block_reason=block_reason))
    with pytest.raises(gemini_asr.AsrCallError) as raised:
        gemini_asr.transcribe_window(clip(tmp_path), 3, 'context', client=client, model='test-model')
    return raised.value


def test_a_blocked_prompt_is_a_refusal(tmp_path):
    assert isinstance(_empty_reply(tmp_path, [], block_reason='PROHIBITED_CONTENT'), gemini_asr.AsrRefusedError)


def test_a_refusal_finish_reason_is_a_refusal(tmp_path):
    refused = _empty_reply(tmp_path, [SimpleNamespace(finish_reason='FinishReason.SAFETY')])
    assert isinstance(refused, gemini_asr.AsrRefusedError)


def test_no_candidates_without_a_block_reason_stays_retryable(tmp_path):
    # An empty candidate list with nothing blocked is a transient hiccup, not a
    # refusal: the ladder should retry it before the Window goes local.
    error = _empty_reply(tmp_path, [])
    assert not isinstance(error, gemini_asr.AsrRefusedError)
    assert 'candidates=0' in str(error)
