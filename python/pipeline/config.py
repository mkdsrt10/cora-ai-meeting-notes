"""Model selection and MLX runtime settings shared by the local pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

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


def _dir_has_weights(model_dir: Path) -> bool:
    """Whether model_dir actually has real (non-empty) weights, not just a
    config/tokenizer — covers both mlx_whisper's expected filenames
    (weights.safetensors, falling back to weights.npz — see
    mlx_whisper.load_models.load_model) and mlx_lm's sharded *.safetensors.

    A directory that exists but is missing its weights (an interrupted
    download or conversion, or files cleaned up under disk pressure) used
    to get selected anyway — mlx_whisper's own load_model() only checks
    model_dir.exists(), so it picked the broken directory and every
    recording failed with an opaque "[load_npz] ... not a zip file" error
    until the whole app was restarted onto a different choice.
    """
    for pattern in ("weights.safetensors", "weights.npz", "*.safetensors"):
        for f in model_dir.glob(pattern):
            if f.is_file() and f.stat().st_size > 0:
                return True
    return False


def _hf_snapshot_dir(repo_id: str) -> Optional[Path]:
    """The downloaded snapshot folder for a cached HF repo id, or None if
    it's never been fetched (or the cache entry is an empty shell)."""
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo_id.replace("/", "--"))
    snapshots = cache_dir / "snapshots"
    if not snapshots.is_dir():
        return None
    for snap in snapshots.iterdir():
        if snap.is_dir():
            return snap
    return None


def model_ready(model_id: str) -> bool:
    """Whether model_id — a local directory path, or an HF repo id — has
    real weights available right now: a local fine-tune whose weights went
    missing, or an HF repo never (fully) downloaded, both read as not
    ready, rather than surfacing as an opaque crash deep inside mlx later."""
    path = Path(model_id).expanduser()
    if path.is_dir():
        return _dir_has_weights(path)
    snap = _hf_snapshot_dir(model_id)
    return bool(snap) and _dir_has_weights(snap)


def whisper_model_status() -> dict[str, Any]:
    import policy
    engine = db.get_setting("transcription_engine", "local")
    lockdown = policy.lockdown_enabled()
    if engine != "local" and not lockdown:
        # A hosted engine needs no local weights, so don't nag to download any.
        return {"model_id": engine, "ready": True, "engine": engine, "lockdown": lockdown}
    model_id = resolve_whisper_model()
    return {"model_id": model_id, "ready": model_ready(model_id), "engine": "local", "lockdown": lockdown}


def llm_model_status() -> dict[str, Any]:
    model_id = db.get_setting("liquid_model", LOCAL_LLM_MODEL_DEFAULT)
    return {"model_id": model_id, "ready": model_ready(model_id)}


def local_whisper_models() -> list[dict[str, Any]]:
    """Fine-tuned local checkpoints listed in config.json, in priority order.

    Each entry: {"path": "~/my-whisper-mlx", "label": ..., "tradeoff": ...}.
    Only entries that exist AND have actual weights are returned.
    """
    models = []
    for entry in _config().get("local_whisper_models") or []:
        if isinstance(entry, str):
            entry = {"path": entry}
        path = Path(str(entry.get("path", ""))).expanduser()
        if entry.get("path") and path.is_dir() and _dir_has_weights(path):
            models.append({**entry, "path": path})
    return models


def resolve_whisper_model() -> str:
    """Which Whisper model to transcribe with, right now.

    Deliberately re-read on every call rather than cached at import time: a
    server process can live across many settings changes (switching models
    in the UI, a local checkpoint's weights going missing), and a stale
    cached choice previously meant a broken local model kept getting picked
    every run until the whole app was restarted.
    """
    # An explicit onboarding choice (db setting) wins over the automatic
    # fine-tuned-model-if-present fallback chain — but only when it still
    # resolves to something real. A Hugging Face repo id (no local path)
    # can't be validated without a network call, so those are trusted as
    # given; an explicit *local* choice whose weights have since gone
    # missing falls through instead of repeating the same failure forever.
    chosen = db.get_setting("whisper_model_choice")
    if chosen:
        chosen_path = Path(str(chosen)).expanduser()
        if not chosen_path.is_dir() or _dir_has_weights(chosen_path):
            return chosen
        print(f"[Local MLX] Configured whisper_model_choice {chosen!r} has no weights; falling back.", flush=True)
    for model in local_whisper_models():
        return str(model["path"])
    return _config().get("whisper_model") or PUBLIC_WHISPER_FALLBACK


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
