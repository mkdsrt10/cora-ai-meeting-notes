"""Hosted speech-to-text, opt-in. Local MLX stays the default; selecting an
engine here sends each speech chunk's audio to that provider, so it is
off under enterprise lockdown (policy.require_outbound_allowed) and the UI
labels it as audio leaving the Mac.

Engines plug in at the same seam as the local one: one short, pause-bounded
clip in, {"text", "segments"} out (see transcribe._transcribe_chunks), so
chunking, silence removal, speaker attribution and cleanup are unchanged.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import db
from .audio import probe_duration

ENGINES = ("local", "gemini")

# More than this many words per second of audio is not speech — it is a
# model running away (LLM-style ASR can ramble or repeat on near-silence).
MAX_WORDS_PER_SECOND = 8

_INSTRUCTION = (
    "Transcribe this audio clip from a business meeting verbatim. Speakers mix Hindi and English; "
    "write Hindi words in Roman script (Hinglish) and keep English words as spoken. Do not translate, "
    "summarize, add speaker labels, timestamps, or commentary. Output only the spoken words. "
    "If there is no intelligible speech, output nothing."
)


def engine() -> str:
    import policy
    value = db.get_setting("transcription_engine", "local")
    if value not in ENGINES or policy.lockdown_enabled():
        return "local"  # lockdown overrides whatever Settings says
    return value


def transcribe_clip(clip: Path, prompt: str = "") -> dict[str, Any]:
    name = engine()
    if name == "gemini":
        return transcribe_gemini(clip, prompt)
    raise ValueError(f"No cloud engine selected (engine={name!r})")


def transcribe_gemini(clip: Path, prompt: str = "") -> dict[str, Any]:
    import ai_trace
    import credentials
    import policy

    policy.require_outbound_allowed("Cloud transcription")
    from google.genai import types

    model = db.get_setting("cloud_asr_model") or credentials.get_default_model()
    instruction = _INSTRUCTION
    if prompt:
        instruction += f"\nNames and terms that may come up (spell them like this): {prompt}"
    duration = probe_duration(clip)

    audio_info = ai_trace.file_fingerprint(clip)
    with ai_trace.span("transcription", "gemini.cloud_asr", provider="gemini", model=model,
                       input={"audio": audio_info, "instruction": instruction},
                       params={"temperature": 0.0}) as trace:
        client = credentials.get_client(traced=False)
        response = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=clip.read_bytes(), mime_type="audio/wav"), instruction],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        text = (response.text or "").strip() if response else ""
        trace.set_output(text, audio_s=audio_info.get("duration_s"))

    return _clip_result(text, duration)


def _clip_result(text: str, duration: float) -> dict[str, Any]:
    from .transcribe import collapse_repetition_loops

    text = collapse_repetition_loops(text)
    if len(text.split()) > MAX_WORDS_PER_SECOND * max(duration, 1.0):
        print(f"[Cloud ASR] Dropped a {len(text.split())}-word result for a {duration:.1f}s clip (runaway output).", flush=True)
        text = ""
    segments = [{"start": 0.0, "end": duration, "text": text}] if text else []
    return {"text": text, "segments": segments}
