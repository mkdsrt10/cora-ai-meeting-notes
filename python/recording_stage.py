"""A Recording's stage: the one definition shared by the dashboard view model
(api/views.py) and the MCP server (mcp_server.py).

Core owns the generic stages. Once a Recording is processed and its owner's
speaker is confirmed, an enabled plugin may claim a more specific stage
(Coaching: ready_for_coaching / coached); otherwise it is simply "ready".
"""
from __future__ import annotations

from typing import Any

import plugin_host

PENDING = ("recording", "processing", "paused")

CORE_LABELS = {
    "recording": "Recording…",
    "processing": "Processing…",
    "paused": "Paused",
    "failed": "Processing failed",
    "needs_diarization": "Needs diarization",
    "needs_speaker_confirmation": "Identify me",
    "ready": "Ready",
}


def stage(recording: dict[str, Any]) -> str:
    """Stage of one Recording DB row (as returned by db.get_recording)."""
    status = recording.get("status")
    if status in PENDING:
        return status
    if status == "failed":
        return "failed"
    if not recording.get("diarization"):
        return "needs_diarization"
    if not (recording.get("identity") or {}).get("speaker_id"):
        return "needs_speaker_confirmation"
    return plugin_host.plugin_stage(recording) or "ready"


def labels() -> dict[str, str]:
    """Every stage the UI can show, core first, then enabled plugins'."""
    return {**CORE_LABELS, **plugin_host.stage_labels()}
