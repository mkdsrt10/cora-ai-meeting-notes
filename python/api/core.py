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
from plugin_registry import get_coaching_plugin  # noqa: E402

# ARCHETYPES only exists when the coaching plugin is installed and enabled;
# with it absent/disabled this is just an empty dict, and every endpoint that
# does ARCHETYPES.get(...) below degrades to a no-op rather than an error.
ARCHETYPES = (get_coaching_plugin().ARCHETYPES if get_coaching_plugin() else {})

ARCHETYPE_OPTIONS = [
    {
        "id": "auto",
        "archetype_id": None,
        "label": "Auto-detect Archetype (Recommended)",
        "hat": "Cora Intelligence",
        "tip": "Cora analyzes meeting dynamics and selects the optimal coaching rubric.",
        "frequency": "Automatic"
    },
    {
        "id": "1",
        "archetype_id": 1,
        "label": "1 · Technical Steering & Architecture",
        "hat": "Chief Architect",
        "tip": "State verdict in first 15s · Bound by hard SLAs & token constraints · Assign spec owner",
        "frequency": "High (~50% of meetings)"
    },
    {
        "id": "4",
        "archetype_id": 4,
        "label": "4 · Strategic L10 & Cross-Functional",
        "hat": "Strategic Lead",
        "tip": "Keep airtime <15% · Translate technical bottlenecks to business impact · Strict IDS",
        "frequency": "High (~20% of meetings)"
    },
    {
        "id": "5",
        "archetype_id": 5,
        "label": "5 · Client Solutioning & Commercials",
        "hat": "Solution Strategist",
        "tip": "Anchor on client ROI · Defend scope & unit economics · Lock sign-off milestone",
        "frequency": "Frequent (~15% of meetings)"
    },
    {
        "id": "2",
        "archetype_id": 2,
        "label": "2 · Execution Control & Standup",
        "hat": "Operating Lead",
        "tip": "Target <15m · Airtime 20-30% · Parking Lot rule (<30s redirect) · Rule of 4",
        "frequency": "Frequent (~10% of meetings)"
    },
    {
        "id": "7",
        "archetype_id": 7,
        "label": "7 · Solo Ideation & Voice Memo",
        "hat": "Thought Partner",
        "tip": "Unconstrained flow · Auto-structures audio into Core Thesis, Dependencies & Spec",
        "frequency": "Specialized"
    },
    {
        "id": "3",
        "archetype_id": 3,
        "label": "3 · Talent Multiplication (1:1 Mentoring)",
        "hat": "Player-Coach",
        "tip": "Socratic questions > lecture (>=2:1) · Synthesis test (learner recaps plan in final 15%)",
        "frequency": "High leverage"
    },
    {
        "id": "6",
        "archetype_id": 6,
        "label": "6 · Talent Acquisition (Interviews)",
        "hat": "Technical Evaluator",
        "tip": "Candidate airtime >70% · 2-min pitch max · 3-level depth probing (Why? What broke?)",
        "frequency": "High stakes"
    },
    {
        "id": "8",
        "archetype_id": 8,
        "label": "8 · Content Creation & Loom",
        "hat": "Presenter",
        "tip": "Deliver core hook in first 10s · Zero filler tolerance · Crisp vocal energy",
        "frequency": "Asynchronous"
    },
]

if get_coaching_plugin() is None:
    # Without the coaching plugin, archetype selection is a no-op (ARCHETYPES
    # is empty) — only offer "auto" so the UI doesn't advertise a rubric list
    # that does nothing.
    ARCHETYPE_OPTIONS = [opt for opt in ARCHETYPE_OPTIONS if opt["id"] == "auto"]

MODE_LABELS = {opt["id"]: opt["label"] for opt in ARCHETYPE_OPTIONS}
MODE_LABELS.update({str(opt["archetype_id"]): opt["label"] for opt in ARCHETYPE_OPTIONS if opt["archetype_id"]})
MODE_LABELS.update({
    "free": "Auto-detect Archetype",
    "story": "Storytelling",
    "negotiation": "Negotiation",
    "direction": "Giving direction",
    "pronunciation": "Delivery practice",
})

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


def _config() -> dict[str, Any]:
    try:
        return json.loads(paths.CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def current_self_name() -> str | None:
    return db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name")


def scanner_executable() -> Path:
    """Optional helper .app that owns macOS Voice Memos access (config: scanner_app)."""
    return Path(_config().get("scanner_app") or "/Applications/Cora Scanner.app/Contents/MacOS/CoraScanner")


def scanner_command() -> list[str]:
    """Kickstart the LaunchAgent whose direct executable owns macOS access."""
    label = _config().get("scanner_launch_agent") or "ai.voicecoach.scanner"
    if not re.fullmatch(r"[A-Za-z0-9.-]+", label):
        raise ValueError("Invalid scanner_launch_agent label in config.json")
    return ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]


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
]


def _hf_cache_has(repo_id: str) -> bool:
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo_id.replace("/", "--"))
    return cache_dir.exists()


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
    liquid_options = [
        {**model, "already_downloaded": _hf_cache_has(model["id"])}
        for model in LOCAL_LLM_MODELS
    ]
    return {
        "whisper_options": whisper_options,
        "liquid_options": liquid_options,
        "selected_liquid_model": db.get_setting("liquid_model", LOCAL_LLM_MODELS[0]["id"]),
        "note": "Models download automatically the first time you process a recording if not already cached — no separate download step blocks setup.",
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
