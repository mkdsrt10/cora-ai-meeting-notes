#!/usr/bin/env python3
"""Automated Cloud VM Synchronization Engine for Cora.

Syncs local meetings, transcripts, models, and training datasets to a developer-configured VM
over SSH/Tailscale with progress reporting and error handling.
"""

from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import time
from typing import Any, Dict

import paths

RECORDINGS_DIR = paths.RECORDINGS_DIR
DB_PATH = paths.DB_PATH
# Developer-only feature: copies raw meeting audio and the whole DB off the
# machine. There is deliberately no default target — it stays disabled until
# the `vm_sync_host` / `vm_sync_dir` settings are set locally, and the target
# is never taken from an API request body.
HOST_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,252}")
DIR_RE = re.compile(r"/[A-Za-z0-9._/-]{1,255}")


def configured_target() -> tuple[str, str] | None:
    import db
    import policy
    if policy.lockdown_enabled():
        return None
    host = str(db.get_setting("vm_sync_host", "") or "").strip()
    target_dir = str(db.get_setting("vm_sync_dir", "") or "").strip()
    if not (HOST_RE.fullmatch(host) and DIR_RE.fullmatch(target_dir)) or ".." in target_dir:
        return None
    return host, target_dir

_last_sync_status: Dict[str, Any] = {
    "active": False,
    "last_synced_at": None,
    "status": "idle",
    "message": "Ready to sync",
    "transferred_bytes": 0,
    "duration_seconds": 0.0,
}


def check_vm_reachability(host: str, timeout: int = 4) -> tuple[bool, str]:
    """Test SSH connection over Tailscale to the VM."""
    if not HOST_RE.fullmatch(host):
        return False, "Invalid host."
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}", "--", host, "echo ok"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if res.returncode == 0 and "ok" in res.stdout:
            return True, "VM is online and reachable over Tailscale."
        return False, res.stderr.strip() or "SSH connection failed."
    except Exception as exc:
        return False, str(exc)


def sync_to_vm(include_audio: bool = False, dry_run: bool = False) -> Dict[str, Any]:
    """Sync meetings, database, and datasets to the locally configured VM."""
    global _last_sync_status
    target = configured_target()
    if target is None:
        return {**_last_sync_status, "status": "disabled",
                "message": "VM sync is not configured (set vm_sync_host and vm_sync_dir)."}
    host, target_dir = target
    t0 = time.time()
    _last_sync_status["active"] = True
    _last_sync_status["status"] = "syncing"
    _last_sync_status["message"] = "Connecting to VM over Tailscale..."

    # 1. Reachability check
    is_online, err_msg = check_vm_reachability(host)
    if not is_online:
        _last_sync_status["active"] = False
        _last_sync_status["status"] = "offline"
        _last_sync_status["message"] = f"VM '{host}' is currently offline: {err_msg}"
        return _last_sync_status

    _last_sync_status["message"] = "Transferring meeting files and datasets..."

    # 2. Rsync command
    rsync = shutil.which("rsync") or "/usr/bin/rsync"
    exclude_args = [
        "--exclude=.DS_Store",
        "--exclude=node_modules",
        "--exclude=.venv",
        "--exclude=.git",
        "--exclude=backups",
    ]
    if not include_audio:
        exclude_args.extend(["--exclude=*.mov", "--exclude=*.wav", "--exclude=*.m4a"])

    cmd = [
        rsync,
        "-avz",
        *exclude_args,
        "--",
        f"{RECORDINGS_DIR}/",
        f"{host}:{target_dir}/",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        dur = round(time.time() - t0, 1)
        if proc.returncode != 0:
            _last_sync_status["active"] = False
            _last_sync_status["status"] = "error"
            _last_sync_status["message"] = f"Rsync error: {proc.stderr[:200]}"
            return _last_sync_status

        # Also sync database copy
        db_cmd = [rsync, "-avz", "--", str(DB_PATH), f"{host}:{target_dir}/voicecoach_sync.db"]
        subprocess.run(db_cmd, capture_output=True, text=True, check=False)

        _last_sync_status["active"] = False
        _last_sync_status["status"] = "success"
        _last_sync_status["last_synced_at"] = dt.datetime.now().astimezone().isoformat()
        _last_sync_status["duration_seconds"] = dur
        _last_sync_status["message"] = f"Synced successfully to {host} in {dur}s."
        return _last_sync_status

    except Exception as exc:
        _last_sync_status["active"] = False
        _last_sync_status["status"] = "error"
        _last_sync_status["message"] = str(exc)
        return _last_sync_status


def get_sync_status() -> Dict[str, Any]:
    return _last_sync_status
