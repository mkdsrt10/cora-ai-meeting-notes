#!/usr/bin/env python3
"""Local-only web server for Cora's dashboard — entry point.

The API itself lives in the `api` package (see api/__init__.py for the map).
This module fixes up the process environment and starts the server.
"""
from __future__ import annotations

import os
import signal
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# A macOS app launched normally (Dock, Finder double-click, LaunchServices —
# not a terminal) inherits a minimal PATH that excludes Homebrew
# (/opt/homebrew/bin on Apple Silicon, /usr/local/bin on Intel). Our own
# ffmpeg/ffprobe subprocess calls all fall back to an absolute path when
# shutil.which() comes up empty, but mlx_whisper's OWN internal audio loader
# shells out to a bare "ffmpeg" with no such fallback — so transcription
# silently failed on every recording whenever Cora wasn't launched from a
# terminal, with no way to tell from a plain subprocess.run() error. Fixing
# PATH here, before anything else in this process can shell out, covers
# every such call for the rest of the process's life. Appended, not
# prepended: the release app puts its bundled ffmpeg first on PATH.
for _brew_bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_bin not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + _brew_bin

sys.path.insert(0, str(Path(__file__).resolve().parent))
import credentials  # noqa: E402
import paths  # noqa: E402
from api.auth import LOOPBACK_HOSTS, init_api_token  # noqa: E402
from api.core import STATIC  # noqa: E402
from api.http import Handler  # noqa: E402,F401  (re-exported for tests/tools)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    paths.ensure_data_dir()
    import ai_trace
    ai_trace.prune()
    if args.host not in LOOPBACK_HOSTS:
        parser.error("--host must be a loopback address; the API is not safe to expose on a network")
    init_api_token()
    STATIC.mkdir(parents=True, exist_ok=True)
    credentials._sanitize_db()
    import usage_emitters
    usage_emitters.people_snapshot_if_due()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Cora: http://{args.host}:{args.port}", flush=True)
    # Electron stops the server with SIGTERM (pythonProcess.kill()); turn it
    # into the same clean exit as Ctrl-C so the beta sender's final flush runs.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    import beta_sender
    beta_sender.start()  # the port is bound; config fetch and first flush run on its thread
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        beta_sender.stop(final_flush=True)


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
