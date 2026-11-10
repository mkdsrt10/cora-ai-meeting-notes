"""Transcribe a recording as multi-minute windows through a hosted model.

Each window goes through: extract FLAC -> model -> validate -> absolute
times. A failing window is retried, then split at a pause or midpoint with up to two
levels of smaller-clip retries. A window still rejected at the bottom of that
ladder, or one the provider refuses outright, is handed to `fallback` (local
Whisper) and its segments are marked `"engine": "local"`; with no fallback, or
one that fails, it becomes a marked gap segment. Every segment says which
engine produced it, so the substitution is never quiet (see engine_summary).
"""
from __future__ import annotations

import math
import threading
import time
from contextvars import copy_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import db
import ai_trace
from .asr_validate import WindowInvalid, validate_turns
from .audio import extract_clip_flac, find_speech_segments
from .errors import WindowedTranscriptionError
from .gemini_asr import AsrCallError, AsrRefusedError, context_block, transcribe_window
from .windows import Window, plan_windows, split_window

ATTEMPTS = 3
BACKOFF_S = (2.0, 6.0)
WORKERS = 3
MAX_SPLIT_DEPTH = 2  # At most 21 requests per original window, including retries.
STRICT_NOISE_DB = "-35dB"  # louder than the main detector: real speech only, for coverage checks

_sleep: Callable[[float], None] = time.sleep


WindowedASRError = WindowedTranscriptionError  # the old name

REJECTED = "the cloud engine kept rejecting this stretch"
REFUSED = "the cloud engine refused this stretch"
NO_LOCAL_MODEL = "no local model is installed"
LOCAL_FAILED = "local transcription failed"

Segment = dict[str, Any]
Fallback = Callable[[Path, float, float], list[Segment]]
WindowFailed = Callable[[float, float, str], None]


def _self_name() -> str:
    return db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name") or ""


def _relative(spans: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    return [(max(s, start) - start, min(e, end) - start) for s, e in spans if e > start and s < end]


def transcribe_windows(audio_path: Path, speech: list[tuple[float, float]], context: Any,
                       offset: float = 0.0, workers: int = WORKERS,
                       caller: Optional[Callable[..., list[dict[str, Any]]]] = None,
                       strict: Optional[list[tuple[float, float]]] = None,
                       fallback: Optional[Fallback] = None,
                       on_window_failed: Optional[WindowFailed] = None,
                       provider: str = "gemini") -> list[dict[str, Any]]:
    """audio_path: the mixed mono recording. speech: its speech stretches.
    context: a MeetingContext. offset: this part's start in the whole recording
    (only for matching screenshot text to the right moment).
    fallback(audio_path, start, end): transcribes a rejected window locally,
    segments in absolute times. on_window_failed(start, end, reason): told of
    every window the cloud engine did not transcribe. provider: the `engine`
    mark on cloud segments."""
    call = caller or transcribe_window
    fallback_lock = threading.Lock()  # one local model run at a time, whatever the worker count

    def replace(window: Window, reason: str) -> list[Segment]:
        segments: Optional[list[Segment]] = None
        if fallback is not None:
            print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s: {reason}; transcribing it on this Mac", flush=True)
            try:
                with fallback_lock:
                    produced = fallback(audio_path, window.start, window.end)
                segments = [{**seg, "engine": "local", "reason": reason} for seg in produced]
            except Exception as exc:
                print(f"[Cloud ASR] local transcription of {window.start:.0f}-{window.end:.0f}s failed: {exc}", flush=True)
                reason = f"{reason}; {LOCAL_FAILED}"
        else:
            reason = f"{reason}; {NO_LOCAL_MODEL}"
        if segments is None:
            print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s left as a gap: {reason}", flush=True)
            segments = [{"start": window.start, "end": window.end, "text": "", "engine": "gap", "reason": reason}]
        if on_window_failed is not None:
            on_window_failed(window.start, window.end, reason)
        return segments

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
                with ai_trace.span('asr_attempt',
                                   f'asr.window.{window.start:.1f}-{window.end:.1f}.attempt{attempt + 1}',
                                   provider='local', params={'window_start_s': window.start,
                                                            'window_end_s': window.end,
                                                            'attempt': attempt + 1, 'split_depth': depth}) as trace:
                    clip = extract_clip_flac(audio_path, window.start, window.end)
                    glossary = context.glossary(window.start + offset, window.end + offset)
                    block = context_block(context.title, context.attendees, self_name, glossary, window.duration)
                    context.record(window.start + offset, window.end + offset, "[cloud window] " + ", ".join(glossary))
                    raw = call(clip, window.duration, block)
                    turns = validate_turns(raw, window.duration,
                                           _relative(strict, window.start, window.end),
                                           _relative(window.stretches, window.start, window.end))
                    trace.set_output({"validated_turns": len(turns)})
                    return [{"start": window.start + t["start"], "end": window.start + t["end"], "text": t["text"],
                             "engine": provider} for t in turns]
            except AsrRefusedError as exc:
                print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s refused: {exc}", flush=True)
                return replace(window, REFUSED)
            except (WindowInvalid, AsrCallError) as exc:
                last = exc
                print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s attempt {attempt + 1}/{ATTEMPTS}: {exc}", flush=True)
                if attempt < ATTEMPTS - 1:
                    _sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
            finally:
                if clip is not None:
                    clip.unlink(missing_ok=True)
        halves = split_window(window) if depth < MAX_SPLIT_DEPTH else None
        if halves:
            print(f"[Cloud ASR] splitting window {window.start:.0f}-{window.end:.0f}s (level {depth + 1}/{MAX_SPLIT_DEPTH}) and retrying each half", flush=True)
            return [seg for half in halves for seg in run(half, depth + 1)]
        print(f"[Cloud ASR] window {window.start:.0f}-{window.end:.0f}s failed at every split level: {last}", flush=True)
        return replace(window, REJECTED)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # Executor workers do not inherit ContextVars. Give every task a
        # separate copy (a Context cannot be entered concurrently), preserving
        # the recording/run IDs and the parent trace span.
        futures = [pool.submit(copy_context().run, run, window) for window in windows]
        results = [future.result() for future in futures]
    segments = [seg for part in results for seg in part]
    segments.sort(key=lambda s: s["start"])
    return segments


def engine_summary(segments: list[Segment]) -> dict[str, Any]:
    """What the cloud engine did not transcribe: {"local_s", "gap_s",
    "windows": [{"start", "end", "engine", "reason"}]}. Consecutive local
    segments with the same reason are one window; seconds are window spans."""
    windows: list[dict[str, Any]] = []
    open_local: Optional[dict[str, Any]] = None  # the local window the previous segment belonged to
    for seg in sorted(segments, key=lambda s: s["start"]):
        engine, reason = seg.get("engine"), seg.get("reason", "")
        if engine == "local" and open_local is not None and open_local["reason"] == reason:
            open_local["end"] = max(open_local["end"], float(seg["end"]))
            continue
        open_local = None
        if engine in ("local", "gap"):
            windows.append({"start": float(seg["start"]), "end": float(seg["end"]), "engine": engine, "reason": reason})
            open_local = windows[-1] if engine == "local" else None
    seconds = {kind: round(sum(w["end"] - w["start"] for w in windows if w["engine"] == kind), 3)
               for kind in ("local", "gap")}
    return {"local_s": float(seconds["local"]), "gap_s": float(seconds["gap"]), "windows": windows}


def engine_notice(summary: dict[str, Any]) -> Optional[str]:
    """The one notification body for a Recording's engine_summary, or None
    when the cloud engine transcribed everything."""
    parts = []
    for kind, what in (("local", "transcribed on this Mac"), ("gap", "could not be transcribed")):
        seconds = summary.get(f"{kind}_s") or 0.0
        if seconds > 0:
            reasons = list(dict.fromkeys(w["reason"] for w in summary.get("windows", []) if w["engine"] == kind))
            parts.append(f"{math.ceil(seconds / 60)} min {what} ({'; '.join(reasons)}).")
    return " ".join(parts) or None
