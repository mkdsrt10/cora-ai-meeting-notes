"""Speech detector: speech is found relative to each recording's own noise floor.

Synthetic audio: a white-noise bed at a known RMS level with loud tone bursts.
Speech stretches must start and end at the bursts' edges (within padding), not
cover the whole file because the bed is louder than a fixed threshold."""
import json
import subprocess

import pytest

from pipeline import audio

BURSTS = [(2.0, 4.0), (8.0, 10.0), (14.0, 16.0)]
DURATION = 18.0
PAD = 0.3


def make_recording(path, noise_rms_db: float):
    # Uniform white noise of amplitude a has RMS a/sqrt(3).
    amplitude = 10 ** (noise_rms_db / 20) * 3 ** 0.5
    # sine's own amplitude is 1/8; x2.4 makes the bursts 0.3 peak (about -10.5 dBFS).
    gate = "+".join(f"between(t,{s},{e})" for s, e in BURSTS)
    graph = (
        f"anoisesrc=color=white:amplitude={amplitude:.5f}:sample_rate=16000:duration={DURATION}:seed=7[n];"
        f"sine=frequency=440:sample_rate=16000:duration={DURATION},"
        f"volume='if({gate},2.4,0)':eval=frame[t];"
        "[n][t]amix=inputs=2:normalize=0[a]"
    )
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-filter_complex", graph, "-map", "[a]",
                    "-ac", "1", "-ar", "16000", str(path)], check=True)
    return path


@pytest.fixture(autouse=True)
def no_overrides(monkeypatch):
    monkeypatch.setattr(audio, "_config", lambda: {})


def assert_gaps_at_burst_edges(speech):
    assert len(speech) == len(BURSTS), speech
    for (s, e), (bs, be) in zip(speech, BURSTS):
        assert s == pytest.approx(bs - PAD, abs=0.15)
        assert e == pytest.approx(be + PAD, abs=0.15)


@pytest.mark.parametrize("noise_rms_db", [-50.0, -40.0])
def test_speech_is_found_only_at_the_bursts_on_a_noise_bed(tmp_path, noise_rms_db):
    rec = make_recording(tmp_path / "rec.wav", noise_rms_db)
    assert_gaps_at_burst_edges(audio.find_speech_segments(rec, pad=PAD))


def test_continuous_speech_with_no_quiet_frames_stays_one_stretch(tmp_path):
    # A tone end to end at about -30 dBFS, louder at the bursts: there is no
    # quiet frame, so the measured "floor" is the speech itself and floor +
    # margin would cut the quieter speech out between the bursts. A floor above
    # -45 dB is clamped, which keeps the threshold under all of it.
    rec = tmp_path / "tone.wav"
    gate = "+".join(f"between(t,{s},{e})" for s, e in BURSTS)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:sample_rate=16000:duration={DURATION}",
                    "-af", f"volume='if({gate},2.4,0.3)':eval=frame", "-ac", "1", str(rec)], check=True)
    assert audio.measure_noise_floor_db(rec) > -45.0
    assert audio.find_speech_segments(rec, pad=PAD) == [(0.0, pytest.approx(DURATION, abs=0.05))]


def test_configured_threshold_overrides_the_relative_one(tmp_path, monkeypatch):
    rec = make_recording(tmp_path / "rec.wav", -40.0)
    # A hand-tuned -55 dB sits under the -40 dB bed, so nothing reads as silence.
    monkeypatch.setattr(audio, "_config", lambda: {"silence_threshold_db": "-55dB"})
    assert audio.find_speech_segments(rec, pad=PAD) == [(0.0, pytest.approx(DURATION, abs=0.05))]


@pytest.mark.parametrize("value", ["", "-50dB"])
def test_empty_or_legacy_example_override_means_relative(tmp_path, monkeypatch, value):
    # "-50dB" was the value config.example.json shipped (and copied into every
    # data dir), so it is not a deliberate override.
    rec = make_recording(tmp_path / "rec.wav", -40.0)
    monkeypatch.setattr(audio, "_config", lambda: {"silence_threshold_db": value})
    assert_gaps_at_burst_edges(audio.find_speech_segments(rec, pad=PAD))


def test_example_config_does_not_pin_a_threshold():
    from paths import CONFIG_EXAMPLE
    example = json.loads(CONFIG_EXAMPLE.read_text())
    assert "silence_threshold_db" not in example
    assert "strict_silence_threshold_db" not in example


def test_strict_detector_uses_its_own_margin_and_override(tmp_path, monkeypatch):
    rec = make_recording(tmp_path / "rec.wav", -40.0)
    strict = dict(margin_db=audio.STRICT_MARGIN_DB, override_key="strict_silence_threshold_db", pad=PAD)
    assert_gaps_at_burst_edges(audio.find_speech_segments(rec, **strict))
    monkeypatch.setattr(audio, "_config", lambda: {"silence_threshold_db": "-55dB"})
    assert_gaps_at_burst_edges(audio.find_speech_segments(rec, **strict))  # main override does not leak in
    monkeypatch.setattr(audio, "_config", lambda: {"strict_silence_threshold_db": "-55dB"})
    assert audio.find_speech_segments(rec, **strict) == [(0.0, pytest.approx(DURATION, abs=0.05))]


def test_noise_floor_is_measured_from_the_recording(tmp_path):
    assert audio.measure_noise_floor_db(make_recording(tmp_path / "a.wav", -40.0)) == pytest.approx(-40.0, abs=1.0)
    assert audio.measure_noise_floor_db(make_recording(tmp_path / "b.wav", -30.0)) == pytest.approx(-30.0, abs=1.0)


def test_threshold_never_goes_above_minus_20_db():
    assert audio.relative_threshold_db(-52.0, 10.0) == "-42dB"
    assert audio.relative_threshold_db(-52.0, 18.0) == "-34dB"
    assert audio.relative_threshold_db(-60.0, 50.0) == "-20dB"


def test_a_floor_above_minus_45_db_is_clamped_before_the_margin():
    assert audio.relative_threshold_db(-42.0, 10.0) == "-35dB"
    assert audio.relative_threshold_db(-25.0, 10.0) == "-35dB"
    assert audio.relative_threshold_db(-10.0, 18.0) == "-27dB"


def count_floor_passes(monkeypatch):
    calls = []
    real_run = audio.subprocess.run

    def run(cmd, *args, **kwargs):
        if any("astats" in str(part) for part in cmd):
            calls.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(audio.subprocess, "run", run)
    return calls


def test_main_and_strict_detectors_share_one_floor_measurement(tmp_path, monkeypatch):
    rec = make_recording(tmp_path / "rec.wav", -40.0)
    passes = count_floor_passes(monkeypatch)
    audio.find_speech_segments(rec, pad=PAD)
    audio.find_speech_segments(rec, margin_db=audio.STRICT_MARGIN_DB,
                               override_key="strict_silence_threshold_db", pad=PAD)
    assert len(passes) == 1


def test_a_rewritten_recording_is_measured_again(tmp_path, monkeypatch):
    rec = make_recording(tmp_path / "rec.wav", -40.0)
    passes = count_floor_passes(monkeypatch)
    assert audio.measure_noise_floor_db(rec) == pytest.approx(-40.0, abs=1.0)
    make_recording(rec, -50.0)
    assert audio.measure_noise_floor_db(rec) == pytest.approx(-50.0, abs=1.0)
    assert len(passes) == 2
