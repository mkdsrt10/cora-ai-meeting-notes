"""Crash reports of Cora's own processes, as crash_report Usage events.

At server start (python/server.py, on a thread) this scans
~/Library/Logs/DiagnosticReports for macOS .ips reports of our binaries
(dual-capture, speaker-watch, mic-watch, mac-ocr, the Cora app and its
helpers, and our bundled Python runtime) written since the last check
(setting crash_reports_checked_at; the first check looks back
FIRST_LOOKBACK_DAYS so a first-day crash is still seen). One event per
report: process, exception_type, signal, termination_reason and frames,
the top FRAMES symbol names from the crashing thread that are in OUR
images. Never a path, an address, a thread name or any other part of the
report (a report can hold a window title or a user name in a path).

Electron's crashReporter (minidump upload) is deliberately not used:
minidumps carry process memory, which can hold transcript text or names.
See docs/DIAGNOSTICS.md.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional

import db
import usage_events

SETTING = "crash_reports_checked_at"
FIRST_LOOKBACK_DAYS = 7
FRAMES = 5
REPORTS_DIR = Path.home() / "Library" / "Logs" / "DiagnosticReports"
HELPERS = ("dual-capture", "speaker-watch", "mic-watch", "mac-ocr")
APP_NAME = "Cora AI Meeting Notes"
BUNDLE_MARK = f"{APP_NAME}.app/"


def _ours(proc_name: str, proc_path: str) -> bool:
    if proc_name in HELPERS or proc_name.startswith(APP_NAME):
        return True
    # Our bundled CPython: only when it ran from inside the app bundle.
    return proc_name.lower().startswith("python") and BUNDLE_MARK in (proc_path or "")


def _candidate(path: Path) -> bool:
    name = path.name
    if path.suffix != ".ips":
        return False
    return name.startswith(HELPERS) or name.startswith(APP_NAME) or name.lower().startswith("python")


def _clean(text: Any, limit: int = 200) -> Optional[str]:
    """A short string with nothing path-like left in it."""
    if text is None:
        return None
    text = " ".join(str(text).split())
    text = re.sub(r"\S*/\S*", "", text).strip()
    return text[:limit] or None


def parse(text: str) -> Optional[dict[str, Any]]:
    """An .ips report (a JSON header line, then a JSON body) -> the
    crash_report payload, or None if it is not one of ours or unreadable."""
    try:
        header_line, body_text = text.split("\n", 1)
        header = json.loads(header_line)
        body = json.loads(body_text)
    except (ValueError, TypeError):
        return None
    proc_name = str(body.get("procName") or header.get("app_name") or header.get("name") or "")
    if not _ours(proc_name, str(body.get("procPath") or "")):
        return None
    exception = body.get("exception") or {}
    termination = body.get("termination") or {}
    images = body.get("usedImages") or []
    ours = set()
    for index, image in enumerate(images):
        name, image_path = str(image.get("name") or ""), str(image.get("path") or "")
        if name in HELPERS or name.startswith(APP_NAME) or BUNDLE_MARK in image_path:
            ours.add(index)
    threads = body.get("threads") or []
    crashed = next((t for t in threads if t.get("triggered")), None)
    if crashed is None:
        faulting = body.get("faultingThread")
        crashed = threads[faulting] if isinstance(faulting, int) and 0 <= faulting < len(threads) else {}
    frames = [str(f.get("symbol")) for f in crashed.get("frames") or []
              if f.get("imageIndex") in ours and f.get("symbol")][:FRAMES]
    reason = termination.get("indicator") or (
        f"{termination.get('namespace')} {termination.get('code')}" if termination.get("namespace") else None)
    return {
        "process": _clean(proc_name, 100),
        "exception_type": _clean(exception.get("type"), 60),
        "signal": _clean(exception.get("signal"), 30),
        "termination_reason": _clean(reason),
        "frames": " | ".join(_clean(f, 120) or "?" for f in frames)[:500] or None,
    }


def _reports(directory: Path, since: float) -> Iterator[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for path in entries:
        try:
            if path.is_file() and _candidate(path) and path.stat().st_mtime > since:
                yield path
        except OSError:
            continue


def scan(directory: Optional[Path] = None, now: Optional[float] = None) -> int:
    """Emit one crash_report per new report of ours; returns how many."""
    directory = directory or REPORTS_DIR
    now = time.time() if now is None else now
    since = db.get_setting(SETTING)
    since = float(since) if isinstance(since, (int, float)) else now - FIRST_LOOKBACK_DAYS * 86400
    emitted = 0
    for path in _reports(directory, since):
        try:
            payload = parse(path.read_text(errors="replace"))
        except OSError:
            continue
        if payload is None:
            continue
        try:
            usage_events.record("crash_report", payload)
            emitted += 1
        except ValueError as exc:
            print(f"[crash_reports] report skipped: {exc}", flush=True)
    db.set_setting(SETTING, now)
    return emitted
