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
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Cora: http://{args.host}:{args.port}", flush=True)
    # Electron stops the server with SIGTERM (pythonProcess.kill()); turn it
    # into the same clean exit as Ctrl-C so the beta sender's final flush runs.
    signal.signal(signal.SIGTERM, _raise_keyboard_interrupt)
    import usage_events
    usage_events.seed_display_name()  # beta builds, once: name teammates who onboarded before 0.4.4
    import threading
    threading.Thread(target=_backfill_identity, name="identity-backfill", daemon=True).start()
    threading.Thread(target=_scan_crash_reports, name="crash-reports", daemon=True).start()
    import beta_sender
    # The port is bound; the daily people_snapshot (a walk of the Recordings
    # folder), the config fetch and the first flush all run on its thread.
    beta_sender.start()
    import audio_pruning
    audio_pruning.start()  # first pass now on its thread, then after each job and every 6 h
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        audio_pruning.stop()
        beta_sender.stop(final_flush=True)


def _scan_crash_reports() -> None:
    """Our processes' macOS crash reports since the last check, as
    crash_report Usage events (python/crash_reports.py)."""
    try:
        import crash_reports
        found = crash_reports.scan()
        if found:
            print(f"[crash_reports] {found} crash report(s) recorded", flush=True)
    except Exception as e:  # noqa: BLE001 - never stops the server
        print(f"[crash_reports] scan failed: {type(e).__name__}: {e}", flush=True)


def _backfill_identity() -> None:
    """0.4.5, once per Install: Recordings Cora captured before then get the
    mic-track identity, so they stop asking which speaker is you."""
    try:
        from pipeline.speakers import backfill_mic_track_identity
        written = backfill_mic_track_identity()
        if written:
            print(f"[identity] mic-track identity written for {written} earlier Recording(s)", flush=True)
    except Exception as e:  # noqa: BLE001 - a backfill must never stop the server
        print(f"[identity] backfill failed: {type(e).__name__}: {e}", flush=True)


def _raise_keyboard_interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
