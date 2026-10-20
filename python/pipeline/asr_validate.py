"""Checks on a hosted model's transcript of one window.

A hosted recognizer can fail quietly: drop a stretch of speech, return
timestamps that are all zero, ramble on silence, or echo the prompt. Each
check here either raises WindowInvalid (retry, then split, then fail the
run) or snaps the timestamps onto the local speech detector's boundaries.
Times are seconds relative to the window start unless stated otherwise.
"""
from __future__ import annotations

from typing import Any

from .transcribe import collapse_repetition_loops

MAX_WORDS_PER_SECOND = 8.0
MIN_COVERAGE = 0.6          # share of strict-VAD speech some turn must overlap
COVERAGE_MIN_SPEECH_S = 5.0  # below this much speech the check isn't meaningful
SNAP_S = 1.5
LEAK_MARKERS = ("names and terms that may come up", "meeting title:", "attendees:")


class WindowInvalid(Exception):
    """The model's answer for this window can't be trusted."""


def _covered(stretch: tuple[float, float], turns: list[dict[str, Any]]) -> float:
    """Seconds of this speech stretch that some turn (padded 1 s) accounts for: the union, not the best single turn."""
    spans = sorted((max(stretch[0], t["start"] - 1.0), min(stretch[1], t["end"] + 1.0)) for t in turns)
    total, cursor = 0.0, stretch[0]
    for a, b in spans:
        if b <= a:
            continue
        a = max(a, cursor)
        if b > a:
            total += b - a
            cursor = b
    return total


def _snap(value: float, edges: list[float]) -> float:
    if not edges:
        return value
    nearest = min(edges, key=lambda e: abs(e - value))
    return nearest if abs(nearest - value) <= SNAP_S else value


def validate_turns(raw: Any, duration: float, strict: list[tuple[float, float]],
                   vad: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """raw: the parsed model reply (a list of {start,end,text}). strict/vad:
    speech stretches relative to the window start. Returns clean turns."""
    if not isinstance(raw, list):
        raise WindowInvalid("reply is not a list of turns")
    turns: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise WindowInvalid("turn is not an object")
        text = collapse_repetition_loops(str(item.get("text", "")).strip())
        if not text or any(m in text.lower() for m in LEAK_MARKERS):
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            raise WindowInvalid("turn has no numeric start/end")
        if start < -1.0 or start > duration + 1.0:
            raise WindowInvalid(f"turn starts at {start:.1f}s outside a {duration:.0f}s window")
        start = min(max(start, 0.0), duration)
        end = min(max(end, start), duration)
        words = len(text.split())
        if words > MAX_WORDS_PER_SECOND * max(end - start, 2.0):
            raise WindowInvalid(f"{words} words in {end - start:.1f}s (runaway output)")
        turns.append({"start": start, "end": end, "text": text})

    speech_s = sum(e - s for s, e in strict)
    if not turns:
        if speech_s >= COVERAGE_MIN_SPEECH_S:
            raise WindowInvalid("no transcript for a window with speech")
        return []
    if sum(len(t["text"].split()) for t in turns) > MAX_WORDS_PER_SECOND * duration:
        raise WindowInvalid("more words than a window can hold")
    if any(b["start"] < a["start"] - 1.0 for a, b in zip(turns, turns[1:])):
        raise WindowInvalid("timestamps go backwards")
    if len(turns) > 3 and max(t["start"] for t in turns) - min(t["start"] for t in turns) < 0.25 * min(duration, speech_s or duration):
        raise WindowInvalid("timestamps are collapsed (all turns at nearly the same time)")

    if speech_s >= COVERAGE_MIN_SPEECH_S:
        covered = sum(_covered(stretch, turns) for stretch in strict)
        if covered / speech_s < MIN_COVERAGE:
            raise WindowInvalid(f"transcript covers only {covered / speech_s:.0%} of the speech")

    starts = [s for s, _ in vad]
    ends = [e for _, e in vad]
    for t in turns:
        t["start"] = _snap(t["start"], starts)
        t["end"] = max(_snap(t["end"], ends), t["start"] + 0.2)
    return turns
