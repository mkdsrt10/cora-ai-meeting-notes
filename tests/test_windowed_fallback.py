"""A cloud Window the engine keeps rejecting (or refuses) is transcribed on the
Mac instead, or kept as a marked gap when no local model is available; one
bad Window never costs the meeting. No audio and no network: clip extraction
is stubbed, the cloud call and the local transcriber are injected."""
import shutil
import subprocess

import pytest

from pipeline import gemini_asr, windowed
from pipeline.asr_validate import WindowInvalid
from pipeline.context import MeetingContext
from pipeline.windowed import engine_summary, transcribe_windows

_real_extract = windowed.extract_clip_flac
CONTEXT = MeetingContext()
GOOD = (0.0, 30.0)
BAD = (100.0, 140.0)                 # a separate Window: the pause before it is > 8 s
SPEECH = [GOOD, BAD]


@pytest.fixture(autouse=True)
def no_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(windowed, "_sleep", lambda _: None)
    monkeypatch.setattr(windowed, "_self_name", lambda: "")

    def extract(_, start, end):
        path = tmp_path / f"clip-{start:.0f}-{end:.0f}.flac"
        path.touch()
        return path
    monkeypatch.setattr(windowed, "extract_clip_flac", extract)


INVALID = WindowInvalid("transcript covers only 10% of the speech")


def cloud(reject=40.0, error=INVALID, calls=None):
    """Answers every Window except those `reject` seconds long."""
    def call(clip, duration, block):
        if calls is not None:
            calls.append(duration)
        if duration == reject:
            raise error
        return [{"start": 0.0, "end": duration, "text": f"cloud words for {duration:.0f} seconds"}]
    return call


def local(calls=None):
    def fallback(audio, start, end):
        if calls is not None:
            calls.append((start, end))
        return [{"start": start + 1.0, "end": end - 1.0, "text": "local words"}]
    return fallback


def run(**kwargs):
    kwargs.setdefault("caller", cloud())
    return transcribe_windows("unused.wav", SPEECH, CONTEXT, strict=SPEECH, workers=1, provider="gemini", **kwargs)


def test_rejected_window_is_transcribed_locally_at_its_absolute_offset():
    asked = []
    segments = run(fallback=local(asked))
    assert asked == [BAD]
    assert segments == [
        {"start": 0.0, "end": 30.0, "text": "cloud words for 30 seconds", "engine": "gemini"},
        {"start": 101.0, "end": 139.0, "text": "local words", "engine": "local",
         "reason": "the cloud engine kept rejecting this stretch"},
    ]


def test_a_window_that_fails_at_every_split_depth_goes_local_piece_by_piece():
    asked = []
    long_window = [(0.0, 120.0)]
    segments = transcribe_windows("unused.wav", long_window, CONTEXT, strict=long_window, workers=1,
                                  caller=_always(WindowInvalid("bad")),
                                  fallback=local(asked), provider="gemini")
    assert asked == [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0), (90.0, 120.0)]
    assert {s["engine"] for s in segments} == {"local"}


def _always(error):
    def call(clip, duration, block):
        raise error
    return call


def test_provider_refusal_goes_local_without_retrying_or_splitting():
    durations, asked = [], []
    refusal = gemini_asr.AsrRefusedError("Gemini returned no text (block_reason=PROHIBITED_CONTENT)")
    segments = run(caller=cloud(error=refusal, calls=durations), fallback=local(asked))
    assert durations.count(40.0) == 1 and asked == [BAD]
    local_seg = next(s for s in segments if s["engine"] == "local")
    assert local_seg["reason"] == "the cloud engine refused this stretch"


def test_transient_call_errors_are_still_retried_before_falling_back():
    durations = []
    run(caller=cloud(error=gemini_asr.AsrCallError("429"), calls=durations), fallback=local())
    assert durations.count(40.0) == 3


def test_without_a_local_model_the_window_becomes_a_marked_gap():
    failed = []
    segments = run(fallback=None, on_window_failed=lambda *a: failed.append(a))
    gap = {"start": 100.0, "end": 140.0, "text": "", "engine": "gap",
           "reason": "the cloud engine kept rejecting this stretch; no local model is installed"}
    assert segments[-1] == gap
    assert [s["engine"] for s in segments] == ["gemini", "gap"]
    assert failed == [(100.0, 140.0, gap["reason"])]


def test_a_failing_local_transcriber_leaves_a_gap_and_the_run_continues():
    def broken(audio, start, end):
        raise RuntimeError("Metal device lost")
    segments = run(fallback=broken)
    assert segments[-1]["engine"] == "gap"
    assert segments[-1]["reason"] == "the cloud engine kept rejecting this stretch; local transcription failed"


def test_on_window_failed_reports_locally_transcribed_windows_too():
    failed = []
    run(fallback=local(), on_window_failed=lambda *a: failed.append(a))
    assert failed == [(100.0, 140.0, "the cloud engine kept rejecting this stretch")]


def test_auth_errors_still_fail_the_run():
    from pipeline.errors import ProviderAuthError
    with pytest.raises(ProviderAuthError):
        run(caller=_always(ProviderAuthError("gemini")), fallback=local())


def test_engine_summary_counts_local_and_gap_seconds():
    segments = [
        {"start": 0.0, "end": 30.0, "text": "a", "engine": "gemini"},
        {"start": 101.0, "end": 110.0, "text": "b", "engine": "local", "reason": "refused"},
        {"start": 112.0, "end": 139.0, "text": "c", "engine": "local", "reason": "refused"},
        {"start": 150.0, "end": 160.0, "text": "d", "engine": "gemini"},
        {"start": 200.0, "end": 260.0, "text": "", "engine": "gap", "reason": "rejected; no local model"},
    ]
    assert engine_summary(segments) == {
        "local_s": 38.0,
        "gap_s": 60.0,
        "windows": [{"start": 101.0, "end": 139.0, "engine": "local", "reason": "refused"},
                    {"start": 200.0, "end": 260.0, "engine": "gap", "reason": "rejected; no local model"}],
    }


def test_a_clean_run_has_an_empty_summary():
    segments = run(caller=cloud(reject=None), fallback=local())
    assert {s["engine"] for s in segments} == {"gemini"}
    assert engine_summary(segments) == {"local_s": 0.0, "gap_s": 0.0, "windows": []}


# ---- the hosted Transcriber wires the local fallback in ---------------------------

ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")


@pytest.fixture
def two_stretches(tmp_path):
    """30 s of tone, 20 s of silence, 40 s of tone: two cloud Windows."""
    path = tmp_path / "meeting.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=30",
                    "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=20",
                    "-f", "lavfi", "-i", "sine=frequency=330:duration=40",
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ac", "1", "-ar", "16000", str(path)], check=True)
    return path


def _hosted(local_for):
    from pipeline.transcriber import Transcriber, Windowed

    def call(clip, duration, block):
        if duration > 35:
            raise WindowInvalid("transcript covers only 10% of the speech")
        return [{"start": 0.0, "end": duration, "text": "cloud words"}]
    return Transcriber(Windowed(call, engine="gemini", local=local_for), engine="gemini", model="fake")


@ffmpeg
def test_hosted_transcriber_fills_a_rejected_window_from_the_local_model(two_stretches, monkeypatch):
    monkeypatch.setattr(windowed, "extract_clip_flac", _real_extract)
    asked = []
    segments, _, _ = _hosted(lambda speech, hints: local(asked)).transcribe(two_stretches)
    assert len(asked) == 1
    assert asked[0][0] == pytest.approx(50, abs=1.5) and asked[0][1] == pytest.approx(90, abs=1.5)
    assert [(s["engine"], s["text"]) for s in segments] == [("gemini", "cloud words"), ("local", "local words")]


@ffmpeg
def test_hosted_transcriber_without_a_local_model_keeps_the_gap(two_stretches, monkeypatch):
    monkeypatch.setattr(windowed, "extract_clip_flac", _real_extract)
    segments, _, _ = _hosted(lambda speech, hints: None).transcribe(two_stretches)
    assert [s["engine"] for s in segments] == ["gemini", "gap"]
    assert segments[1]["text"] == "" and segments[1]["reason"].endswith("no local model is installed")


def test_no_local_fallback_when_the_whisper_model_is_not_downloaded(monkeypatch):
    from pipeline import config, transcriber
    monkeypatch.setattr(config, "resolve_whisper_model", lambda: "mlx-community/whisper-large-v3-turbo")
    monkeypatch.setattr(config, "model_ready", lambda model_id: False)
    assert transcriber.local_fallback([(0.0, 10.0)], {"prompt": "", "prompt_for": None}) is None


def test_local_fallback_transcribes_only_the_speech_inside_the_window(monkeypatch):
    from pipeline import config, transcribe, transcriber
    monkeypatch.setattr(config, "resolve_whisper_model", lambda: "mlx-community/whisper-large-v3-turbo")
    monkeypatch.setattr(config, "model_ready", lambda model_id: True)
    monkeypatch.setattr(transcriber, "_mlx_installed", lambda: True)
    seen = []

    def chunks(audio, speech, prompt, prompt_for):        # stands in for MLX Whisper
        seen.append((audio, speech, prompt))
        return [{"start": a, "end": b, "text": "heard"} for a, b in speech]
    monkeypatch.setattr(transcribe, "_transcribe_chunks", chunks)
    speech = [(0.0, 30.0), (95.0, 120.0), (125.0, 150.0)]
    fallback = transcriber.local_fallback(speech, {"prompt": "Priya", "prompt_for": None})
    assert fallback("mix.wav", 100.0, 140.0) == [{"start": 100.0, "end": 120.0, "text": "heard"},
                                                 {"start": 125.0, "end": 140.0, "text": "heard"}]
    assert seen == [("mix.wav", [(100.0, 120.0), (125.0, 140.0)], "Priya")]


# ---- the pipeline records what was not transcribed in the cloud ------------------

def _process(name, segments, fake_text, fake_transcriber, monkeypatch):
    import json
    import db
    import paths
    from pipeline import runner
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    db.init_db()
    db.delete_recording(name)
    db.create_recording(name, str(folder), name, "2026-11-10T15:50:00", 260.0, 0, {"recording_name": name})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "Participant")
    fake_transcriber.segments = segments
    fake_text.reply = json.dumps(dict(title="Kickoff", overview="Talked.", action_items_md="- None noted.",
                                      decisions_md="- None noted.", timeline_md="- Intro",
                                      open_questions_md="- None noted.", key_entities_md="- None"))
    result = runner.process_recording_local(folder, {"mode": "cloud", "provider": "openai", "transcription": "gemini"})
    mine = [n for n in db.get_notifications() if n["recording_id"] == name]
    return result, db.get_recording_data(name, "metadata") or {}, mine


MIXED = [
    {"start": 0.0, "end": 30.0, "text": "cloud words about the launch", "engine": "gemini"},
    {"start": 100.0, "end": 190.0, "text": "local words about the budget", "engine": "local",
     "reason": "the cloud engine refused this stretch"},
    {"start": 200.0, "end": 260.0, "text": "", "engine": "gap",
     "reason": "the cloud engine kept rejecting this stretch; no local model is installed"},
]


def test_pipeline_stores_the_engine_summary_and_posts_one_notification(fake_text, fake_transcriber, monkeypatch):
    _, metadata, notes = _process("engines-mixed", MIXED, fake_text, fake_transcriber, monkeypatch)
    assert metadata["transcription_engines"] == {
        "local_s": 90.0, "gap_s": 60.0,
        "windows": [{"start": 100.0, "end": 190.0, "engine": "local", "reason": "the cloud engine refused this stretch"},
                    {"start": 200.0, "end": 260.0, "engine": "gap",
                     "reason": "the cloud engine kept rejecting this stretch; no local model is installed"}]}
    assert len(notes) == 1
    assert notes[0]["level"] == "warning"
    assert "2 min transcribed on this Mac" in notes[0]["body"]
    assert "1 min could not be transcribed" in notes[0]["body"]
    assert "the cloud engine refused this stretch" in notes[0]["body"]
    assert "no local model is installed" in notes[0]["body"]


def test_a_fully_cloud_transcribed_recording_posts_no_notification(fake_text, fake_transcriber, monkeypatch):
    _, metadata, notes = _process("engines-clean", MIXED[:1], fake_text, fake_transcriber, monkeypatch)
    assert metadata["transcription_engines"] == {"local_s": 0.0, "gap_s": 0.0, "windows": []}
    assert notes == []


def test_transcript_segments_keep_their_engine_marks(fake_text, fake_transcriber, monkeypatch):
    result, _, _ = _process("engines-marks", MIXED, fake_text, fake_transcriber, monkeypatch)
    marks = [(s.get("engine"), s.get("reason"), s["text"]) for s in result["diarization"]["segments"]]
    assert marks == [(None, None, "cloud words about the launch"),
                     ("local", "the cloud engine refused this stretch", "local words about the budget"),
                     ("gap", "the cloud engine kept rejecting this stretch; no local model is installed", "")]
    assert all(p["name"] for p in result["diarization"]["speakers"])    # a gap is nobody speaking
