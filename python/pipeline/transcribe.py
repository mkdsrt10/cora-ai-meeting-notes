"""Local MLX Whisper transcription (pause-bounded chunks, cleanup, tracing).

Callers go through pipeline.transcriber; this is its MlxWhisper implementation."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

import ai_trace
from .audio import extract_clip
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


def _transcribe_clip(clip: Path, prompt: str) -> dict[str, Any]:
    return transcribe_local_mlx(clip, prompt=prompt)


def _transcribe_chunks(audio_path: Path, speech_segments: list[tuple[float, float]], prompt: str,
                       prompt_for: Optional[Callable[[float, float], str]] = None) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    chunks = plan_chunks(speech_segments)
    for start, end in chunks:
        clip = extract_clip(audio_path, start, end)
        try:
            result = _transcribe_clip(clip, prompt_for(start, end) if prompt_for else prompt)
        finally:
            clip.unlink(missing_ok=True)
        for seg in result.get("segments", []):
            seg_start = start + float(seg.get("start", 0.0))
            seg_end = min(end, start + float(seg.get("end", 0.0)))
            segments.append({**seg, "start": seg_start, "end": max(seg_end, seg_start)})
    return segments
