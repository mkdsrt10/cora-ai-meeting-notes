"""Transcriber: the one way Cora turns speech into timed text.

    segments, duration, speech_s = transcriber(profile).transcribe(audio_path, context=..., prompt=...)

The Processing profile's `transcription` picks the engine (ENGINES). Behind
the interface this module owns: lockdown, dead-air removal, mapping times
back onto the recording, cleanup of repeated/inverted segments, tracing,
and for hosted engines the windowed ladder (pipeline/windowed.py: retry,
split, validate, snap to speech boundaries). A hosted engine that fails
fails the run; it never quietly substitutes another engine.

Engines:
  local              on-device MLX Whisper in pause-bounded chunks
  gemini             Gemini audio, multi-minute windows (pipeline/gemini_asr.py)
  openai_compatible  POST {base_url}/audio/transcriptions on the profile's
                     OpenAI-compatible endpoint (OpenAI, Groq, a local server)
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Optional

import ai_trace
import policy

ENGINES = ("local", "gemini", "openai_compatible")
# Speech-to-text model per OpenAI-compatible preset; override with the
# `openai_asr_model` setting.
OPENAI_AUDIO_DEFAULTS = {"groq": "whisper-large-v3"}
OPENAI_AUDIO_DEFAULT = "whisper-1"

Segments = list[dict[str, Any]]


class Transcriber:
    """See the module docstring. `engine` and `model` say what transcribes."""

    def __init__(self, adapter: Any, *, engine: str, model: str) -> None:
        self._adapter, self.engine, self.model = adapter, engine, model

    def transcribe(self, audio_path: Path, *, prompt: str = "", context: Any = None,
                   prompt_for: Optional[Callable[[float, float], str]] = None, offset: float = 0.0,
                   keep_audio_in: Optional[Path] = None) -> tuple[Segments, float, float]:
        """Transcribe one audio file. Returns (segments on the file's own
        timeline, audio duration, seconds of speech).

        prompt / prompt_for(start, end): Whisper initial prompts (local).
        context: a MeetingContext, for hosted engines' per-window glossary.
        offset: this file's start within the whole recording (context lookups).
        keep_audio_in: folder that gets audio_transcribed.* (the silence-
        stripped audio the model heard), when audio is retained.

        Dead air is dropped before transcription: a long unbroken pass over
        true silence is exactly when Whisper's decoder hallucinates repeated
        phrases, and hosted engines bill for it.
        """
        import db
        from .audio import build_trimmed_audio, ensure_mixed_audio, find_speech_segments, probe_duration
        from .transcribe import clean_whisper_segments
        duration = probe_duration(audio_path)
        mixed = ensure_mixed_audio(audio_path)
        speech = find_speech_segments(mixed)
        speech_s = sum(end - start for start, end in speech)
        print(f"[ASR] {self.engine}:{self.model}: {len(speech)} speech stretch(es), {speech_s:.0f}s of {duration:.0f}s kept "
              f"({100 * speech_s / duration:.0f}% — {duration - speech_s:.0f}s of silence skipped)", flush=True)
        trimmed, mapping = build_trimmed_audio(mixed, speech)
        t0 = time.time()
        try:
            segments = self._adapter.segments(mixed, speech, dict(prompt=prompt, prompt_for=prompt_for, context=context,
                                                                 offset=offset, trimmed=trimmed, mapping=mapping))
        finally:
            if mixed != audio_path:
                mixed.unlink(missing_ok=True)
            # Kept alongside audio.mov, so it follows the retain_audio opt-out;
            # saved even when transcription failed, since that's when it helps most.
            if keep_audio_in and db.get_setting("retain_audio", True):
                try:
                    shutil.copy2(trimmed, keep_audio_in / f"audio_transcribed{trimmed.suffix}")
                except Exception as exc:
                    print(f"[ASR] Failed to save post-processed transcription audio: {exc}", flush=True)
            trimmed.unlink(missing_ok=True)
        print(f"[ASR] STT completed in {time.time() - t0:.1f}s over {speech_s:.0f}s of speech", flush=True)
        segments.sort(key=lambda s: s["start"])
        return clean_whisper_segments(segments), duration, speech_s


def transcriber(profile: dict[str, Any]) -> Transcriber:
    """The Transcriber for a Processing profile (`transcription`, and
    `provider` for the OpenAI-compatible endpoint). Raises
    policy.LockdownError for a hosted engine under lockdown."""
    return _make(profile)


def _make(profile: dict[str, Any]) -> Transcriber:
    engine = profile.get("transcription") or "local"
    if engine not in ENGINES:
        raise ValueError(f"Unknown transcription engine: {engine}")
    if engine == "local":
        from .config import resolve_whisper_model
        model_id = resolve_whisper_model()
        return Transcriber(MlxWhisper(), engine=engine, model=Path(model_id).name if os.path.isabs(model_id) else model_id)
    if engine == "gemini":
        policy.require_outbound_allowed("Gemini transcription")
        from .gemini_asr import model_name, transcribe_window
        model = model_name()
        return Transcriber(Windowed(lambda clip, duration, block: transcribe_window(clip, duration, block, model=model)),
                           engine=engine, model=model)
    import credentials
    import db
    from .text_model import OPENAI_COMPATIBLE
    preset = profile.get("provider") if profile.get("provider") in OPENAI_COMPATIBLE else "openai"
    settings = credentials.provider_settings(preset)
    base_url = (settings.get("base_url") or OPENAI_COMPATIBLE[preset][0]).rstrip("/")
    if not policy.provider_allowed(preset, base_url):
        raise policy.LockdownError("Hosted transcription is disabled by enterprise lockdown.")
    model = db.get_setting("openai_asr_model") or OPENAI_AUDIO_DEFAULTS.get(preset, OPENAI_AUDIO_DEFAULT)
    return Transcriber(Windowed(OpenAICompatibleAudio(base_url, settings.get("api_key") or "", model).window),
                       engine=engine, model=model)


# ---- adapters ---------------------------------------------------------------------
# segments(mixed_audio, speech_stretches, hints) -> segments on the original timeline.

class MlxWhisper:
    def segments(self, audio: Path, speech: list[tuple[float, float]], hints: dict[str, Any]) -> Segments:
        """Pause-bounded chunks: models without timestamp tokens (most
        fine-tunes) emit one segment per 30s window, which lumps several
        speakers into one turn; chunking between natural pauses gives
        turn-sized segments. Falls back to one pass over the spliced audio."""
        from .audio import _to_original_time
        from .transcribe import _transcribe_chunks, transcribe_local_mlx
        try:
            return _transcribe_chunks(audio, speech, hints["prompt"], hints["prompt_for"])
        except Exception as exc:
            print(f"[Local MLX] Chunked transcription failed, using single pass: {exc}", flush=True)
        result = transcribe_local_mlx(hints["trimmed"], prompt=hints["prompt"])
        mapping = hints["mapping"]
        return [{**seg, "start": _to_original_time(float(seg.get("start", 0.0)), mapping),
                 "end": _to_original_time(float(seg.get("end", 0.0)), mapping)} for seg in result.get("segments", [])]


class Windowed:
    """Hosted engines: multi-minute windows through windowed.transcribe_windows,
    with `window(clip, duration, context_block) -> raw turns` as the one call."""

    def __init__(self, window: Callable[[Path, float, str], list[dict[str, Any]]]) -> None:
        self.window = window

    def segments(self, audio: Path, speech: list[tuple[float, float]], hints: dict[str, Any]) -> Segments:
        from .context import MeetingContext
        from .windowed import transcribe_windows
        return transcribe_windows(audio, speech, hints["context"] or MeetingContext(), offset=hints["offset"],
                                  caller=self.window)


_RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


def _whisper_prompt(block: str) -> str:
    """Names and terms from the hosted-engine context block, as a Whisper prompt
    (vocabulary only: Whisper prompts are spelling hints, not instructions)."""
    keep = ("Meeting title:", "Attendees:", "Names and terms")
    values = [line.split(":", 1)[1].strip() for line in block.splitlines()
              if line.startswith(keep) and ":" in line]
    return ", ".join(v for v in values if v)[:800]


class OpenAICompatibleAudio:
    """One window through POST {base_url}/audio/transcriptions (verbose_json)."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url, self.api_key, self.model = base_url, api_key, model

    def window(self, clip: Path, duration: float, block: str) -> list[dict[str, Any]]:
        """Raw turns relative to the clip. Rate limits, server errors and
        dropped connections raise AsrCallError (retried by the ladder); a
        rejected key raises ProviderAuthError; other HTTP errors (unknown
        model) fail the run."""
        import requests

        from .errors import AUTH_STATUS, ProviderAuthError
        from .gemini_asr import AsrCallError
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        mime = {".wav": "audio/wav", ".flac": "audio/flac"}.get(clip.suffix.lower(), "audio/flac")
        data = {"model": self.model, "response_format": "verbose_json", "prompt": _whisper_prompt(block)}
        fingerprint = ai_trace.file_fingerprint(clip)
        # Only sizes and counts are traced, never the transcript or the meeting's names.
        with ai_trace.span("transcription", "openai_compatible.window", provider="openai_compatible", model=self.model,
                           input={"audio": fingerprint}) as trace:
            try:
                res = requests.post(f"{self.base_url}/audio/transcriptions", headers=headers, data=data,
                                    files={"file": (clip.name, clip.read_bytes(), mime)}, timeout=300)
                res.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as exc:
                raise AsrCallError(f"Transcription request failed: {exc}") from exc
            except requests.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status in _RETRY_STATUS:
                    raise AsrCallError(f"Transcription request failed: {exc}") from exc
                if status in AUTH_STATUS:
                    raise ProviderAuthError("openai_compatible") from exc
                raise
            body = res.json()
            raw = body.get("segments")
            if raw is None:
                text = str(body.get("text") or "").strip()
                raw = [{"start": 0.0, "end": duration, "text": text}] if text else []
            if not isinstance(raw, list):
                raise AsrCallError("Transcription reply had no segments list")
            turns = [{"start": s.get("start"), "end": s.get("end"), "text": str(s.get("text", "")).strip()}
                     for s in raw if isinstance(s, dict)]
            trace.set_output({"turns": len(turns)}, audio_s=fingerprint.get("duration_s"))
        return turns


class FakeTranscriber(Transcriber):
    """Test stand-in: returns `segments` without touching audio."""

    def __init__(self, segments: Segments, *, engine: str = "local", model: str = "fake") -> None:
        super().__init__(None, engine=engine, model=model)
        self._segments = segments

    def transcribe(self, audio_path: Path, **kwargs: Any) -> tuple[Segments, float, float]:
        segments = [dict(s) for s in self._segments]
        end = max((s["end"] for s in segments), default=0.0)
        return segments, end, end
