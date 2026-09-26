"""HTTP request handler: security headers, auth gate, JSON/file responses, dispatch."""
from __future__ import annotations
import hmac
import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

from api import auth, router
from api.auth import LOOPBACK_HOSTS, PUBLIC_PATHS, _cookie_token  # noqa: F401
import api.routes  # noqa: F401  (registers every endpoint)
from api.routes.media import serve_static


class Handler(BaseHTTPRequestHandler):
    server_version = "Cora/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"{h}:{port}" for h in LOOPBACK_HOSTS}

    def authorize(self, path: str) -> bool:
        """Reject rebinding, cross-origin, and unauthenticated requests.

        Sends the error response itself and returns False when rejected.
        """
        if self.headers.get("Host", "") not in self._allowed_hosts():
            self.send_json({"error": "Forbidden host"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin.removeprefix("http://") not in self._allowed_hosts():
            self.send_json({"error": "Forbidden origin"}, 403)
            return False
        if path in PUBLIC_PATHS or not (path.startswith("/api/") or path.startswith("/media")):
            return True
        presented = self.headers.get("X-VC-Token") or _cookie_token(self.headers.get("Cookie", ""))
        if not (auth.API_TOKEN and presented and hmac.compare_digest(presented, auth.API_TOKEN)):
            self.send_json({"error": "Unauthorized"}, 401)
            return False
        return True

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def serve_file(self, path: Path, cache: bool = True) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if not match:
                self.send_error(416)
                return
            start = int(match.group(1) or 0)
            end = min(int(match.group(2) or size - 1), size - 1)
            if start > end:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            length = end - start + 1
        else:
            start, length = 0, size
            self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        if not self.authorize(path):
            return
        try:
            handler = router.match("GET", path) or serve_static
            return handler(self, path, query)
        except (ValueError, FileNotFoundError) as exc:
            return self.send_json({"error": str(exc)}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self.authorize(path):
            return
        try:
            body = self.read_json()
            handler = router.match("POST", path)
            if handler is None:
                return self.send_json({"error": "Unknown endpoint"}, 404)
            return handler(self, path, body)
        except (ValueError, FileNotFoundError) as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)
