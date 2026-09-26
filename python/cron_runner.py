#!/usr/bin/env python3
"""Silent cron wrapper for the Voice Memo pipeline.

Successful runs write only to local log files and produce no cron delivery.
Failures return non-zero so the caller can alert.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path

# Spawned by main.js, which itself inherits a minimal PATH when Cora is
# launched normally (Dock/Finder, not a terminal) — Homebrew's ffmpeg/ffprobe
# then aren't found by any bare "ffmpeg" subprocess call anywhere down this
# process tree (mlx_whisper's own internal audio loader does exactly that).
# subprocess.run(COMMAND) below has no explicit env=, so it inherits
# whatever's fixed here. See the matching fix in server.py for the fuller
# story — that's the process that actually calls mlx_whisper (and would
# fail on the exact same bare "ffmpeg" lookup for the exact same reason).
for _brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _brew_bin + os.pathsep + os.environ.get("PATH", "")

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

paths.ensure_data_dir()
ROOT = paths.APP_ROOT
LOG_DIR = paths.LOGS_DIR
LOG = LOG_DIR / "cron-pipeline.log"
ERR = LOG_DIR / "cron-pipeline-error.log"
COMMAND = [
    str(paths.venv_python()),
    str(paths.PYTHON_DIR / "voice_memo_pipeline.py"),
    "--once",
]

stamp = dt.datetime.now().astimezone().isoformat()
with LOG.open("a") as stdout, ERR.open("a") as stderr:
    stdout.write(f"\n[{stamp}] cron scan\n")
    stdout.flush()
    result = subprocess.run(COMMAND, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=900)

raise SystemExit(result.returncode)
