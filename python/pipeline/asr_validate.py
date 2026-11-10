"""Checks on a hosted model's transcript of one window.

A hosted recognizer can fail quietly: drop a stretch of speech, return
timestamps that are all zero, ramble on silence, or echo the prompt. Each
check here either raises WindowInvalid (retry, then split, then local
Whisper or a marked gap) or snaps the timestamps onto the local speech detector's boundaries.
Times are seconds relative to the window start unless stated otherwise.
"""
from __future__ import annotations

from typing import Any
import math

from .transcribe import collapse_repetition_loops

MAX_WORDS_PER_SECOND = 8.0
MIN_COVERAGE = 0.6          # share of strict-VAD speech some turn must overlap
COVERAGE_MIN_SPEECH_S = 5.0  # below this much speech the check isn't meaningful
SNAP_S = 1.5
SATURATED_MIN_WINDOW_S = 20.0  # in a Window longer than this, strict hearing no silence = detector saturated
SATURATED_SHARE = 0.98         # "no silence": strict speech covers at least this share of the Window
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


def _saturated(strict: list[tuple[float, float]], duration: float) -> bool:
    """The strict detector heard no silence in a long Window (a noisy mic
    reads as one unbroken stretch): its speech list says nothing about where
    speech is, so it can't be used to demand coverage."""
    if duration <= SATURATED_MIN_WINDOW_S:
        return False
    heard = sum(max(0.0, min(e, duration) - max(s, 0.0)) for s, e in strict)
    return heard >= SATURATED_SHARE * duration


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
        if not math.isfinite(start) or not math.isfinite(end):
            raise WindowInvalid("turn timestamps must be finite")
        if end <= start:
            raise WindowInvalid("turn end must be after its start")
        if end > duration + 1.0:
            raise WindowInvalid(f"turn ends at {end:.1f}s outside a {duration:.0f}s window")
        if start < -1.0 or start > duration + 1.0:
            raise WindowInvalid(f"turn starts at {start:.1f}s outside a {duration:.0f}s window")
        start = min(max(start, 0.0), duration)
        end = min(max(end, start), duration)
        words = len(text.split())
        if words > MAX_WORDS_PER_SECOND * max(end - start, 2.0):
            raise WindowInvalid(f"{words} words in {end - start:.1f}s (runaway output)")
        turns.append({"start": start, "end": end, "text": text})

    speech_s = sum(e - s for s, e in strict)
    saturated = _saturated(strict, duration)
    if not turns:
        if speech_s >= COVERAGE_MIN_SPEECH_S and not saturated:
            raise WindowInvalid("no transcript for a window with speech")
        return []
    if sum(len(t["text"].split()) for t in turns) > MAX_WORDS_PER_SECOND * duration:
        raise WindowInvalid("more words than a window can hold")
    if any(b["start"] < a["start"] - 1.0 for a, b in zip(turns, turns[1:])):
        raise WindowInvalid("timestamps go backwards")
    if len(turns) > 3 and max(t["start"] for t in turns) - min(t["start"] for t in turns) < 0.25 * min(duration, speech_s or duration):
        raise WindowInvalid("timestamps are collapsed (all turns at nearly the same time)")

    if speech_s >= COVERAGE_MIN_SPEECH_S and not saturated:
        covered = sum(_covered(stretch, turns) for stretch in strict)
        if covered / speech_s < MIN_COVERAGE:
            raise WindowInvalid(f"transcript covers only {covered / speech_s:.0%} of the speech")

    starts = [s for s, _ in vad]
    ends = [e for _, e in vad]
    for t in turns:
        t["start"] = _snap(t["start"], starts)
        t["start"] = min(max(t["start"], 0.0), max(0.0, duration - 0.2))
        t["end"] = min(duration, max(_snap(t["end"], ends), t["start"] + 0.2))
    return turns
