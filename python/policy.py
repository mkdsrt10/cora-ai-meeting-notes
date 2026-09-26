"""Enterprise lockdown: one switch that guarantees nothing leaves the Mac.

For regulated deployments (HIPAA, defence contractors) an admin sets either
`"enterprise_lockdown": true` in config.json or VOICECOACH_ENTERPRISE_LOCKDOWN=1
(e.g. via MDM). While it is on, every outbound path refuses to run —
tracing, cloud LLM/transcription providers, VM sync, and data contribution —
regardless of what a user toggles in Settings. The env var cannot be
switched off from inside the app, which is what makes it enforceable.
"""
from __future__ import annotations

import json
import os

import paths

CLOUD_PROVIDERS = frozenset({"anthropic", "openai", "vertex", "ai_studio", "gemini"})


class LockdownError(RuntimeError):
    """Raised when an outbound action is attempted under enterprise lockdown."""


def lockdown_enabled() -> bool:
    if os.environ.get("VOICECOACH_ENTERPRISE_LOCKDOWN") == "1":
        return True
    try:
        return bool(json.loads(paths.CONFIG_PATH.read_text()).get("enterprise_lockdown"))
    except (OSError, ValueError):
        return False


def require_outbound_allowed(what: str) -> None:
    if lockdown_enabled():
        raise LockdownError(f"{what} is disabled by enterprise lockdown.")


def provider_allowed(provider: str | None, base_url: str | None = None) -> bool:
    """Cloud providers are blocked under lockdown; a custom endpoint is only
    allowed if it runs on this machine (e.g. Ollama on localhost)."""
    if not lockdown_enabled():
        return True
    p = (provider or "").lower()
    if p in CLOUD_PROVIDERS:
        return False
    if p == "custom":
        from urllib.parse import urlparse
        return urlparse(base_url or "").hostname in {"localhost", "127.0.0.1", "::1"}
    return True
