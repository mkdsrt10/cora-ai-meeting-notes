"""A hosted transcript is only trusted if it passes these checks."""
import pytest

from pipeline.asr_validate import WindowInvalid, validate_turns

STRICT = [(0.0, 30.0)]
VAD = [(0.0, 12.0), (14.0, 30.0)]


def turns(*spans):
    return [{"start": a, "end": b, "text": t} for a, b, t in spans]


def ok(raw, duration=30.0, strict=STRICT, vad=VAD):
    return validate_turns(raw, duration, strict, vad)


def test_clean_turns_pass_and_snap_to_speech_boundaries():
    out = ok(turns((0.4, 11.2, "haan toh we can ship it"), (14.6, 29.1, "okay next item")))
    assert out[0]["start"] == 0.0 and out[0]["end"] == 12.0      # snapped within 1.5 s
    assert out[1]["start"] == 14.0 and out[1]["end"] == 30.0


def test_non_list_and_non_numeric_times_are_rejected():
    with pytest.raises(WindowInvalid):
        ok({"turns": []})
    with pytest.raises(WindowInvalid):
        ok([{"start": "soon", "end": 3, "text": "hi"}])


def test_timestamp_outside_the_window_is_rejected():
    with pytest.raises(WindowInvalid):
        ok(turns((0, 5, "fine"), (200, 210, "way past the end")))


def test_runaway_words_are_rejected():
    with pytest.raises(WindowInvalid):
        ok(turns((0, 3, " ".join(f"w{i}" for i in range(200)))))


def test_repetition_loop_is_collapsed():
    out = ok(turns((0, 12, "the the the the the the the the"), (14, 30, "and then we moved on")))
    assert out[0]["text"] == "the"


def test_dropped_speech_is_rejected():
    # only the first 4 s of 30 s of speech has any transcript
    with pytest.raises(WindowInvalid, match="covers only"):
        ok(turns((0, 4, "just the start")))


def test_empty_reply_for_a_window_with_speech_is_rejected_but_silence_is_fine():
    with pytest.raises(WindowInvalid):
        ok([])
    assert ok([], strict=[(0.0, 1.0)]) == []


def test_collapsed_timestamps_are_rejected():
    with pytest.raises(WindowInvalid, match="collapsed"):
        ok(turns(*[(1.0, 1.5, f"turn number {i}") for i in range(6)]))


def test_backwards_timestamps_are_rejected():
    with pytest.raises(WindowInvalid, match="backwards"):
        ok(turns((10, 14, "later first"), (0, 4, "then earlier")))


def test_prompt_echo_is_dropped():
    out = ok(turns((0, 12, "Names and terms that may come up: Priya, Rahul"), (14, 30, "real speech here")),
             strict=[(14.0, 30.0)])
    assert [t["text"] for t in out] == ["real speech here"]


def test_one_long_speech_stretch_covered_by_several_turns_passes():
    # regression: coverage must be the union of turns, not the best single turn
    ok(turns((0, 10, "first part of it"), (10, 20, "the middle part"), (20, 30, "and the last part")),
       strict=[(0.0, 30.0)])
