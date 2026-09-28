"""Local MLX Whisper transcription (pause-bounded chunks, cleanup, tracing)."""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

import ai_trace
import db
from .audio import _to_original_time, build_trimmed_audio, ensure_mixed_audio, extract_clip, find_speech_segments, probe_duration
from .config import resolve_whisper_model


def collapse_repetition_loops(text: str) -> str:
    """Collapse a Whisper repetition-loop hallucination (a word or short
    phrase repeated 3+ times in a row, e.g. "the the the..." or "ek ek ek
    ek...") down to a single occurrence. A backstop for whatever
    temperature fallback (see transcribe_local_mlx) doesn't catch —
    legitimate intentional doubling ("very very important", "no no wait")
    survives untouched since this only triggers on 3+ repeats. Verified
    against a real ~900-char hallucinated run (collapses correctly, <1ms)
    and a full ~58k-char real transcript (~0.14s, no false positives)."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'([!?.\-])(?:\s*\1){2,}', r'\1', text)
        text = re.sub(r'\b(\w+)(?:\s+\1\b){2,}', r'\1', text, flags=re.IGNORECASE)
        text = re.sub(r'([^.!?\n]{4,60}[.!?]?)(?:\s*\1){2,}', r'\1', text, flags=re.IGNORECASE)
        text = re.sub(r'(\b(?:\w+\s+){1,6}\w+)(?:\s+\1\b){2,}', r'\1', text, flags=re.IGNORECASE)
    return text.strip()


def transcribe_local_mlx(audio_path: Path, prompt: str = "") -> dict[str, Any]:
    """Run local MLX Whisper speech-to-text on Apple Silicon Metal.

    temperature=0.0 (locked greedy decoding, no fallback) was the root
    cause of the repetition-loop hallucination bug seen repeatedly this
    session (confirmed: a real recording's transcript had a ~700-word "the
    the the..." run that then got extracted verbatim into an LLM-generated
    action item). mlx_whisper.transcribe() has a real, working retry
    mechanism for exactly this — on each temperature in the tuple, it
    checks compression_ratio_threshold/logprob_threshold and falls back to
    a higher (less deterministic) temperature if a segment looks too
    repetitive or low-confidence (verified against
    mlx_whisper/transcribe.py's own decode loop) — but a bare 0.0 disables
    it outright, since there's nothing left to fall back to. Restoring the
    library's own default fallback ladder re-enables that mechanism; the
    explicit thresholds below just make the trigger conditions visible
    rather than relying on library defaults silently applying.
    """
    import mlx_whisper

    model_id = resolve_whisper_model()
    decode_params = dict(language="en", condition_on_previous_text=False, temperature=(0.0, 0.2, 0.4),
                         compression_ratio_threshold=2.4, logprob_threshold=-1.0, no_speech_threshold=0.5,
                         word_timestamps=False)
    audio_info = ai_trace.file_fingerprint(audio_path)
    with ai_trace.span("transcription", "whisper.local_pipeline", provider="mlx", model=model_id,
                       input={"audio": audio_info, "initial_prompt": prompt}, params=decode_params,
                       prompt_template=prompt) as trace:
        result = _whisper_transcribe(mlx_whisper, audio_path, prompt, model_id)
        trace.set_output(_whisper_trace_output(result), audio_s=audio_info.get("duration_s"),
                         segments=len(result.get("segments", [])))
    for seg in result.get("segments", []):
        if "text" in seg:
            seg["text"] = collapse_repetition_loops(seg["text"])
    if "text" in result:
        result["text"] = collapse_repetition_loops(result["text"])
    return result


def _whisper_trace_output(result: dict[str, Any]) -> dict[str, Any]:
    """The raw decoder output plus per-segment confidence signals — the
    fields that matter for spotting hallucination and for retraining."""
    keep = ("start", "end", "text", "avg_logprob", "no_speech_prob", "compression_ratio", "temperature")
    return {
        "language": result.get("language"),
        "text": result.get("text"),
        "segments": [{k: seg.get(k) for k in keep if k in seg} for seg in result.get("segments", [])],
    }


def _whisper_transcribe(mlx_whisper, audio_path: Path, prompt: str, model_id: str) -> dict[str, Any]:
    return mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=model_id,
        language="en",
        initial_prompt=prompt,
        condition_on_previous_text=False,
        # Capped well below the library's own default ladder (which goes to
        # 1.0) — verified empirically against a real corrupted recording:
        # the full 0.0-1.0 ladder traded repetition-loop hallucination for
        # something worse, incoherent word-salad gibberish, once retries
        # climbed past ~0.6. This fine-tuned model's decoder is shallow (4
        # layers) and fragile at high temperature — better to accept an
        # occasional short repetition (still caught by
        # collapse_repetition_loops above) than confident-sounding nonsense
        # that looks like real speech and would slip straight past any
        # obvious-garbage filter into the LLM notes.
        temperature=(0.0, 0.2, 0.4),
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        no_speech_threshold=0.5,
        word_timestamps=False,
    )


def clean_whisper_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop consecutive segments that duplicate the previous one's text, and
    fix inverted/zero-length timestamps (end <= start).

    collapse_repetition_loops() only dedupes repetition WITHIN one segment's
    text — it never touches the case where Whisper emits the same short
    text as many separate, consecutive segments instead of one long
    repeated string. Verified this is a real, severe, and DIFFERENT failure
    mode from the one collapse_repetition_loops() catches: on a real
    corrupted recording, 127 of 289 consecutive segment pairs were exact
    duplicates (mostly a single hallucinated word like "replica." repeated
    across ~20 separate segments), with 58 of 290 segments also carrying
    inverted timestamps (end before start) from the same corrupted stretch.
    """
    cleaned: list[dict[str, Any]] = []
    last_text = ""
    for seg in segments:
        text = collapse_repetition_loops(str(seg.get("text", "")).strip())
        if not text:
            continue
        if text.lower() == last_text.lower():
            continue
        last_text = text

        start_sec = float(seg.get("start", 0.0))
        end_sec = float(seg.get("end", 0.0))
        if end_sec <= start_sec:
            end_sec = start_sec + 1.0

        cleaned.append({**seg, "text": text, "start": start_sec, "end": end_sec})
    return cleaned


CHUNK_TARGET_S = 12.0   # merge speech stretches up to about this long


CHUNK_MAX_S = 25.0      # hard cap (Whisper's window is 30s)


def plan_chunks(speech_segments: list[tuple[float, float]], target: float = CHUNK_TARGET_S,
                max_len: float = CHUNK_MAX_S) -> list[tuple[float, float]]:
    """Group speech stretches (original timeline) into transcription chunks
    that end at natural pauses. Stretches longer than max_len are split."""
    pieces: list[tuple[float, float]] = []
    for start, end in speech_segments:
        while end - start > max_len:
            pieces.append((start, start + max_len))
            start += max_len
        if end - start > 0.05:
            pieces.append((start, end))
    chunks: list[tuple[float, float]] = []
    for start, end in pieces:
        if chunks and end - chunks[-1][0] <= target:
            chunks[-1] = (chunks[-1][0], end)
        else:
            chunks.append((start, end))
    return chunks


def _transcribe_chunks(audio_path: Path, speech_segments: list[tuple[float, float]], prompt: str,
                       prompt_for: Optional[Callable[[float, float], str]] = None) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    chunks = plan_chunks(speech_segments)
    for start, end in chunks:
        clip = extract_clip(audio_path, start, end)
        try:
            result = transcribe_local_mlx(clip, prompt=prompt_for(start, end) if prompt_for else prompt)
        finally:
            clip.unlink(missing_ok=True)
        for seg in result.get("segments", []):
            seg_start = start + float(seg.get("start", 0.0))
            seg_end = min(end, start + float(seg.get("end", 0.0)))
            segments.append({**seg, "start": seg_start, "end": max(seg_end, seg_start)})
    return segments


def transcribe_with_silence_removal(audio_path: Path, prompt: str, folder: Optional[Path] = None,
                                    prompt_for: Optional[Callable[[float, float], str]] = None) -> tuple[list[dict[str, Any]], float, float]:
    """Detect and drop dead air, transcribe the remaining speech in a single
    Whisper pass, then shift segment timestamps back onto the original
    recording's timeline. Returns (segments, audio_duration, speech_duration).

    Speech is transcribed in pause-bounded chunks (see plan_chunks);
    mlx_whisper caches the loaded model (ModelHolder), so many chunks cost
    no reloads. The spliced single-pass audio is still built — as the
    fallback path and as audio_transcribed.wav for debugging.

    This also fixes a quality problem, not just a speed one: a long unbroken
    pass over real dead air (waiting for a screen share, muted, thinking) is
    exactly when Whisper's autoregressive decoder tends to hallucinate
    repeated phrases — the phrase-looping the fine-tuned model's
    anti-repetition setting is meant to prevent, but which a 70-minute
    uninterrupted pass could still trigger during long true-silence stretches.
    """
    model_id = resolve_whisper_model()
    model_label = Path(model_id).name if os.path.isabs(model_id) else model_id
    duration = probe_duration(audio_path)
    mixed_audio_path = ensure_mixed_audio(audio_path)
    speech_segments = find_speech_segments(mixed_audio_path)
    speech_duration = sum(end - start for start, end in speech_segments)
    print(
        f"[Local MLX] {model_label}: {len(speech_segments)} speech stretch(es), "
        f"{speech_duration:.0f}s of {duration:.0f}s kept "
        f"({100 * speech_duration / duration:.0f}% — {duration - speech_duration:.0f}s of silence skipped)",
        flush=True,
    )

    trimmed_path, mapping = build_trimmed_audio(mixed_audio_path, speech_segments)
    t0 = time.time()
    chunked: Optional[list[dict[str, Any]]] = None
    try:
        # Pause-bounded chunks: models without timestamp tokens (most
        # fine-tunes) emit one segment per 30s window, which lumps several
        # speakers into one "turn". Transcribing each stretch between
        # natural pauses gives turn-sized segments that speaker attribution
        # can label individually. Falls back to the single spliced pass.
        try:
            chunked = _transcribe_chunks(mixed_audio_path, speech_segments, prompt, prompt_for)
        except Exception as exc:
            print(f"[Local MLX] Chunked transcription failed, using single pass: {exc}", flush=True)
            result = transcribe_local_mlx(trimmed_path, prompt=prompt)
    finally:
        if mixed_audio_path != audio_path:
            mixed_audio_path.unlink(missing_ok=True)
        # The exact silence-stripped, spliced audio Whisper actually heard —
        # useful for hearing what a hallucinated/garbled segment really
        # sounded like, and for checking silence-removal didn't cut real
        # speech. Kept alongside audio.mov, so it follows the same
        # retain_audio opt-out rather than always persisting regardless of
        # that choice. Saved even on a failed transcribe_local_mlx call,
        # since that's exactly when it's most useful for debugging.
        if folder and db.get_setting("retain_audio", True):
            try:
                shutil.copy2(trimmed_path, folder / f"audio_transcribed{trimmed_path.suffix}")
            except Exception as exc:
                print(f"[Local MLX] Failed to save post-processed transcription audio: {exc}", flush=True)
        trimmed_path.unlink(missing_ok=True)
    print(f"[Local MLX] STT completed in {time.time() - t0:.1f}s over {speech_duration:.0f}s of speech"
          f" ({'pause-bounded chunks' if chunked is not None else 'single pass'})", flush=True)

    if chunked is not None:
        all_segments = chunked
    else:
        all_segments = [
            {**seg,
             "start": _to_original_time(float(seg.get("start", 0.0)), mapping),
             "end": _to_original_time(float(seg.get("end", 0.0)), mapping)}
            for seg in result.get("segments", [])
        ]
    all_segments.sort(key=lambda s: s["start"])
    all_segments = clean_whisper_segments(all_segments)
    return all_segments, duration, speech_duration
