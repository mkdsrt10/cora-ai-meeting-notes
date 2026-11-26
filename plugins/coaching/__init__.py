"""Cora coaching plugin.

Optional executive-communication coaching: meeting-archetype classification,
per-speaker scoring rubrics and delivery metrics (pace/pauses/fillers/pitch).

This plugin still calls Google Gemini's cloud audio API to generate coaching
scores and archetype classification (see engine.coach/classify_meeting) — it
has not been ported to a local model. Core meeting notes (transcription,
diarization, call summary) work fully offline without this plugin; enabling
it opts a user into that additional cloud call for the coaching layer only.

Off by default. Enable with `plugins.coaching.enabled: true` in config.json.
Disabled or deleted, the host simply leaves it out: no payload, no coaching
stages, no after_meeting Hook.
"""
from __future__ import annotations

from plugin_host import Plugin

from . import plugin

PLUGIN = Plugin(
    id="coaching",
    name="Executive Coaching",
    payload=plugin.payload,
    stage=plugin.stage,
    stage_labels=plugin.STAGE_LABELS,
    hooks={"after_meeting": plugin.after_meeting},
)
