"""Shared state and view-model builders for the local API (recording/dashboard payloads, paths, helpers)."""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

import paths  # noqa: E402

ROOT = paths.APP_ROOT
APP = paths.PYTHON_DIR
STATIC = paths.STATIC_DIR
RECORDINGS = paths.RECORDINGS_DIR
INBOX = paths.INBOX_DIR
PEOPLE_DIR = paths.PEOPLE_DIR
COACH_DATA = paths.COACH_DATA_PATH
STATE = paths.STATE_PATH
PIPELINE = APP / "voice_memo_pipeline.py"
PYTHON = paths.venv_python()
API_TOKEN_FILE = paths.API_TOKEN_FILE
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
import plugin_host  # noqa: E402


def archetypes() -> dict[int, dict[str, Any]]:
    """Coaching rubric archetypes by id while the Coaching plugin is enabled;
    {} otherwise, so tagging a Recording with an archetype is a no-op.
    TODO(plugins): tag with core meeting_types instead and drop this."""
    if not plugin_host.is_enabled("coaching"):
        return {}
    from plugins.coaching import engine
    return engine.ARCHETYPES


DATA_LOCK = threading.Lock()
DEFAULT_DATA = {
    "goals": {
        "weekly_sessions": 7,
        "clarity_target": 75,
        "filler_target_per_minute": 2.0,
        "pace_min": 120,
        "pace_max": 165,
        "focus": "Say the main point early and end with a clear next action.",
    },
    "reflections": [],
}


def current_self_name() -> str | None:
    return db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name")


LOCAL_LLM_MODELS = [
    {
        "id": "mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "label": "Qwen3 4B (Recommended for Accuracy)",
        "approx_size_gb": 2.1,
        "tradeoff": "Top accuracy: captures 100% decisions, true action items, and owners. Recommended for 16GB+ Macs."
    },
    {
        "id": "LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit",
        "label": "Liquid 1.2B (Legacy Fast)",
        "approx_size_gb": 0.7,
        "tradeoff": "Fastest, but hallucinates and drops action items on complex meetings."
    },
    {
        "id": "LiquidAI/LFM2.5-2.6B-MLX-4bit",
        "label": "Liquid 2.6B",
        "approx_size_gb": 1.5,
        "tradeoff": "Mid-tier model."
    },
    {
        "id": "mlx-community/Qwen3-8B-4bit",
        "label": "Qwen3 8B (Higher-end Macs)",
        "approx_size_gb": 4.6,
        "tradeoff": "Noticeably better reasoning and notes quality than the 4B default. Needs 32GB+ of RAM to run comfortably alongside the rest of Cora's pipeline."
    },
    {
        "id": "mlx-community/Qwen3-14B-4bit",
        "label": "Qwen3 14B (High-end Macs)",
        "approx_size_gb": 8.3,
        "tradeoff": "The most capable local option — best for dense, technical, or long meetings. Needs 64GB+ of RAM; expect slower generation than the smaller models."
    },
]


def _hf_cache_has(repo_id: str) -> bool:
    """Whether repo_id has real, usable weights cached locally — not just an
    empty/interrupted cache directory. See pipeline.config.model_ready."""
    import pipeline.config as pcfg
    return pcfg.model_ready(repo_id)


def local_usage_stats() -> dict[str, Any]:
    """Real local-resource numbers only — no fabricated metrics.
    Transcription speed and LLM throughput are averaged over the last 7
    days of local processing runs (see log_resource_usage in
    local_meeting_pipeline.py) rather than just the most recent run, so one
    unusually slow/fast recording doesn't swing the sidebar stat — falls
    back to whatever's available (even a single run) when there's less
    than 7 days of history. None until at least one recording has been
    processed locally."""
    import resource as _resource
    usage = _resource.getrusage(_resource.RUSAGE_SELF)
    server_memory_mb = round(usage.ru_maxrss / (1024 * 1024), 1)  # macOS reports bytes

    log_path = paths.LOGS_DIR / "local_pipeline_resource_usage.jsonl"
    runs: list[dict[str, Any]] = []
    if log_path.exists():
        try:
            for line in log_path.read_text().strip().splitlines():
                try:
                    runs.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            runs = []

    last_run = runs[-1] if runs else None

    cutoff = dt.datetime.now().astimezone() - dt.timedelta(days=7)
    recent_runs = []
    for run in runs:
        try:
            # strptime, not fromisoformat: log_resource_usage() writes
            # %z-style offsets ("+0530", no colon) via time.strftime, which
            # datetime.fromisoformat() rejects entirely on Python <3.11 —
            # silently threw out every single log entry here, until this
            # was actually tested against the real log file.
            logged_at = dt.datetime.strptime(run.get("logged_at", ""), "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            continue
        if logged_at >= cutoff:
            recent_runs.append(run)
    if not recent_runs and last_run:
        recent_runs = [last_run]  # no run within 7 days — still show the last one, not nothing

    speeds = [1 / rtf for run in recent_runs if (rtf := run.get("transcription_rtf"))]
    token_rates = [tps for run in recent_runs if (tps := (run.get("llm") or {}).get("tokens_per_second"))]

    return {
        "server_memory_mb": server_memory_mb,
        "last_processing_run": last_run,
        "stats_sample_size": len(recent_runs),
        "transcription_speed_x": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "tokens_per_second": round(sum(token_rates) / len(token_rates), 1) if token_rates else None,
    }


def available_models() -> dict[str, Any]:
    """What's already on disk vs. what would need a first-time download, so
    onboarding can show real state instead of guessing."""
    import local_meeting_pipeline
    whisper_options = [
        {
            "id": str(model["path"]),
            "label": model.get("label") or Path(model["path"]).name,
            "already_downloaded": True,
            "tradeoff": model.get("tradeoff", "Local model configured in config.json (local_whisper_models)."),
        }
        for model in local_meeting_pipeline.local_whisper_models()
    ]
    whisper_options.append({
        "id": "mlx-community/whisper-small-mlx",
        "label": "Public Whisper (small)",
        "already_downloaded": _hf_cache_has("mlx-community/whisper-small-mlx"),
        "tradeoff": "Works out of the box, no personal fine-tuning — good general accuracy.",
    })
    whisper_options.append({
        "id": "mayank-dubey-ai/whisper-large-v3-turbo-hinglish-mlx",
        "label": "Whisper Turbo Hinglish (public fine-tune)",
        "already_downloaded": _hf_cache_has("mayank-dubey-ai/whisper-large-v3-turbo-hinglish-mlx"),
        "tradeoff": "4-layer turbo decoder fine-tuned on Hindi-English speech — fast, no personal setup needed. For the deepest, most loop-resistant option see docs/RESEARCH.md on decoder depth.",
    })
    whisper_options.append({
        "id": "mayank-dubey-ai/tara-mlx",
        "label": "Tara (public fine-tune, recommended)",
        "already_downloaded": _hf_cache_has("mayank-dubey-ai/tara-mlx"),
        "tradeoff": "Full Whisper-large-v3 decoder (32 layers) fine-tuned on Hindi-English speech — the most accurate and loop-resistant option, at the cost of slower transcription than the turbo fine-tune above. See docs/RESEARCH.md on decoder depth.",
    })
    whisper_options.append({
        "id": "mlx-community/whisper-large-v3-mlx",
        "label": "Whisper large-v3 (full, general-purpose)",
        "already_downloaded": _hf_cache_has("mlx-community/whisper-large-v3-mlx"),
        "tradeoff": "Full-size, non-fine-tuned 32-layer decoder (~3.2GB, fp16) — best general accuracy if your meetings aren't Hindi-English specific. Slower than the turbo or quantized options above; best on 32GB+ Macs.",
    })
    liquid_options = [
        {**model, "already_downloaded": _hf_cache_has(model["id"])}
        for model in LOCAL_LLM_MODELS
    ]
    return {
        "whisper_options": whisper_options,
        "liquid_options": liquid_options,
        "selected_liquid_model": db.get_setting("liquid_model", LOCAL_LLM_MODELS[0]["id"]),
        "note": "Download a model ahead of time from here, or from the startup prompt — otherwise it downloads automatically the first time you process a recording.",
    }


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(default))


def save_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def safe_id(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", identifier or ""):
        raise ValueError("Invalid recording id")
    return identifier


def safe_folder(identifier: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", identifier or ""):
        raise ValueError("Invalid recording id")
    folder = (RECORDINGS / identifier).resolve()
    folder.relative_to(RECORDINGS.resolve())
    if not folder.is_dir():
        raise FileNotFoundError(identifier)
    return folder


_FILE_SIZE_TREE_EXCLUDE = {".venv", ".git", "__pycache__", "node_modules"}


def file_size_tree(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for base, dirs, files in os.walk(root):
        # Prune implementation directories (esp. .venv, which can be several
        # GB of installed packages) — this stat represents Cora's own data
        # footprint, not the app's runtime environment.
        dirs[:] = [d for d in dirs if d not in _FILE_SIZE_TREE_EXCLUDE]
        for filename in files:
            try:
                total += (Path(base) / filename).stat().st_size
            except OSError:
                pass
    return total
