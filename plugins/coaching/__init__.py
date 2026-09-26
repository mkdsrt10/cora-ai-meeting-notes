"""Cora coaching plugin.

Optional executive-communication coaching: meeting-archetype classification,
per-speaker scoring rubrics, delivery metrics (pace/pauses/fillers/pitch), and
the goals/reflections/practice-queue habit loop built on top of them.

This plugin still calls Google Gemini's cloud audio API to generate coaching
scores and archetype classification (see engine.coach/classify_meeting) — it
has not been ported to a local model. Core meeting notes (transcription,
diarization, call summary) work fully offline without this plugin; enabling
it opts a user into that additional cloud call for the coaching layer only.

To disable: set `plugins.coaching.enabled` to `false` in config.json, or
delete this directory entirely. Either way, python/diarization.py and
python/server.py degrade gracefully — coaching endpoints return a clear
404 instead of crashing, and the auto-pilot hook in diarize() simply skips
coaching.
"""
from __future__ import annotations

from . import engine  # noqa: F401

PLUGIN_ID = "coaching"
PLUGIN_NAME = "Executive Coaching"
REQUIRES_CLOUD = True
