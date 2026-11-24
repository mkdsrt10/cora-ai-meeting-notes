"""python/live_whisper.py: the on-device Whisper live engine speaks the same
LIVE_* contract as the other engines (no model here: a scripted recognizer)."""
import numpy as np

import live_whisper as lw

SPEECH = (0.1 * np.sin(np.linspace(0, 400 * np.pi, lw.CHUNK))).astype(np.float32)
SILENCE = np.zeros(lw.CHUNK, dtype=np.float32)


def _chunks(*spans):
    """spans: ("s"|"q", seconds) -> 100 ms chunks of speech or quiet."""
    for kind, seconds in spans:
        for _ in range(int(round(seconds * 10))):
            yield SPEECH if kind == "s" else SILENCE


def _run(spans, hypotheses):
    lines, calls = [], []

    def recognize(audio):
        calls.append(len(audio) / lw.SAMPLE_RATE)
        return hypotheses(len(calls), len(audio) / lw.SAMPLE_RATE)

    # Fed as if each chunk arrived on time (run() skips partials while behind).
    engine = lw.WhisperLive("mic", recognize, emit=lambda kind, payload: lines.append((kind, payload)))
    for chunk in _chunks(*spans):
        engine.feed(chunk)
    engine.finish()
    return lines, calls


def _growing(_call, seconds):
    words = "aaj hum release plan dekhte hain phir Rahul demo karega".split()
    return " ".join(words[:max(1, int(seconds * 2))])


def test_speech_then_silence_gives_growing_partials_and_one_final():
    lines, _ = _run([("q", 1), ("s", 4), ("q", 1)], _growing)
    partials = [p for k, p in lines if k == "LIVE_PARTIAL"]
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    assert partials and len(finals) == 1
    texts = [p["text"] for p in partials]
    assert all(b.startswith(a) for a, b in zip(texts, texts[1:]))     # only grows
    assert finals[0]["text"].startswith(texts[-1])
    assert 0.6 <= finals[0]["start"] <= 1.0 and 4.6 <= finals[0]["end"] <= 5.1
    assert all(set(p) == {"track", "seg", "start", "end", "text", "lag_ms"} for p in partials + finals)


def test_stable_words_are_never_retracted_when_the_model_changes_its_mind():
    flip = ["haan theek hai", "haan theek hai kal", "haan thik hai kal milte", "haan theek hai kal milte hain"]
    lines, _ = _run([("s", 5), ("q", 1)], lambda call, _s: flip[min(call, len(flip)) - 1])
    stable = [p["text"] for k, p in lines if k == "LIVE_PARTIAL"]
    final = next(p["text"] for k, p in lines if k == "LIVE_FINAL")
    for earlier, later in zip(stable, stable[1:] + [final]):
        assert later.startswith(earlier)


def test_long_speech_is_cut_into_ordered_segments():
    lines, calls = _run([("s", 30), ("q", 1)], lambda _c, s: f"segment of {int(s)} seconds")
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    assert len(finals) >= 3
    assert [f["seg"] for f in finals] == list(range(len(finals)))
    for a, b in zip(finals, finals[1:]):
        assert b["start"] >= a["end"]
    assert max(calls) <= lw.MAX_SEGMENT_S + lw.PRE_ROLL_S + 0.11


def test_blips_and_silence_produce_nothing():
    lines, calls = _run([("q", 2), ("s", 0.1), ("q", 2)], lambda *_: "noise")
    assert not lines and not calls


def test_run_announces_the_engine_and_catches_up_instead_of_decoding_every_step():
    lines, calls = [], []
    code = lw.run("mic", _chunks(("s", 4), ("q", 1)), lambda: lambda audio: calls.append(1) or "kal milte hain",
                  "fake/model", emit=lambda k, p: lines.append((k, p)))
    assert code == 0
    assert lines[0] == ("LIVE_ENGINE", {"track": "mic", "engine": "mlx_whisper", "model": "fake/model"})
    assert [p["text"] for k, p in lines if k == "LIVE_FINAL"] == ["kal milte hain"]


def test_a_model_that_is_not_downloaded_pauses_captions_without_downloading():
    lines = []

    def missing():
        raise FileNotFoundError("not/here")

    code = lw.run("sys", iter(()), missing, "not/here", emit=lambda k, p: lines.append((k, p)))
    assert code == 3 and lines == [("LIVE_ERROR", {"track": "sys", "code": "model_missing"})]


def test_audio_that_arrives_while_the_model_loads_is_kept_not_dropped():
    import threading
    loaded = threading.Event()
    seen = []

    def slow_factory():
        loaded.wait(0.5)          # the model takes a while; the reader keeps reading meanwhile
        return lambda audio: seen.append(len(audio)) or "pehle se bol raha hoon"

    consumed = []

    def chunks():
        for chunk in _chunks(("s", 2), ("q", 1)):
            consumed.append(1)
            yield chunk

    lines = []
    code = lw.run("sys", chunks(), slow_factory, "fake/model", emit=lambda k, p: lines.append((k, p)))
    assert code == 0 and len(consumed) == 30
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    assert [f["text"] for f in finals] == ["pehle se bol raha hoon"] and finals[0]["start"] == 0.0


def test_a_quiet_remote_speaker_still_opens_a_segment():
    quiet = (0.006 * np.sin(np.linspace(0, 400 * np.pi, lw.CHUNK))).astype(np.float32)   # RMS ~0.004
    lines = []
    engine = lw.WhisperLive("sys", lambda audio: "haan ji", emit=lambda k, p: lines.append((k, p)))
    for chunk in [quiet] * 10 + [SILENCE] * 10:
        engine.feed(chunk)
    engine.finish()
    assert [p["text"] for k, p in lines if k == "LIVE_FINAL"] == ["haan ji"]


def test_no_partial_until_the_segment_has_enough_audio():
    """A partial on about a second of quiet audio is where Whisper invents text;
    the stabilizer would then lock it into the final."""
    lines, calls = _run([("s", lw.MIN_PARTIAL_S - 1.0), ("q", 1)], lambda *_: "haan theek hai")   # + pre-roll + closing silence < MIN_PARTIAL_S
    assert [k for k, _ in lines] == ["LIVE_FINAL"]
    assert len(calls) == 1
    lines, _ = _run([("s", lw.MIN_PARTIAL_S + 1.5), ("q", 1)], _growing)
    partials = [p for k, p in lines if k == "LIVE_PARTIAL"]
    assert partials and all(p["end"] - p["start"] >= lw.MIN_PARTIAL_S - lw.PRE_ROLL_S for p in partials)


def test_segments_whisper_scores_as_junk_are_dropped():
    # Nov 2026 call: real speech scored -0.16 .. -0.81; junk NaN, ~-2, or a loop the ladder kept.
    assert lw.keep_segment({"avg_logprob": -0.81, "compression_ratio": 1.4})
    assert not lw.keep_segment({"avg_logprob": float("nan"), "compression_ratio": 1.0})
    assert not lw.keep_segment({"avg_logprob": -2.06, "compression_ratio": 1.0})
    assert not lw.keep_segment({"avg_logprob": -0.44, "compression_ratio": 18.8})
    assert not lw.keep_segment({})


def test_stray_punctuation_runs_are_tidied_away():
    assert lw.tidy("So, I'm not sure. . !") == "So, I'm not sure."
    assert lw.tidy("Okay. . ! . !") == "Okay."
    assert lw.tidy("Yes, Rob. So, I will review it.") == "Yes, Rob. So, I will review it."
    assert lw.tidy(" . !") == ""
