"""Cleaning of participant names read from meeting apps (Accessibility UI text).

Dependency-light on purpose: used by both the API server and the pipeline,
and importing it must not pull in the ML stack.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import paths


def _extra_participant_stopwords() -> set[str]:
    """Workspace/org names that show up in meeting-app UI text but aren't
    people (config.json: participant_stopwords, lowercase)."""
    try:
        extra = json.loads(paths.CONFIG_PATH.read_text()).get("participant_stopwords") or []
    except (OSError, ValueError):
        extra = []
    return {str(w).lower() for w in extra}


_BAD_PARTICIPANT_WORDS = {
    "video", "audio", "microphone", "mic", "camera", "cam", "screen", "record",
    "recording", "mute", "unmute", "volume", "share", "speaker", "settings",
    "options", "clip", "tab", "channel", "cora", "slack", "zoom",
    "meet", "google", "calendar", "activity", "huddle", "deployments", "search",
    "message", "messages", "notetaker", "tldv", "read.ai", "otter", "fireflies",
    "fathom", "granola", "fellow", "bot", "ai", "speaking", "started", "ended",
    "offline", "online", "joined", "left", "waiting", "draw", "keep", "outline",
    "frame", "loudspeaker", "emoji", "overview", "notes", "summary", "actions"
}


def clean_and_validate_participant(raw_name: str) -> Optional[str]:
    """Filter out notetakers, bot extensions, UI text, and invalid fragments from participant names."""
    if not raw_name or not isinstance(raw_name, str):
        return None
    s = raw_name.strip()
    s = re.sub(r"^[!*#@\-_•\s]+", "", s).strip()
    if "," in s:
        return None
    s = re.sub(r"\s*\((?:Your )?Presentation\)$", "", s, flags=re.I).strip()
    s = re.sub(r"\s*\((?:is )?speaking\)$", "", s, flags=re.I).strip()
    s = re.sub(r"^More options for\s+", "", s, flags=re.I).strip()
    s = re.sub(r"^View\s+(.+?)'s\s+profile$", r"\1", s, flags=re.I).strip()
    if len(s) < 3 or len(s) > 35:
        return None
    s_lower = s.lower()
    words = set(re.findall(r"[a-z]+", s_lower))
    if words & (_BAD_PARTICIPANT_WORDS | _extra_participant_stopwords()):
        return None
    if re.search(r"[{}\[\]/\\_+=<>@#$%^&*~`]", s):
        return None
    if re.search(r"\d", s):
        return None
    if "." in s:
        return None
    if not re.search(r"[a-zA-Z]", s):
        return None
    return s.strip()
