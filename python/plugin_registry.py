#!/usr/bin/env python3
"""Loader for optional Cora plugins.

Cora's core (recording, local or Gemini-cloud diarization, call summaries,
speaker identity) never imports a plugin module directly — it asks this
registry for one, and gets None back if the plugin's config flag is off or
its package isn't present. Delete plugins/coaching/ entirely and the core app
keeps working; you just lose the coaching endpoints.
"""
from __future__ import annotations

import json
from typing import Any

import paths

CONFIG_PATH = paths.CONFIG_PATH

_DEFAULTS: dict[str, Any] = {
    # Off unless explicitly enabled: an early prototype that still calls a
    # cloud API (Gemini) for scoring — see plugins/coaching/README.md.
    "coaching": {"enabled": False},
}


def _config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def plugin_config(plugin_id: str) -> dict[str, Any]:
    return _config().get("plugins", {}).get(plugin_id, _DEFAULTS.get(plugin_id, {}))


def is_plugin_enabled(plugin_id: str) -> bool:
    return bool(plugin_config(plugin_id).get("enabled", _DEFAULTS.get(plugin_id, {}).get("enabled", False)))


def coaching_enabled() -> bool:
    return is_plugin_enabled("coaching")


_cache: dict[str, Any] = {}


def get_coaching_plugin():
    """Return the coaching plugin's engine module, or None if disabled/not installed."""
    if "coaching" in _cache:
        return _cache["coaching"]
    module = None
    if coaching_enabled():
        try:
            from plugins.coaching import engine as module  # noqa: F401
        except ImportError:
            module = None
    _cache["coaching"] = module
    return module
