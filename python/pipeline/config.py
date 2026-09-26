"""Model selection and MLX runtime settings shared by the local pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import db
import paths


ROOT = paths.APP_ROOT


CONFIG_PATH = paths.CONFIG_PATH


# A fine-tuned personal model (if present) wins; otherwise fall back to
# whatever public MLX Whisper repo config.json names, and finally to a
# public stock model — so a fresh OSS install has a working local model with
# zero manual setup, rather than only working for whoever trained the
# personal checkpoint.
PUBLIC_WHISPER_FALLBACK = "mlx-community/whisper-small-mlx"


def _config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def local_whisper_models() -> list[dict[str, Any]]:
    """Fine-tuned local checkpoints listed in config.json, in priority order.

    Each entry: {"path": "~/my-whisper-mlx", "label": ..., "tradeoff": ...}.
    Only entries whose path exists are returned.
    """
    models = []
    for entry in _config().get("local_whisper_models") or []:
        if isinstance(entry, str):
            entry = {"path": entry}
        path = Path(str(entry.get("path", ""))).expanduser()
        if entry.get("path") and path.exists():
            models.append({**entry, "path": path})
    return models


def _resolve_whisper_model() -> str:
    # An explicit onboarding choice (db setting) wins over the automatic
    # fine-tuned-model-if-present fallback chain.
    chosen = db.get_setting("whisper_model_choice")
    if chosen:
        return chosen
    for model in local_whisper_models():
        return str(model["path"])
    return _config().get("whisper_model") or PUBLIC_WHISPER_FALLBACK


MLX_WHISPER_MODEL = _resolve_whisper_model()


LOCAL_LLM_MODEL_DEFAULT = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


BIN_OCR = paths.BIN_DIR / "mac-ocr"


def _cap_mlx_memory() -> None:
    """Hard-cap MLX's Metal memory use for this process, once, at import
    time. Without this, both set_memory_limit and set_cache_limit default
    to ~1.5x the device's max recommended working set — on this machine
    that's a large enough ceiling that MLX's Metal allocator cache was
    free to grow, unreclaimed, across many sequential mlx_lm.generate()
    calls within a single long notes-generation run. Measured directly:
    the server process reached 11.41 GB RSS mid-run and crashed the
    machine, for a 4-bit Qwen3-4B that should need on the order of 4-5 GB
    even generously. A low cache_limit forces the allocator to reclaim
    unused cached buffers on the very next allocation instead of hoarding
    them; memory_limit is a hard ceiling so a real overrun raises a
    catchable Python exception (surfaced as a normal pipeline error)
    instead of exhausting system memory and taking the whole machine down.
    """
    try:
        import mlx.core as mx
        mx.set_cache_limit(1 * 1024**3)
        mx.set_memory_limit(6 * 1024**3)
    except Exception as exc:
        print(f"[Local Pipeline] Could not set MLX memory limits: {exc}", flush=True)


_cap_mlx_memory()


# Domain vocabulary hint fed to Whisper as an initial_prompt to bias spelling
# of names/products/systems specific to your own meetings. Configure your own
# via config.json's "transcription_vocabulary_hint" — this defaults to
# nothing so a fresh install doesn't inherit one user's personal contacts and
# employer's internal system names. This is only the *static* base — see
# build_vocabulary_prompt() for the per-recording dynamic part (known people,
# terms matched to the meeting title, and terms learned from past transcripts).
DEFAULT_KEYWORDS = _config().get("transcription_vocabulary_hint", "")


# A gap has to be at least this long to count as "dead air" worth cutting out
# before transcription — short inter-word/inter-sentence pauses (<1.2s) are
# left alone so a chunk boundary never lands mid-sentence.
SILENCE_MIN_GAP_SECONDS = float(_config().get("silence_min_gap_seconds", 1.2))


SILENCE_THRESHOLD_DB = str(_config().get("silence_threshold_db", "-50dB"))


def _clear_mlx_cache() -> None:
    """Reclaim MLX's cached (but unused) Metal buffers right now, rather
    than waiting for the next allocation to trigger it — called after
    every single chunk/section generate() call in generate_enhanced_notes'
    run(), not just once at the very end of the whole function. A months-
    old design only released memory at end-of-run; with a long recording
    needing 40+ sequential generate() calls (many chunks x many sections),
    that let the process's RSS climb to 11+ GB mid-run and crash the
    machine before cleanup ever got a chance to run. See _cap_mlx_memory
    for the hard ceiling this works alongside."""
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception as exc:
        print(f"[Local LLM] Failed to clear MLX cache: {exc}", flush=True)


def _release_mlx_model(model, tokenizer) -> None:
    """Fuller cleanup than _clear_mlx_cache alone — also drops Python's own
    references to the model/tokenizer, called once when generate_enhanced_notes
    or generate_summary_variant finishes with them entirely (see
    _clear_mlx_cache for the more frequent per-call version)."""
    import gc
    try:
        import mlx.core as mx
        del model, tokenizer
        gc.collect()
        mx.clear_cache()
    except Exception as exc:
        print(f"[Local LLM] Failed to release MLX model memory: {exc}", flush=True)
