"""Background Hugging Face model downloads with progress, for the Settings UI.

Separate from pipeline/: this is driven by API requests (a user clicking
"Download" or the startup "no model available" prompt), not by the
recording pipeline, and needs no MLX/Whisper import just to report progress.

Progress is tracked by polling how many bytes have actually landed in the
repo's cache directory (`~/.cache/huggingface/hub/.../blobs/`) against the
repo's known total size, rather than hooking huggingface_hub's tqdm
internals — those didn't report incremental byte progress for a plain
(non-Xet-chunked) file in testing, while summing the blobs directory
matches the reported total exactly and works regardless of which transfer
backend huggingface_hub picks.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_POLL_SECONDS = 0.5


def _set(repo_id: str, **fields: Any) -> None:
    with _lock:
        _jobs.setdefault(repo_id, {}).update(fields, _at=time.time())


def status(repo_id: str) -> dict[str, Any]:
    with _lock:
        job = dict(_jobs.get(repo_id, {"state": "idle"}))
    job["repo_id"] = repo_id
    return job


def _cache_dir(repo_id: str) -> Path:
    return Path.home() / ".cache" / "huggingface" / "hub" / ("models--" + repo_id.replace("/", "--"))


def _downloaded_bytes(repo_id: str) -> int:
    blobs = _cache_dir(repo_id) / "blobs"
    if not blobs.is_dir():
        return 0
    try:
        return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
    except OSError:
        return 0


def _repo_total_bytes(repo_id: str) -> int:
    from huggingface_hub import HfApi
    info = HfApi().model_info(repo_id, files_metadata=True)
    return sum((s.size or 0) for s in (info.siblings or []) if s.size)


def start(repo_id: str) -> dict[str, Any]:
    """Kick off a background download for repo_id. Safe to call repeatedly
    (e.g. the user clicks Download twice, or the startup check and Settings
    both want to trigger the same one) — a download already in flight is
    reused rather than duplicated."""
    with _lock:
        existing = _jobs.get(repo_id)
        if existing and existing.get("state") == "downloading":
            return dict(existing)
        _jobs[repo_id] = {"state": "downloading", "downloaded_bytes": 0, "total_bytes": 0, "error": None}
    threading.Thread(target=_run, args=(repo_id,), daemon=True).start()
    return status(repo_id)


def _run(repo_id: str) -> None:
    from huggingface_hub import snapshot_download

    stop = threading.Event()

    def poll() -> None:
        while not stop.wait(_POLL_SECONDS):
            _set(repo_id, downloaded_bytes=_downloaded_bytes(repo_id))

    poller = threading.Thread(target=poll, daemon=True)
    try:
        try:
            total = _repo_total_bytes(repo_id)
            _set(repo_id, total_bytes=total)
        except Exception as exc:
            # Size lookup failing (offline, rate-limited) shouldn't block the
            # download itself — progress just won't have a known total.
            print(f"[download_manager] Could not fetch size for {repo_id}: {exc}", flush=True)
        poller.start()
        snapshot_download(repo_id=repo_id)
        stop.set()
        poller.join(timeout=2)
        _set(repo_id, state="done", downloaded_bytes=_downloaded_bytes(repo_id))
    except Exception as exc:
        stop.set()
        _set(repo_id, state="error", error=str(exc))
        print(f"[download_manager] Download failed for {repo_id}: {exc}", flush=True)


def prune(max_age_seconds: int = 3600) -> None:
    """Drop finished/errored job records older than max_age_seconds so the
    in-memory dict doesn't grow forever across a long server lifetime."""
    cutoff = time.time() - max_age_seconds
    with _lock:
        for repo_id in [k for k, v in _jobs.items() if v.get("state") in ("done", "error") and v.get("_at", 0) < cutoff]:
            del _jobs[repo_id]
