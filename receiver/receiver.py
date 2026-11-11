#!/usr/bin/env python3
"""Cora beta receiver: one process and a directory.

    CORA_RECEIVER_TOKEN=... python3 receiver/receiver.py --root DIR --port N

Python standard library only. Endpoints (bearer token on the POSTs):
  POST /v1/events      batch -> one line per event in <root>/events/YYYY-MM-DD.jsonl
  POST /v1/recordings  tar.gz -> <root>/recordings/<install>/<recording>/{archive.tar.gz,meta.json}
  GET  /v1/config      <root>/config.json over the defaults, re-read per request
Every request is logged to <root>/logs/receiver.jsonl. Archives are streamed to
disk and never opened. See receiver/README.md for deployment."""
import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_CONFIG = {
    "telemetry_enabled": True,
    "capture_sample_rate": 0.25,
    "capture_max_minutes": 60,
    "min_app_version": None,
}
BATCH_FIELDS = ("install_id", "display_name", "app_version", "git_commit", "build_variant")
REASONS = ("feedback", "sample")
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,200}")  # same charset as the app's api.core.safe_id
MAX_EVENTS_BYTES = 16 * 1024 * 1024  # the sender caps a batch at 5 MB
MAX_ARCHIVE_BYTES = 2 * 1024 ** 3
DRAIN_LIMIT = 16 * 1024 * 1024  # a refused body up to this size is read and discarded so the client sees the status
CHUNK = 1024 * 1024  # uploads are streamed to disk in 1 MiB pieces, never held whole
APPEND_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()


def utc_now():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_id(value):
    return bool(value and SAFE_ID.fullmatch(value) and set(value) != {"."})


class Refused(Exception):
    def __init__(self, status, error):
        super().__init__(error)
        self.status, self.error = status, error


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # needed for Expect: 100-continue; every response still closes the connection
    server_version = "CoraReceiver/1"
    root: Path
    token: str

    # ---- plumbing ---------------------------------------------------------------

    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.status = status
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # replaced by the JSONL request log

    def begin(self):
        self.started = time.monotonic()
        self.status = None
        self.fields = {}

    def write_log(self):
        entry = {"ts": iso(utc_now()), "method": self.command, "path": self.path, "status": self.status,
                 "ms": round((time.monotonic() - self.started) * 1000, 1), **self.fields}
        log_file = self.root / "logs" / "receiver.jsonl"
        with LOG_LOCK:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def dispatch(self, route):
        try:
            route()
        except Refused as r:
            self.refuse(r)
        except Exception as e:
            traceback.print_exc()
            self.fields["error"] = f"{type(e).__name__}: {e}"
            if self.status is None:
                self.close_connection = True
                self.send_json({"error": "internal error"}, 500)
        finally:
            self.write_log()

    def refuse(self, r, body_follows=True):
        """Answer a refusal. A small body is drained first so the client reads the
        status instead of a reset; a large one is left unread and the connection closed."""
        self.fields["error"] = r.error
        length = self.declared_length()
        if body_follows and length is not None and 0 < length <= DRAIN_LIMIT:
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        self.close_connection = True
        self.send_json({"error": r.error}, r.status)

    def declared_length(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        return length if length >= 0 else None

    def body_length(self, limit):
        length = self.declared_length()
        if length is None:
            raise Refused(400, "Content-Length required")
        if length > limit:
            raise Refused(413, f"body over {limit} bytes")
        return length

    def check_token(self):
        given = self.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {self.token}".encode()):
            raise Refused(401, "bad token")

    # ---- routing ----------------------------------------------------------------

    def do_GET(self):
        self.begin()
        self.dispatch(self.route_get)

    def do_POST(self):
        if not hasattr(self, "started"):
            self.begin()
        self.dispatch(self.route_post)

    def route_get(self):
        if self.path != "/v1/config":
            raise Refused(404, "not found")
        self.get_config()

    def route_post(self):
        self.check_post()
        if self.path == "/v1/events":
            self.post_events()
        else:
            self.post_recording()

    def check_post(self):
        """Everything decidable from the request line and headers, before any body byte."""
        if self.path not in ("/v1/events", "/v1/recordings"):
            raise Refused(404, "not found")
        self.check_token()
        if self.path == "/v1/events":
            self.body_length(MAX_EVENTS_BYTES)
            return
        install = self.headers.get("X-Cora-Install", "")
        recording = self.headers.get("X-Cora-Recording", "")
        self.fields.update(install_id=install, recording_id=recording)
        if not safe_id(install) or not safe_id(recording):
            raise Refused(400, "X-Cora-Install and X-Cora-Recording must be ids of [A-Za-z0-9._-]")
        if self.headers.get("X-Cora-Reason") not in REASONS:
            raise Refused(400, f"X-Cora-Reason must be one of {', '.join(REASONS)}")
        self.body_length(MAX_ARCHIVE_BYTES)
        if (self.root / "recordings" / install / recording).exists():
            raise Refused(409, "already stored")

    def handle_expect_100(self):
        """A client that sends Expect: 100-continue is refused before it uploads anything."""
        self.begin()
        try:
            self.check_post()
        except Refused as r:
            self.refuse(r, body_follows=False)
            self.write_log()
            return False
        return super().handle_expect_100()

    # ---- endpoints --------------------------------------------------------------

    def get_config(self):
        path = self.root / "config.json"
        try:
            overrides = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(overrides, dict):
                raise ValueError("config.json must hold an object")
        except ValueError as e:
            raise Refused(500, f"config.json unreadable: {e}") from None
        self.send_json({**DEFAULT_CONFIG, **overrides})

    def post_events(self):
        length = self.body_length(MAX_EVENTS_BYTES)
        try:
            batch = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(batch, dict):
                raise ValueError("batch must be an object")
            if not isinstance(batch.get("install_id"), str) or not batch["install_id"]:
                raise ValueError("install_id required")
            if not isinstance(batch.get("events"), list) or not all(isinstance(e, dict) for e in batch["events"]):
                raise ValueError("events must be a list of objects")
        except ValueError as e:  # includes JSONDecodeError and UnicodeDecodeError; the body is already read
            self.fields["error"] = f"malformed batch: {e}"
            return self.send_json({"error": f"malformed batch: {e}"}, 400)
        now = utc_now()
        stamp = {k: batch.get(k) for k in BATCH_FIELDS}
        stamp["received_at"] = iso(now)
        lines = "".join(json.dumps({**e, **stamp}) + "\n" for e in batch["events"])
        if lines:
            day_file = self.root / "events" / f"{now:%Y-%m-%d}.jsonl"
            with APPEND_LOCK:
                day_file.parent.mkdir(exist_ok=True)
                with open(day_file, "a") as f:
                    f.write(lines)
        self.fields.update(install_id=batch["install_id"], accepted=len(batch["events"]))
        self.send_json({"accepted": len(batch["events"])}, 202)

    def post_recording(self):
        install = self.headers["X-Cora-Install"]
        recording = self.headers["X-Cora-Recording"]
        length = self.body_length(MAX_ARCHIVE_BYTES)
        folder = self.root / "recordings" / install / recording
        folder.parent.mkdir(parents=True, exist_ok=True)
        try:
            folder.mkdir()  # the claim: a concurrent second upload of the same Recording gets 409
        except FileExistsError:
            raise Refused(409, "already stored") from None
        try:
            received_at = utc_now()
            digest = hashlib.sha256()
            part = folder / "archive.tar.gz.part"
            remaining = length
            with open(part, "wb") as out:
                while remaining:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            if remaining:
                shutil.rmtree(folder)
                self.fields.update(error=f"upload cut off after {length - remaining} of {length} bytes")
                self.status = 400
                self.close_connection = True
                return  # the client is gone; nothing to answer
            meta = {"install_id": install, "recording_id": recording, "reason": self.headers["X-Cora-Reason"],
                    "app_version": self.headers.get("X-Cora-Version"),
                    "display_name": self.headers.get("X-Cora-Display-Name"),
                    "size": length, "sha256": digest.hexdigest(), "received_at": iso(received_at)}
            (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            part.rename(folder / "archive.tar.gz")  # last: archive.tar.gz present means the upload is complete
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self.fields["size"] = length
        self.send_json({"stored": f"{install}/{recording}"}, 201)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Cora beta receiver")
    ap.add_argument("--root", required=True, type=Path, help="directory for events, recordings, config, logs")
    ap.add_argument("--port", required=True, type=int)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (Tailscale Funnel proxies to localhost)")
    ap.add_argument("--token-env", default="CORA_RECEIVER_TOKEN", help="environment variable holding the token")
    args = ap.parse_args(argv)
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(f"receiver: set the bearer token in ${args.token_env}", file=sys.stderr)
        return 2
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    handler = type("BoundHandler", (Handler,), {"root": root, "token": token})
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    httpd.daemon_threads = True
    print(f"receiver: serving {root} on {args.host}:{args.port}", file=sys.stderr, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
