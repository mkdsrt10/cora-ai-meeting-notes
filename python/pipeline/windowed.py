"""Transcribe a recording as multi-minute windows through a hosted model.

Each window goes through: extract FLAC -> model -> validate -> absolute
times. A failing window is retried, then split at its longest pause and each
half retried; if that still fails the whole run fails with a clear error —
it never quietly substitutes a different engine, and it never half-saves.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import db
from .asr_validate import WindowInvalid, validate_turns
from .audio import extract_clip_flac, find_speech_segments
from .gemini_asr import AsrCallError, context_block, transcribe_window
from .windows import Window, plan_windows, split_window

ATTEMPTS = 3
BACKOFF_S = (2.0, 6.0)
WORKERS = 3
STRICT_NOISE_DB = "-35dB"  # louder than the main detector: real speech only, for coverage checks

_sleep: Callable[[float], None] = time.sleep


class WindowedASRError(RuntimeError):
    pass


def _self_name() -> str:
    return db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name") or ""


def _relative(spans: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    return [(max(s, start) - start, min(e, end) - start) for s, e in spans if e > start and s < end]


def transcribe_windows(audio_path: Path, speech: list[tuple[float, float]], context: Any,
                       offset: float = 0.0, workers: int = WORKERS,
                       caller: Optional[Callable[..., list[dict[str, Any]]]] = None,
                       strict: Optional[list[tuple[float, float]]] = None) -> list[dict[str, Any]]:
    """audio_path: the mixed mono recording. speech: its speech stretches.
    context: a MeetingContext. offset: this part's start in the whole recording
    (only for matching screenshot text to the right moment)."""
    call = caller or transcribe_window
    if strict is None:
        strict = find_speech_segments(audio_path, noise_db=STRICT_NOISE_DB, min_gap=0.6)
    self_name = _self_name()
    windows = plan_windows(speech)
    print(f"[Cloud ASR] {len(windows)} window(s) for {sum(w.duration for w in windows) / 60:.1f} min of speech", flush=True)

    def run(window: Window, depth: int = 0) -> list[dict[str, Any]]:
        last: Optional[Exception] = None
        for attempt in range(ATTEMPTS):
            clip = None
            try:
                clip = extract_clip_flac(audio_path, window.start, window.end)
                glossary = context.glossary(window.start + offset, window.end + offset)
                block = context_block(context.title, context.attendees, self_name, glossary, window.duration)
                context.record(window.start + offset, window.end + offset, "[cloud window] " + ", ".join(glossary))
                raw = call(clip, window.duration, block)
                turns = validate_turns(raw, window.duration,
                                       _relative(strict, window.start, window.end),
                                       _relative(window.stretches, window.start, window.end))
                return [{"start": window.start + t["start"], "end": window.start + t["end"], "text": t["text"]} for t in turns]
            except (WindowInvalid, AsrCallError) as exc:
                last = exc
                print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s attempt {attempt + 1}/{ATTEMPTS}: {exc}", flush=True)
                if attempt < ATTEMPTS - 1:
                    _sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
            finally:
                if clip is not None:
                    clip.unlink(missing_ok=True)
        halves = split_window(window) if depth == 0 else None
        if halves:
            print(f"[Cloud ASR] splitting window {window.start:.0f}-{window.end:.0f}s and retrying each half", flush=True)
            return [seg for half in halves for seg in run(half, depth + 1)]
        raise WindowedASRError(f"Cloud transcription failed for {window.start:.0f}-{window.end:.0f}s of the recording: {last}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(run, windows))
    segments = [seg for part in results for seg in part]
    segments.sort(key=lambda s: s["start"])
    return segments
