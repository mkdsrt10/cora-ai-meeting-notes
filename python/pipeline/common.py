"""Small shared helpers: timestamps, progress reporting, slugs."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any



def format_ts(seconds: Any) -> str:
    if isinstance(seconds, str):
        return seconds
    s = int(seconds)
    m = s // 60
    sec = s % 60
    return f"{m:02d}:{sec:02d}"


def _parse_ts(mmss: str) -> float:
    """Reverse of format_ts, for shifting a continuation recording's segment
    timestamps onto the end of the meeting it continues (see
    _load_continuation_segments)."""
    try:
        m, sec = mmss.split(":", 1)
        return int(m) * 60 + int(sec)
    except (ValueError, AttributeError):
        return 0.0


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "section"


def _write_progress(folder: Path, stage: str, detail: str = "", percent: int = 0) -> None:
    """A lightweight heartbeat file so the UI can show real processing state
    instead of a static "Processing..." with no way to tell active work from
    a stall. Overwritten at each stage boundary; deleted once process_recording_local
    finishes."""
    try:
        (folder / ".pipeline_progress.json").write_text(json.dumps({
            "stage": stage,
            "detail": detail,
            "percent": percent,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "timestamp": time.time(),
        }))
    except Exception:
        pass
