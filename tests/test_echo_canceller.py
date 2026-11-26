"""Live mic echo canceller in the capture helper (`dual-capture --aec-test`).

Synthetic 16 kHz signals only: a "far end" of noise bursts played into the room
(the echo is a delayed, attenuated, smeared copy on the mic) plus "near end"
tone bursts the user says, some alone and some over the far end. Asserts the
echo is cut, the user's own sound is kept, the bulk delay is found, and a mic
block zeroed by the device's own gate stays zero."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "capture" / "dual-capture"
SR = 16000

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                                reason="needs macOS with swiftc")


@pytest.fixture(scope="module", autouse=True)
def built():
    subprocess.run(["make", "capture/dual-capture"], cwd=ROOT, check=True, capture_output=True, timeout=600)


def write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def read_wav(path):
    pcm = path.with_suffix(".i16.wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{SR}", str(path), str(pcm)], check=True)
    with wave.open(str(pcm)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float32) / 32767


def run_aec(tmp_path, mic, far):
    write_wav(tmp_path / "mic.wav", mic)
    write_wav(tmp_path / "sys.wav", far)
    proc = subprocess.run([str(CAPTURE), "--aec-test", str(tmp_path / "mic.wav"), str(tmp_path / "sys.wav"),
                           str(tmp_path / "out.wav")], capture_output=True, text=True, timeout=120, check=True)
    stats = json.loads(next(line for line in proc.stdout.splitlines() if line.startswith("AEC_STATS ")).split(" ", 1)[1])
    return read_wav(tmp_path / "out.wav"), stats


def rms(x):
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def span(a, b):
    return slice(int(a * SR), int(b * SR))


def scene(seconds=24, delay_s=0.2, seed=1):
    """Far end talks in 1.5 s bursts with 0.5 s gaps; the user says a tone alone
    at 13.0-13.4 s (inside a far-end gap) and over the far end at 18.2-19.0 s."""
    rng = np.random.default_rng(seed)
    t = np.arange(seconds * SR) / SR
    far = rng.normal(0, 0.1, len(t)).astype(np.float32)
    far *= ((t % 2.0) < 1.5)                                   # bursts
    path = np.zeros(int(0.03 * SR), dtype=np.float32)          # room: 30 ms decaying tail
    path[0] = 0.05
    path[1:] = 0.02 * np.exp(-np.arange(1, len(path)) / 60) * rng.choice([-1, 1], len(path) - 1)
    lag = int(delay_s * SR)
    echo = np.convolve(np.concatenate([np.zeros(lag, np.float32), far])[:len(t)], path)[:len(t)].astype(np.float32)
    near = np.zeros(len(t), dtype=np.float32)
    for a, b in [(13.0, 13.4), (18.2, 19.0)]:
        near[span(a, b)] = 0.01 * np.sin(2 * np.pi * 220 * t[span(a, b)])
    return far, echo, near


def test_echo_is_cut_and_the_users_voice_kept(tmp_path):
    far, echo, near = scene()
    out, stats = run_aec(tmp_path, echo + near, far)
    assert len(out) == len(far)
    # Echo-only stretches after the canceller has settled (far bursts from 8 s on, away from the user).
    echo_only = np.concatenate([out[span(s + 0.3, s + 1.5)] for s in (8, 10, 14, 16, 20, 22)])
    echo_in = np.concatenate([echo[span(s + 0.3, s + 1.5)] for s in (8, 10, 14, 16, 20, 22)])
    assert 20 * np.log10(rms(echo_only) / rms(echo_in)) < -12
    # The user alone: untouched. Over the far end: still clearly there.
    assert abs(20 * np.log10(rms(out[span(13.05, 13.35)]) / rms(near[span(13.05, 13.35)]))) < 0.5
    residual = out[span(18.3, 18.9)] - near[span(18.3, 18.9)]
    assert rms(residual) < 0.5 * rms(near[span(18.3, 18.9)])
    assert abs(stats["echo_delay_ms"] - 200) <= 40
    assert stats["echo_reduction_db"] <= -3        # whole run, including the seconds before it converges
    assert stats["echo_far_s"] > 10


def test_without_a_far_end_the_mic_passes_unchanged(tmp_path):
    _, _, near = scene()
    out, stats = run_aec(tmp_path, near, np.zeros_like(near))
    assert np.max(np.abs(out - near)) < 2e-4
    assert stats["echo_far_s"] == 0
    assert stats["echo_delay_ms"] == -1


def test_a_gated_mic_stays_silent_while_the_far_end_plays(tmp_path):
    far, echo, _ = scene()
    mic = echo.copy()
    mic[span(9, 11)] = 0.0          # the device's own noise gate closed
    out, _ = run_aec(tmp_path, mic, far)
    assert np.max(np.abs(out[span(9.05, 10.95)])) == 0.0
