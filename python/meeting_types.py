#!/usr/bin/env python3
"""Core meeting-type taxonomy: categorization only, no coaching logic.

This is deliberately separate from plugins/coaching/engine.py's ARCHETYPES
dict, which shares these same ids/names but adds coaching-specific fields
(coaching_enabled, scoring rubrics). Core features that need "what kind of
meeting is this" — onboarding's meeting-type picker, the home page filter,
the vocabulary/summary prompts — must keep working with the coaching plugin
disabled, so they read from here, not from the plugin.

If you add or rename a type here, update plugins/coaching/engine.py's
ARCHETYPES to match (ids and names are meant to stay in sync; the plugin's
copy just adds coaching_enabled and rubric-selection fields on top).
"""
from __future__ import annotations

from typing import Any

MEETING_TYPES: list[dict[str, Any]] = [
    {"id": 1, "name": "Technical Steering", "description": "Architecture, protocol design, schema, and trade-off resolutions"},
    {"id": 2, "name": "Execution Control", "description": "Standups, sprint reviews, blocker sweeps, rapid updates"},
    {"id": 3, "name": "Talent Multiplication", "description": "1:1 mentoring, junior walkthroughs, mental model transfers — either direction: guiding someone, or being guided"},
    {"id": 4, "name": "Strategic / Cross-Functional", "description": "Cross-functional alignment, roadmaps, friction resolution across multiple coworkers"},
    {"id": 5, "name": "Client Solutioning", "description": "Client demos, commercial alignment, ROI defense, scope boundaries"},
    {"id": 6, "name": "Talent Acquisition", "description": "Interviews, evaluating candidate technical depth"},
    {"id": 7, "name": "Solo Ideation", "description": "Voice memo, brainstorming, unstructured dictation"},
    {"id": 8, "name": "Content Creation", "description": "Async demo, scripted presentation, recorded walkthrough"},
]

MEETING_TYPES_BY_ID: dict[int, dict[str, Any]] = {item["id"]: item for item in MEETING_TYPES}
