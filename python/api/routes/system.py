"""Health, auth check, Finder integration."""
from __future__ import annotations
import subprocess

from api.router import route
import paths
import subprocess
from api.core import safe_folder


@route("GET", '/api/health')
def get_api_health(req, path: str, query: dict) -> None:
    return req.send_json({"ok": True, "service": "Cora"})


@route("GET", '/api/auth/check')
def get_api_auth_check(req, path: str, query: dict) -> None:
    return req.send_json({"ok": True})


@route("POST", '/api/open-folder')
def post_api_open_folder(req, path: str, body: dict) -> None:
    subprocess.run(["open", str(paths.DATA_DIR)], check=False)
    return req.send_json({"ok": True})


@route("POST", '/api/open-recording-folder')
def post_api_open_recording_folder(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    subprocess.run(["open", str(folder)], check=False)
    return req.send_json({"ok": True, "folder_path": str(folder.resolve())})
