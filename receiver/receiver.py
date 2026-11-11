#!/usr/bin/env python3
"""Cora beta receiver: one process and a directory.

    CORA_RECEIVER_TOKEN=... python3 receiver/receiver.py --root DIR --port N

Python standard library only. See receiver/README.md for the wire protocol,
disk layout and deployment (launchd + tailscale funnel)."""
import argparse
import hmac
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BATCH_FIELDS = ("install_id", "display_name", "app_version", "git_commit", "build_variant")
APPEND_LOCK = threading.Lock()
MAX_EVENTS_BYTES = 16 * 1024 * 1024  # the sender caps a batch at 5 MB
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3

DEFAULT_CONFIG = {
    "telemetry_enabled": True,
    "capture_sample_rate": 0.25,
    "capture_max_minutes": 60,
    "min_app_version": None,
}


class Handler(BaseHTTPRequestHandler):
    root: Path
    token: str

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/config":
            return self.get_config()
        self.send_json({"error": "not found"}, 404)

    def authorized(self):
        given = self.headers.get("Authorization", "")
        return hmac.compare_digest(given.encode(), f"Bearer {self.token}".encode())

    def do_POST(self):
        if self.path not in ("/v1/events", "/v1/recordings"):
            return self.send_json({"error": "not found"}, 404)
        if not self.authorized():
            self.close_connection = True  # never read an unauthenticated body
            return self.send_json({"error": "bad token"}, 401)
        if self.path == "/v1/events":
            return self.post_events()
        self.send_json({"error": "not found"}, 404)

    def body_length(self, limit):
        """Declared body length, or None after answering 400/413 (the body is then never read)."""
        try:
            length = int(self.headers.get("Content-Length", ""))
            if length < 0:
                raise ValueError
        except ValueError:
            self.close_connection = True
            self.send_json({"error": "Content-Length required"}, 400)
            return None
        if length > limit:
            self.close_connection = True
            self.send_json({"error": f"body over {limit} bytes"}, 413)
            return None
        return length

    def post_events(self):
        length = self.body_length(MAX_EVENTS_BYTES)
        if length is None:
            return
        try:
            batch = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(batch, dict):
                raise ValueError("batch must be an object")
            if not isinstance(batch.get("install_id"), str) or not batch["install_id"]:
                raise ValueError("install_id required")
            if not isinstance(batch.get("events"), list) or not all(isinstance(e, dict) for e in batch["events"]):
                raise ValueError("events must be a list of objects")
        except ValueError as e:  # includes JSONDecodeError and UnicodeDecodeError
            return self.send_json({"error": f"malformed batch: {e}"}, 400)
        now = datetime.now(timezone.utc)
        stamp = {k: batch.get(k) for k in BATCH_FIELDS}
        stamp["received_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        lines = "".join(json.dumps({**e, **stamp}) + "\n" for e in batch["events"])
        if lines:
            day_file = self.root / "events" / f"{now:%Y-%m-%d}.jsonl"
            day_file.parent.mkdir(exist_ok=True)
            with APPEND_LOCK, open(day_file, "a") as f:
                f.write(lines)
        self.send_json({"accepted": len(batch["events"])}, 202)

    def get_config(self):
        path = self.root / "config.json"
        try:
            overrides = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(overrides, dict):
                raise ValueError("config.json must hold an object")
        except ValueError as e:
            return self.send_json({"error": f"config.json unreadable: {e}"}, 500)
        self.send_json({**DEFAULT_CONFIG, **overrides})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token-env", default="CORA_RECEIVER_TOKEN")
    args = ap.parse_args(argv)
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(f"receiver: set the bearer token in ${args.token_env}", file=sys.stderr)
        return 2
    args.root.mkdir(parents=True, exist_ok=True)
    handler = type("BoundHandler", (Handler,), {"root": args.root, "token": token})
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
