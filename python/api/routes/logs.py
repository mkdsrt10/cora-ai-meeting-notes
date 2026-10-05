"""Notification history and on-disk log visibility/export.

Notifications disappear from Notification Center within seconds, and the
pipeline's own logs (cron-pipeline.log, speaker-watch-*.log, etc.) only ever
lived as flat files nobody looked at unless something had already gone
wrong badly enough to go digging manually. This gives the app itself a way
to show "what happened and when", and an explicit, opt-in way to hand a
bundle of that to a support/debug server — never automatic, never without
the user choosing to do it.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from api.router import route
import db
import paths
import policy

LOGS_DIR = paths.LOGS_DIR

# Files worth bundling/sending by default — the small, high-signal ones.
# speaker-watch-*.log files are per-meeting and can run into the tens of MB
# (verbose accessibility-tree polling), so they're listed individually but
# left out of the default bundle; a specific one can still be fetched via
# GET /api/logs/file.
DEFAULT_BUNDLE_FILES = ("cron-pipeline.log", "cron-pipeline-error.log", "local_pipeline_resource_usage.jsonl")

MAX_TAIL_BYTES = 512_000  # 500KB — plenty for recent context, never a multi-MB dump into the UI


def _safe_log_name(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
        raise ValueError("Invalid log file name")
    path = (LOGS_DIR / name).resolve()
    path.relative_to(LOGS_DIR.resolve())
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def _tail_bytes(path: Path, max_bytes: int = MAX_TAIL_BYTES) -> str:
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    return data.decode("utf-8", errors="replace")


@route("GET", "/api/notifications")
def get_api_notifications(req, path: str, query: dict) -> None:
    limit = int((query.get("limit") or ["200"])[0])
    return req.send_json({"notifications": db.get_notifications(limit=min(limit, 1000))})


@route("POST", "/api/notifications/log")
def post_api_notifications_log(req, path: str, body: dict) -> None:
    db.log_notification(
        title=str(body.get("title") or ""),
        body=str(body.get("body") or ""),
        level=str(body.get("level") or "info"),
        recording_id=(str(body.get("recording_id")) if body.get("recording_id") else None),
    )
    return req.send_json({"ok": True})


@route("GET", "/api/logs")
def get_api_logs(req, path: str, query: dict) -> None:
    if not LOGS_DIR.is_dir():
        return req.send_json({"files": []})
    files = []
    for p in LOGS_DIR.iterdir():
        if not p.is_file():
            continue
        stat = p.stat()
        files.append({
            "name": p.name,
            "size_bytes": stat.st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(stat.st_mtime)),
            "is_error_log": "error" in p.name.lower(),
        })
    files.sort(key=lambda f: f["modified_at"], reverse=True)
    return req.send_json({"files": files})


@route("GET", "/api/logs/file")
def get_api_logs_file(req, path: str, query: dict) -> None:
    name = (query.get("name") or [""])[0]
    file_path = _safe_log_name(name)
    return req.send_json({
        "name": name,
        "size_bytes": file_path.stat().st_size,
        "truncated": file_path.stat().st_size > MAX_TAIL_BYTES,
        "content": _tail_bytes(file_path),
    })


def _build_bundle() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("notifications.json", json.dumps(db.get_notifications(limit=1000), indent=2))
        for name in DEFAULT_BUNDLE_FILES:
            file_path = LOGS_DIR / name
            if file_path.is_file():
                zf.writestr(name, _tail_bytes(file_path, max_bytes=2_000_000))
    return buf.getvalue()


@route("POST", "/api/logs/bundle")
def post_api_logs_bundle(req, path: str, body: dict) -> None:
    body = body or {}
    bundle = _build_bundle()
    exports_dir = paths.DATA_DIR / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out_path = exports_dir / f"cora-logs-{stamp}.zip"
    out_path.write_bytes(bundle)

    send = bool(body.get("send"))
    result: dict[str, Any] = {"ok": True, "saved_to": str(out_path), "size_bytes": len(bundle), "sent": False}
    if not send:
        return req.send_json(result)

    upload_url = db.get_setting("log_upload_url") or ""
    if not upload_url:
        result["ok"] = False
        result["error"] = "No log upload server configured — set one in Settings first."
        return req.send_json(result, 400)
    try:
        policy.require_outbound_allowed("Log upload")
    except policy.LockdownError as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return req.send_json(result, 403)

    try:
        resp = requests.post(
            upload_url,
            files={"bundle": (out_path.name, bundle, "application/zip")},
            timeout=30,
        )
        resp.raise_for_status()
        result["sent"] = True
    except requests.RequestException as exc:
        result["ok"] = False
        result["error"] = f"Upload failed: {exc}"
        return req.send_json(result, 502)
    return req.send_json(result)
