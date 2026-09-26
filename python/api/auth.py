"""Access control for the local API: per-launch token, loopback Host/Origin pinning."""
from __future__ import annotations
import os
import secrets

import paths

API_TOKEN_FILE = paths.API_TOKEN_FILE


# --- Local API access control -------------------------------------------
# The server binds to loopback, but loopback alone isn't a boundary: any web
# page open in any browser can fire requests at 127.0.0.1, and DNS rebinding
# can make them same-origin. Every /api and /media request must therefore
# present the per-launch token — as the HttpOnly SameSite=Strict cookie
# Electron sets for its own window (covers fetch, <audio>, <img>), or as the
# X-VC-Token header for local tools (main.js, CLI scripts). Host and Origin
# are pinned to loopback, and POST bodies must be JSON so a cross-site
# "simple" text/plain form post can't slip past CORS preflight.
API_TOKEN = ""
TOKEN_COOKIE = "vc_token"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
PUBLIC_PATHS = {"/api/health"}


def init_api_token() -> str:
    """Use the token Electron handed us, or mint one for standalone runs.

    The token is also written (0600) to API_TOKEN_FILE so same-user CLI
    tools can authenticate without it ever appearing in argv or `ps`.
    """
    global API_TOKEN
    API_TOKEN = os.environ.get("VOICECOACH_API_TOKEN") or secrets.token_urlsafe(32)
    fd = os.open(API_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(API_TOKEN)
    os.chmod(API_TOKEN_FILE, 0o600)
    return API_TOKEN


def _cookie_token(cookie_header: str) -> str:
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == TOKEN_COOKIE:
            return value
    return ""
