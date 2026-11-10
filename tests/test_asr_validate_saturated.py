"""validate_turns when the strict speech detector is saturated: a noisy mic
can make it report one unbroken stretch of "speech" over a long Window. That
is no evidence of continuous speech, so coverage is not held against the
transcript; every other rule still applies."""
import pytest

from pipeline.asr_validate import WindowInvalid, validate_turns

WINDOW = 65.0
SATURATED = [(0.0, WINDOW)]                         # strict found no silence at all
QUIET_HALF = [(0.0, 30.0), (52.0, WINDOW)]          # a 22 s gap: the detector heard silence
FIRST_HALF_ONLY = [{"start": 0.0, "end": 28.0, "text": "we talked through the plan for the launch week"}]


def test_saturated_detector_does_not_fail_coverage():
    turns = validate_turns(FIRST_HALF_ONLY, WINDOW, SATURATED, SATURATED)
    assert [t["text"] for t in turns] == [FIRST_HALF_ONLY[0]["text"]]


def test_saturated_detector_with_tiny_gaps_is_still_saturated():
    nearly = [(0.0, 20.0), (20.5, 40.0), (40.4, WINDOW)]   # 98.6 % of the Window is "speech"
    assert validate_turns(FIRST_HALF_ONLY, WINDOW, nearly, nearly)


def test_a_few_seconds_of_silence_keeps_the_coverage_check():
    paused = [(0.0, 30.0), (34.0, WINDOW)]                 # one 4 s pause: the detector works
    with pytest.raises(WindowInvalid, match="covers only"):
        validate_turns(FIRST_HALF_ONLY, WINDOW, paused, paused)


def test_saturated_detector_allows_an_empty_transcript():
    assert validate_turns([], WINDOW, SATURATED, SATURATED) == []


def test_real_silence_keeps_the_coverage_check():
    late_only = [{"start": 53.0, "end": 64.0, "text": "and that is all from me today"}]
    with pytest.raises(WindowInvalid, match="covers only"):
        validate_turns(late_only, WINDOW, QUIET_HALF, QUIET_HALF)


def test_real_silence_keeps_the_no_transcript_check():
    with pytest.raises(WindowInvalid, match="no transcript"):
        validate_turns([], WINDOW, QUIET_HALF, QUIET_HALF)


def test_short_window_is_never_treated_as_saturated():
    short = [(0.0, 15.0)]
    with pytest.raises(WindowInvalid, match="no transcript"):
        validate_turns([], 15.0, short, short)


def test_saturated_detector_still_rejects_timestamps_outside_the_clip():
    with pytest.raises(WindowInvalid, match="outside"):
        validate_turns([{"start": 0.0, "end": WINDOW + 18.6, "text": "overrun"}], WINDOW, SATURATED, SATURATED)


def test_saturated_detector_still_rejects_runaway_output():
    with pytest.raises(WindowInvalid, match="runaway"):
        validate_turns([{"start": 0.0, "end": 1.0, "text": " ".join(f"word{i}" for i in range(40))}], WINDOW, SATURATED, SATURATED)
