"""Live transcript, seam 2: the capture helper's live engine on WAV input
(docs/specs/live-transcript.md, ticket T1). Builds `capture/live-engine` and
`capture/dual-capture` with the repo Makefile and runs them on short fictional
fixtures (tests/fixtures/live). Asserts the stdout lines a caller sees:
well-formed LIVE_* lines per track, times that never go backwards, stable
words never retracted, a fallback engine when the primary model is missing,
and a recorder that survives a missing or crashing engine."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "live"
ENGINE = ROOT / "capture" / "live-engine"
CAPTURE = ROOT / "capture" / "dual-capture"

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"),
                                reason="needs macOS with swiftc")


@pytest.fixture(scope="module", autouse=True)
def built():
    subprocess.run(["make", "capture/live-engine", "capture/dual-capture"], cwd=ROOT, check=True,
                   capture_output=True, timeout=600)


def run(args, timeout=120):
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, parse(proc.stdout)


def parse(stdout):
    lines = []
    for raw in stdout.splitlines():
        kind, _, payload = raw.partition(" ")
        if kind.startswith("LIVE_"):
            lines.append((kind, json.loads(payload)))
    return lines


def words(text):
    import re
    return [re.sub(r"[^\w']", "", w.lower()) for w in text.split()]


def assert_track_contract(lines, track):
    """Per track: well-formed lines, `start` never decreasing, each final at or
    after the previous final's end, partials of a segment only growing, and the
    final keeping every word its last partial showed."""
    texts = [p for k, p in lines if k in ("LIVE_PARTIAL", "LIVE_FINAL") and p["track"] == track]
    assert texts, f"no live text for {track}"
    last_start, last_final_end = 0.0, 0.0
    shown = {}
    for kind, p in [(k, p) for k, p in lines if k in ("LIVE_PARTIAL", "LIVE_FINAL") and p["track"] == track]:
        assert set(p) >= {"track", "seg", "start", "end", "text", "lag_ms"}
        assert isinstance(p["text"], str) and p["text"].strip()
        assert p["end"] >= p["start"] >= 0 and p["lag_ms"] >= 0
        assert p["start"] >= last_start
        last_start = p["start"]
        before = words(shown.get(p["seg"], ""))
        assert words(p["text"])[:len(before)] == before, f"retracted {before} -> {p['text']}"
        shown[p["seg"]] = p["text"]
        if kind == "LIVE_FINAL":
            assert p["start"] >= last_final_end
            last_final_end = p["end"]
            shown[p["seg"]] = "\0final"  # nothing may follow a final in its segment
    return texts


def test_replayed_hypotheses_never_retract_stable_words():
    code, lines = run([str(ENGINE), "--track", "sys", "--replay", str(FIXTURES / "hypotheses.jsonl")])
    assert code == 0
    assert lines[0] == ("LIVE_ENGINE", {"track": "sys", "engine": "replay"})
    assert_track_contract(lines, "sys")
    partials = [p["text"] for k, p in lines if k == "LIVE_PARTIAL"]
    # A trailing half word ("f", "fest") is never shown as stable.
    assert partials[:2] == ["the spring", "the spring festival"]
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    # The engine's final may restyle stable words, not drop them.
    assert finals[0]["text"] == "The Spring Festival, was opened."
    # A final that disagrees keeps the stable words and adds only its remainder.
    assert finals[1]["text"] == "blue lanterns arrived."
    assert finals[1]["start"] >= finals[0]["end"]


@pytest.fixture(scope="module")
def engine_ok(built):
    """Skips on a Mac with no usable on-device engine (macOS < 26 without
    Speech permission, or its speech assets not installed)."""
    code, lines = run([str(ENGINE), "--track", "mic", "--wav", str(FIXTURES / "you.wav")])
    if code != 0 or not any(k == "LIVE_FINAL" for k, _ in lines):
        pytest.skip("no on-device speech engine usable on this Mac")


needs_engine = pytest.mark.usefixtures("engine_ok")


@needs_engine
@pytest.mark.parametrize("track, fixture, expected", [
    ("mic", "you.wav", ["garden", "spring", "festival", "tulips", "tuesday"]),
    ("sys", "them.wav", ["blue", "lanterns", "weather", "tomorrow"]),
])
def test_wav_input_gives_wellformed_lines_per_track(track, fixture, expected):
    code, lines = run([str(ENGINE), "--track", track, "--wav", str(FIXTURES / fixture)])
    assert code == 0
    kind, engine = lines[0]
    assert kind == "LIVE_ENGINE" and engine["track"] == track
    assert_track_contract(lines, track)
    heard = set(words(" ".join(p["text"] for k, p in lines if k == "LIVE_FINAL")))
    assert sum(w in heard for w in expected) >= len(expected) - 1, heard


@needs_engine
def test_falls_back_when_the_primary_model_is_missing(tmp_path):
    code, lines = run([str(ENGINE), "--track", "mic", "--models", str(tmp_path / "none"),
                       "--wav", str(FIXTURES / "you.wav")])
    assert code == 0
    kind, engine = lines[0]
    assert kind == "LIVE_ENGINE"
    assert engine["engine"] != "whisperkit"
    assert engine["fallback_from"] == "whisperkit"
    assert engine["reason"] in {"not_built", "model_missing"}
    assert any(k == "LIVE_FINAL" for k, _ in lines)


def test_forced_engine_that_cannot_run_reports_no_engine(tmp_path):
    code, lines = run([str(ENGINE), "--track", "mic", "--engine", "whisperkit", "--models", str(tmp_path),
                       "--wav", str(FIXTURES / "you.wav")])
    assert code == 3
    assert lines == [("LIVE_ERROR", {"track": "mic", "code": "no_engine"})]


@needs_engine
def test_helper_relays_both_tracks_from_wav_input():
    code, lines = run([str(CAPTURE), "--live-test", str(FIXTURES / "you.wav"), str(FIXTURES / "them.wav"),
                       "--live-engine", str(ENGINE)])
    assert code == 0
    assert {p["track"] for k, p in lines if k == "LIVE_ENGINE"} == {"mic", "sys"}
    assert_track_contract(lines, "mic")
    assert_track_contract(lines, "sys")
    assert lines[-1] == ("LIVE_STATUS", {"state": "stopped", "dropped_s": 0})


def test_helper_survives_a_missing_engine():
    code, lines = run([str(CAPTURE), "--live-test", str(FIXTURES / "you.wav"), "--live-engine", "/nonexistent/live-engine"])
    assert code == 0
    assert ("LIVE_STATUS", {"track": "mic", "state": "paused", "code": "engine_missing"}) in lines
    assert lines[-1][1]["state"] == "stopped"


def test_helper_survives_an_engine_that_crashes(tmp_path):
    crash = tmp_path / "crash.sh"
    crash.write_text("#!/bin/sh\nhead -c 1000 >/dev/null\nexit 9\n")
    crash.chmod(0o755)
    code, lines = run([str(CAPTURE), "--live-test", str(FIXTURES / "you.wav"), str(FIXTURES / "them.wav"),
                       "--live-engine", str(crash)])
    assert code == 0
    paused = {p["track"]: p["code"] for k, p in lines if k == "LIVE_STATUS" and p.get("state") == "paused"}
    assert paused == {"mic": "engine_exit_9", "sys": "engine_exit_9"}


def test_old_helper_grammar_prints_no_live_lines():
    out = subprocess.run([str(CAPTURE), "--list-devices"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0 and "LIVE_" not in out.stdout
