"""Coaching plugin endpoints."""
from __future__ import annotations

from api.router import route
from diarization import LATEST_AUDIO_MODEL
from diarization import confirm_speaker
from plugin_registry import get_coaching_plugin
import db
from api.core import DEFAULT_DATA, safe_folder


@route("POST", '/api/confirm-and-coach')
def post_api_confirm_and_coach(req, path: str, body: dict) -> None:
    coaching_plugin = get_coaching_plugin()
    if coaching_plugin is None:
        return req.send_json({"error": "Coaching plugin is not enabled. Set plugins.coaching.enabled to true in config.json."}, 404)
    folder = safe_folder(body.get("id", ""))
    speaker_id = str(body.get("speaker_id", ""))
    mode = str(body.get("archetype_id") if body.get("archetype_id") is not None else (body.get("mode") or "auto"))
    confirm_speaker(folder, speaker_id)
    goals = db.get_setting("goals", DEFAULT_DATA["goals"])
    result = coaching_plugin.coach(folder, mode=mode, model=LATEST_AUDIO_MODEL, goals=goals)
    return req.send_json({"ok": True, "coaching": result})


@route("POST", '/api/gemini-coach')
def post_api_gemini_coach(req, path: str, body: dict) -> None:
    coaching_plugin = get_coaching_plugin()
    if coaching_plugin is None:
        return req.send_json({"error": "Coaching plugin is not enabled. Set plugins.coaching.enabled to true in config.json."}, 404)
    folder = safe_folder(body.get("id", ""))
    goals = db.get_setting("goals", DEFAULT_DATA["goals"])
    mode = str(body.get("archetype_id") if body.get("archetype_id") is not None else (body.get("mode") or "auto"))
    result = coaching_plugin.coach(folder, mode=mode, model=LATEST_AUDIO_MODEL, goals=goals)
    return req.send_json({"ok": True, "coaching": result})
