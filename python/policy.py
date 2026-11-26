"""Enterprise lockdown: one switch that guarantees nothing leaves the Mac.

For regulated deployments (HIPAA, defence contractors) an admin sets either
`"enterprise_lockdown": true` in config.json or VOICECOACH_ENTERPRISE_LOCKDOWN=1
(e.g. via MDM). While it is on, every outbound path refuses to run —
tracing, cloud LLM/transcription providers, and data contribution —
regardless of what a user toggles in Settings. The env var cannot be
switched off from inside the app, which is what makes it enforceable.
"""
from __future__ import annotations

import json
import os

import paths

LOCAL_PROVIDERS = frozenset({"local_mlx", "local"})
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
    """Under lockdown only on-device models run: local MLX, or an endpoint on
    this machine (e.g. Ollama or a LiteLLM proxy on localhost). Every other
    provider (Gemini, Anthropic, any remote base URL) is blocked."""
    if not lockdown_enabled():
        return True
    if (provider or "").lower() in LOCAL_PROVIDERS:
        return True
    from urllib.parse import urlparse
    return bool(base_url) and urlparse(base_url).hostname in LOCAL_HOSTS
