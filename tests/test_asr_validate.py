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


PAUSED = [(0.0, 12.0), (16.0, 30.0)]  # the strict detector heard a pause, so it isn't saturated


def test_dropped_speech_is_rejected():
    # only the first 4 s of 26 s of speech has any transcript
    with pytest.raises(WindowInvalid, match="covers only"):
        ok(turns((0, 4, "just the start")), strict=PAUSED)


def test_empty_reply_for_a_window_with_speech_is_rejected_but_silence_is_fine():
    with pytest.raises(WindowInvalid):
        ok([], strict=PAUSED)
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


@pytest.mark.parametrize('start,end', [(float('nan'),10),(0,float('inf')),(10,5),(5,5),(0,48)])
def test_invalid_end_and_nonfinite_timestamps_are_retried(start,end):
    with pytest.raises(WindowInvalid):
        ok(turns((start,end,'real speech')))


def test_boundary_tolerance_and_snap_never_exceed_clip():
    result = ok(turns((0,30.5,'real speech')), vad=[(0,30.5)])
    assert result[0]['end'] <= 30


# ---- a Gemini timing slip at the end of a Window is clamped, not rejected ----
# Seen 2026-11-13: "turn ends at 304.4s outside a 302s window" escalated one
# timing slip into splits, retries and finally the local model. The tolerance
# is max(5 s, 3% of the Window): a few seconds of drift over a multi-minute
# clip is a timestamp error, not wrong words (the model only heard this clip).

def test_a_turn_a_few_seconds_past_the_end_of_a_long_window_is_clamped():
    stats = {}
    out = validate_turns(turns((0, 150, "first half " * 10), (150, 304.4, "the last words " * 10)), 302.0,
                         [(0, 302.0)], [(0, 302.0)], stats=stats)
    assert out[-1]["end"] == 302.0
    assert stats == {"clamped": 1}


def test_the_tolerance_is_five_seconds_on_a_short_window():
    out = ok(turns((0, 12, "fine"), (14, 34.9, "a little long")))
    assert out[-1]["end"] == 30.0
    with pytest.raises(WindowInvalid) as caught:
        ok(turns((0, 12, "fine"), (14, 35.5, "too far past")))
    assert caught.value.rule == "outside_window"


def test_forty_seconds_past_a_five_minute_window_is_still_rejected():
    with pytest.raises(WindowInvalid) as caught:
        validate_turns(turns((0, 340.0, "words " * 50)), 300.0, [(0, 300.0)], [(0, 300.0)])
    assert caught.value.rule == "outside_window"


@pytest.mark.parametrize("raw, rule", [
    ({"turns": []}, "malformed"),
    ([{"start": "soon", "end": 3, "text": "hi"}], "timestamps"),
    ([{"start": 0, "end": 3, "text": " ".join(f"w{i}" for i in range(200))}], "runaway"),
    ([], "empty"),
    ([{"start": 0, "end": 2, "text": "only this"}], "coverage"),
])
def test_every_rejection_names_its_rule(raw, rule):
    with pytest.raises(WindowInvalid) as caught:
        ok(raw, strict=[(0.0, 10.0), (15.0, 25.0)])
    assert caught.value.rule == rule
