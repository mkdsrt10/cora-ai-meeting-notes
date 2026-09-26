"""Local, private trace of every AI call Cora makes.

Each Whisper transcription, local/cloud LLM call, Gemini request and OCR
pass is recorded as a *span* — inputs, outputs, timing, token usage,
throughput, memory — grouped into *runs* (one pipeline execution over one
recording) and stamped with every version that could explain a change in
behaviour: app version + git commit, pipeline version, model id + resolved
weights revision, and a hash of the prompt template.

That makes the store useful for two things:
  * retraining — input/output pairs per model and prompt version
    (see `tools/traces.py export`);
  * benchmarking — latency, tokens/s, real-time factor and peak memory
    per model/version/hardware (see `tools/traces.py stats`).

Everything stays on this Mac in DATA_DIR/traces.db (0600, same privacy as the
recordings themselves). Nothing is sent anywhere; Langfuse (tracing.py) is a
separate, opt-in mirror. Config (config.json → "local_tracing"):
  {"enabled": true, "store_payloads": true, "retention_days": 180}
With store_payloads false, only metrics and versions are kept.

Tracing must never break the pipeline: every write is best-effort.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Optional

import paths

TRACE_DB = paths.TRACES_DB
# Bump when the pipeline's structure changes in a way that affects outputs
# (new stages, different chunking, prompt restructuring).
PIPELINE_VERSION = "2026.09.1"
MAX_PAYLOAD_CHARS = 2_000_000

_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("ai_trace_run", default=None)
_recording_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("ai_trace_recording", default=None)
_span_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("ai_trace_span", default=None)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    pipeline TEXT NOT NULL,
    recording_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    duration_s REAL,
    status TEXT,
    error TEXT,
    app_version TEXT,
    git_commit TEXT,
    git_dirty INTEGER,
    pipeline_version TEXT,
    hardware TEXT,
    settings TEXT,
    meta TEXT
);
CREATE TABLE IF NOT EXISTS spans (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    parent_id TEXT,
    recording_id TEXT,
    kind TEXT NOT NULL,            -- transcription | llm | ocr | ...
    name TEXT NOT NULL,            -- e.g. enhanced_notes.action_items
    provider TEXT,                 -- mlx | anthropic | openai | custom | gemini | apple_vision
    model TEXT,
    model_revision TEXT,
    prompt_id TEXT,
    prompt_hash TEXT,
    started_at REAL NOT NULL,
    duration_s REAL,
    status TEXT,
    error TEXT,
    input TEXT,
    output TEXT,
    params TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    prompt_tps REAL,
    generation_tps REAL,
    tokens_per_s REAL,
    audio_s REAL,
    rtf REAL,
    peak_memory_mb REAL,
    metrics TEXT
);
CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id);
CREATE INDEX IF NOT EXISTS spans_kind_model ON spans(kind, model, model_revision, prompt_hash);
CREATE INDEX IF NOT EXISTS spans_recording ON spans(recording_id);
CREATE INDEX IF NOT EXISTS runs_recording ON runs(recording_id);
-- Human corrections to AI output (speaker labels, transcript text): the
-- highest-value retraining signal. start/end locate the audio slice.
CREATE TABLE IF NOT EXISTS corrections (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL,
    segment_index INTEGER,
    field TEXT NOT NULL,           -- speaker | text
    before TEXT,
    after TEXT,
    segment_start TEXT,
    segment_end TEXT,
    source_model TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS corrections_recording ON corrections(recording_id);
"""


# --- configuration --------------------------------------------------------

def _settings() -> dict[str, Any]:
    try:
        cfg = json.loads(paths.CONFIG_PATH.read_text()).get("local_tracing") or {}
    except (OSError, ValueError):
        cfg = {}
    return {"enabled": True, "store_payloads": True, "retention_days": 180, **cfg}


def enabled() -> bool:
    return bool(_settings()["enabled"])


# --- storage ---------------------------------------------------------------

_schema_ready = False


def _connect() -> sqlite3.Connection:
    global _schema_ready
    new = not TRACE_DB.exists()
    conn = sqlite3.connect(TRACE_DB, timeout=10)
    if new:
        TRACE_DB.chmod(0o600)
    if not _schema_ready:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _schema_ready = True
    return conn


def _write(sql: str, params: tuple) -> None:
    try:
        with _connect() as conn:
            conn.execute(sql, params)
    except Exception as exc:  # never let tracing break a pipeline
        print(f"[ai_trace] write failed: {exc}", file=sys.stderr)


def _json(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = json.dumps(to_jsonable(value), ensure_ascii=False, default=str)
    if len(text) > MAX_PAYLOAD_CHARS:
        text = json.dumps({"truncated": True, "original_chars": len(text), "head": text[:MAX_PAYLOAD_CHARS]})
    return text


def to_jsonable(value: Any, depth: int = 0) -> Any:
    """Make SDK objects storable without ever persisting raw audio/image bytes."""
    if depth > 12:
        return repr(value)[:200]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        data = bytes(value)
        return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v, depth + 1) for v in value]
    if hasattr(value, "model_dump"):  # pydantic (google-genai types)
        try:
            return to_jsonable(value.model_dump(exclude_none=True), depth + 1)
        except Exception:
            pass
    if hasattr(value, "tolist"):  # numpy / mlx arrays
        try:
            return f"<array shape={getattr(value, 'shape', '?')}>"
        except Exception:
            pass
    return repr(value)[:2000]


# --- versions & environment -------------------------------------------------

@lru_cache(maxsize=1)
def app_versions() -> dict[str, Any]:
    info: dict[str, Any] = {"app_version": None, "git_commit": None, "git_dirty": None}
    try:
        info["app_version"] = json.loads((paths.APP_ROOT / "package.json").read_text()).get("version")
    except (OSError, ValueError):
        pass
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=paths.APP_ROOT, capture_output=True, text=True, timeout=3)
        if commit.returncode == 0:
            info["git_commit"] = commit.stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=paths.APP_ROOT,
                                   capture_output=True, text=True, timeout=5)
            info["git_dirty"] = int(bool(dirty.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return info


@lru_cache(maxsize=1)
def hardware() -> dict[str, Any]:
    def sysctl(key: str) -> str:
        try:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    mem = sysctl("hw.memsize")
    return {
        "chip": sysctl("machdep.cpu.brand_string") or platform.processor(),
        "memory_gb": round(int(mem) / 2**30) if mem.isdigit() else None,
        "cpu_cores": sysctl("hw.ncpu"),
        "macos": platform.mac_ver()[0],
        "python": platform.python_version(),
    }


@lru_cache(maxsize=64)
def model_revision(model: str) -> Optional[str]:
    """Pin down exactly which weights ran: the HF snapshot commit for a repo
    id, or a fingerprint of config + weight files for a local checkpoint."""
    if not model:
        return None
    local = Path(model).expanduser()
    if local.exists():
        digest = hashlib.sha256()
        for f in sorted(local.glob("*")):
            if f.suffix in {".json", ".safetensors", ".npz", ".bin"}:
                stat = f.stat()
                digest.update(f"{f.name}:{stat.st_size}:{int(stat.st_mtime)}".encode())
                if f.name == "config.json":
                    digest.update(f.read_bytes())
        return "local:" + digest.hexdigest()[:16]
    if "/" in model:
        ref = Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + model.replace("/", "--")) / "refs" / "main"
        try:
            return "hf:" + ref.read_text().strip()
        except OSError:
            return None
    return None


def prompt_hash(template: Optional[str]) -> Optional[str]:
    return hashlib.sha256(template.encode()).hexdigest()[:16] if template else None


def file_fingerprint(path: Path | str) -> dict[str, Any]:
    """Identify an input file (audio/image) without storing its contents."""
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return {"path": str(p)}
    digest = hashlib.sha256()
    with p.open("rb") as handle:  # head+tail hash: fast on multi-GB audio
        digest.update(handle.read(1 << 20))
        if stat.st_size > 2 << 20:
            handle.seek(-(1 << 20), 2)
            digest.update(handle.read())
    info: dict[str, Any] = {"path": str(p), "bytes": stat.st_size, "sha256_headtail": digest.hexdigest()}
    if p.suffix.lower() == ".wav":
        try:
            import wave
            with wave.open(str(p)) as w:
                info["duration_s"] = round(w.getnframes() / float(w.getframerate()), 3)
        except Exception:
            pass
    return info


# --- runs & spans ---------------------------------------------------------

@contextmanager
def run(pipeline: str, recording_id: Optional[str] = None, **meta: Any) -> Iterator[Optional[str]]:
    """Group every span inside this block under one pipeline run."""
    if not enabled():
        yield None
        return
    run_id = uuid.uuid4().hex
    started = time.time()
    versions = app_versions()
    _write(
        "INSERT INTO runs (id, pipeline, recording_id, started_at, status, app_version, git_commit, git_dirty,"
        " pipeline_version, hardware, settings, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, pipeline, recording_id, started, "running", versions["app_version"], versions["git_commit"],
         versions["git_dirty"], PIPELINE_VERSION, _json(hardware()), _json(_pipeline_settings()), _json(meta or None)),
    )
    run_token, rec_token = _run_id.set(run_id), _recording_id.set(recording_id)
    status, error = "ok", None
    try:
        yield run_id
    except BaseException as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _run_id.reset(run_token)
        _recording_id.reset(rec_token)
        ended = time.time()
        _write("UPDATE runs SET ended_at=?, duration_s=?, status=?, error=? WHERE id=?",
               (ended, round(ended - started, 3), status, error, run_id))


def _pipeline_settings() -> dict[str, Any]:
    """The knobs that change model behaviour, snapshotted per run."""
    try:
        import db
        keys = ("whisper_model_choice", "liquid_model", "notes_llm_provider", "transcription_engine")
        out = {k: db.get_setting(k) for k in keys}
    except Exception:
        out = {}
    try:
        cfg = json.loads(paths.CONFIG_PATH.read_text())
        out.update({k: cfg.get(k) for k in ("whisper_model", "language", "silence_threshold_db", "silence_min_gap_seconds")})
    except (OSError, ValueError):
        pass
    return out


class Span:
    """Handle yielded by `span()`; fill in outputs and metrics as they're known."""

    def __init__(self) -> None:
        self.output: Any = None
        self.input_tokens: Optional[int] = None
        self.output_tokens: Optional[int] = None
        self.prompt_tps: Optional[float] = None
        self.generation_tps: Optional[float] = None
        self.audio_s: Optional[float] = None
        self.peak_memory_mb: Optional[float] = None
        self.model: Optional[str] = None
        self.metrics: dict[str, Any] = {}

    def set_output(self, output: Any, **metrics: Any) -> None:
        self.output = output
        self.set(**metrics)

    def set(self, **metrics: Any) -> None:
        for key, value in metrics.items():
            if hasattr(self, key) and key not in {"output", "metrics"}:
                setattr(self, key, value)
            else:
                self.metrics[key] = value


@contextmanager
def span(kind: str, name: str, *, provider: str, model: Optional[str] = None, input: Any = None,
         params: Optional[dict[str, Any]] = None, prompt_template: Optional[str] = None,
         prompt_id: Optional[str] = None, recording_id: Optional[str] = None) -> Iterator[Span]:
    """Record one AI call. Exceptions are recorded and re-raised."""
    handle = Span()
    if not enabled():
        yield handle
        return
    store = bool(_settings()["store_payloads"])
    span_id = uuid.uuid4().hex
    parent = _span_id.get()
    token = _span_id.set(span_id)
    _reset_mlx_peak()
    started_wall, t0 = time.time(), time.perf_counter()
    status, error = "ok", None
    try:
        yield handle
    except BaseException as exc:
        status, error = "error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _span_id.reset(token)
        duration = time.perf_counter() - t0
        model_name = handle.model or model
        peak = handle.peak_memory_mb if handle.peak_memory_mb is not None else _mlx_peak_mb(provider)
        tokens_per_s = round(handle.output_tokens / duration, 2) if handle.output_tokens and duration > 0 else None
        rtf = round(duration / handle.audio_s, 4) if handle.audio_s else None
        _write(
            "INSERT INTO spans (id, run_id, parent_id, recording_id, kind, name, provider, model, model_revision,"
            " prompt_id, prompt_hash, started_at, duration_s, status, error, input, output, params, input_tokens,"
            " output_tokens, prompt_tps, generation_tps, tokens_per_s, audio_s, rtf, peak_memory_mb, metrics)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (span_id, _run_id.get(), parent, recording_id or _recording_id.get(), kind, name, provider, model_name,
             model_revision(model_name or ""), prompt_id or name, prompt_hash(prompt_template), started_wall,
             round(duration, 4), status, error, _json(input) if store else None,
             _json(handle.output) if store else None, _json(params), handle.input_tokens, handle.output_tokens,
             handle.prompt_tps, handle.generation_tps, tokens_per_s, handle.audio_s, rtf, peak,
             _json(handle.metrics or None)),
        )


def _reset_mlx_peak() -> None:
    mx = sys.modules.get("mlx.core")
    if mx is not None:
        try:
            mx.reset_peak_memory()
        except Exception:
            pass


def _mlx_peak_mb(provider: str) -> Optional[float]:
    mx = sys.modules.get("mlx.core")
    if provider != "mlx" or mx is None:
        return None
    try:
        return round(mx.get_peak_memory() / 2**20, 1)
    except Exception:
        return None


def record_correction(recording_id: str, segment_index: Optional[int], field: str, before: Any, after: Any,
                      segment_start: Optional[str] = None, segment_end: Optional[str] = None,
                      source_model: Optional[str] = None) -> None:
    """Log a human fix to AI output. It contains transcript text, so it is
    only kept when payload storage is on (the default)."""
    if not enabled() or not _settings()["store_payloads"]:
        return
    _write(
        "INSERT INTO corrections (id, recording_id, segment_index, field, before, after, segment_start, segment_end,"
        " source_model, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, recording_id, segment_index, field, _json(before), _json(after), segment_start,
         segment_end, source_model, time.time()),
    )


# --- maintenance ------------------------------------------------------------

def prune(retention_days: Optional[int] = None) -> int:
    """Delete traces older than the retention window. Returns spans removed."""
    days = retention_days if retention_days is not None else int(_settings()["retention_days"])
    if days <= 0 or not TRACE_DB.exists():
        return 0
    cutoff = time.time() - days * 86400
    try:
        with _connect() as conn:
            removed = conn.execute("DELETE FROM spans WHERE started_at < ?", (cutoff,)).rowcount
            conn.execute("DELETE FROM runs WHERE started_at < ?", (cutoff,))
        return removed
    except Exception as exc:
        print(f"[ai_trace] prune failed: {exc}", file=sys.stderr)
        return 0


def purge_recording(recording_id: str) -> None:
    """Remove every trace for a recording (call when the recording is deleted)."""
    if not TRACE_DB.exists():
        return
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM spans WHERE recording_id = ?", (recording_id,))
            conn.execute("DELETE FROM runs WHERE recording_id = ?", (recording_id,))
            conn.execute("DELETE FROM corrections WHERE recording_id = ?", (recording_id,))
    except Exception as exc:
        print(f"[ai_trace] purge failed: {exc}", file=sys.stderr)
