"""Coaching's side of the Plugin seam: its data for a Recording, its stages
and its after_meeting Hook. Light to import (no numpy, no Gemini SDK); the
engine is imported only when a coaching report is actually generated."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import db

# Report models Cora has produced; older reports carry no executive_assessment.
REPORT_MODELS = {"gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash"}

STAGE_LABELS = {"ready_for_coaching": "Ready to coach", "coached": "Coached"}

ARCHETYPE_OPTIONS = [
    {
        "id": "auto",
        "archetype_id": None,
        "label": "Auto-detect Archetype (Recommended)",
        "hat": "Cora Intelligence",
        "tip": "Cora analyzes meeting dynamics and selects the optimal coaching rubric.",
        "frequency": "Automatic"
    },
    {
        "id": "1",
        "archetype_id": 1,
        "label": "1 · Technical Steering & Architecture",
        "hat": "Chief Architect",
        "tip": "State verdict in first 15s · Bound by hard SLAs & token constraints · Assign spec owner",
        "frequency": "High (~50% of meetings)"
    },
    {
        "id": "4",
        "archetype_id": 4,
        "label": "4 · Strategic L10 & Cross-Functional",
        "hat": "Strategic Lead",
        "tip": "Keep airtime <15% · Translate technical bottlenecks to business impact · Strict IDS",
        "frequency": "High (~20% of meetings)"
    },
    {
        "id": "5",
        "archetype_id": 5,
        "label": "5 · Client Solutioning & Commercials",
        "hat": "Solution Strategist",
        "tip": "Anchor on client ROI · Defend scope & unit economics · Lock sign-off milestone",
        "frequency": "Frequent (~15% of meetings)"
    },
    {
        "id": "2",
        "archetype_id": 2,
        "label": "2 · Execution Control & Standup",
        "hat": "Operating Lead",
        "tip": "Target <15m · Airtime 20-30% · Parking Lot rule (<30s redirect) · Rule of 4",
        "frequency": "Frequent (~10% of meetings)"
    },
    {
        "id": "7",
        "archetype_id": 7,
        "label": "7 · Solo Ideation & Voice Memo",
        "hat": "Thought Partner",
        "tip": "Unconstrained flow · Auto-structures audio into Core Thesis, Dependencies & Spec",
        "frequency": "Specialized"
    },
    {
        "id": "3",
        "archetype_id": 3,
        "label": "3 · Talent Multiplication (1:1 Mentoring)",
        "hat": "Player-Coach",
        "tip": "Socratic questions > lecture (>=2:1) · Synthesis test (learner recaps plan in final 15%)",
        "frequency": "High leverage"
    },
    {
        "id": "6",
        "archetype_id": 6,
        "label": "6 · Talent Acquisition (Interviews)",
        "hat": "Technical Evaluator",
        "tip": "Candidate airtime >70% · 2-min pitch max · 3-level depth probing (Why? What broke?)",
        "frequency": "High stakes"
    },
    {
        "id": "8",
        "archetype_id": 8,
        "label": "8 · Content Creation & Loom",
        "hat": "Presenter",
        "tip": "Deliver core hook in first 10s · Zero filler tolerance · Crisp vocal energy",
        "frequency": "Asynchronous"
    },
]

MODE_LABELS = {opt["id"]: opt["label"] for opt in ARCHETYPE_OPTIONS}
MODE_LABELS.update({str(opt["archetype_id"]): opt["label"] for opt in ARCHETYPE_OPTIONS if opt["archetype_id"]})
MODE_LABELS.update({
    "free": "Auto-detect Archetype",
    "story": "Storytelling",
    "negotiation": "Negotiation",
    "direction": "Giving direction",
    "pronunciation": "Delivery practice",
})



def report(recording: dict[str, Any]) -> dict[str, Any]:
    """The Recording's coaching report, or {} when it is missing or stale
    (no diarization, owner not confirmed, or scored for another speaker)."""
    raw = recording.get("coaching") or {}
    self_speaker = (recording.get("identity") or {}).get("speaker_id")
    if not (recording.get("diarization") and self_speaker and raw):
        return {}
    if raw.get("target_speaker") != self_speaker:
        return {}
    if not (raw.get("executive_assessment") or raw.get("model") in REPORT_MODELS):
        return {}
    return raw


def stage(recording: dict[str, Any]) -> str:
    return "coached" if report(recording) else "ready_for_coaching"


def delivery(raw_metrics: dict[str, Any], coaching: dict[str, Any], target_speaker: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Delivery metrics for the owner's turns, with the report's best/fix
    moments merged into the metrics timeline."""
    if not raw_metrics or not target_speaker or raw_metrics.get("target_speaker") != target_speaker:
        return {}, {}
    from diarization import timestamp_seconds
    metrics = json.loads(json.dumps(raw_metrics))

    def moment(item: dict[str, Any] | None, kind: str) -> dict[str, Any]:
        if not item:
            return {}
        return {
            "type": f"{kind}_moment",
            "label": "Best moment" if kind == "best" else "Fix this moment",
            "time": timestamp_seconds(item.get("timestamp", "")),
            "timestamp": item.get("timestamp", ""),
            "excerpt": item.get("quote", ""),
            "explanation": item.get("observation", ""),
            "alternative": item.get("better_response", ""),
            "alternative_source": "coaching",
        }

    moments = {
        "best": moment((coaching.get("strongest_moments") or [None])[0], "best"),
        "fix": moment((coaching.get("improvement_moments") or [None])[0], "fix"),
    }
    timeline = metrics.setdefault("timeline", {})
    events = list(timeline.get("events", []))
    events.extend(value for value in moments.values() if value)
    timeline["events"] = sorted(events, key=lambda event: float(event.get("time", 0)))
    return metrics, moments


def payload(recording: dict[str, Any]) -> dict[str, Any] | None:
    coaching = report(recording)
    if not coaching:
        return None
    scores = {
        name: int(value.get("score", 0))
        for name, value in coaching.get("scores", {}).items()
        if isinstance(value, dict)
    }
    if scores:
        scores["overall"] = round(sum(scores.values()) / len(scores))
    metrics, moments = delivery(recording.get("delivery_metrics") or {}, coaching, coaching.get("target_speaker"))
    return {
        "report": coaching,
        "scores": scores,
        "top_priority": ((coaching.get("improvement_moments") or [{}])[0]).get("observation"),
        "mode": coaching.get("mode"),
        "mode_label": MODE_LABELS.get(coaching.get("mode"), coaching.get("mode")),
        "archetype": coaching.get("archetype") or {},
        "delivery_metrics": metrics,
        "delivery_moments": moments,
    }


def after_meeting(recording_id: str) -> None:
    """Score the owner's turns once a Recording is processed.

    Runs only when this Recording was diarized by Gemini, so the audio has
    already gone to Google in this run; a locally processed Recording is never
    uploaded by this hook. Needs a confirmed owner speaker."""
    recording = db.get_recording(recording_id)
    if not recording:
        return
    diarization = recording.get("diarization") or {}
    speaker_id = (recording.get("identity") or {}).get("speaker_id")
    model = str(diarization.get("model") or "")
    if not (speaker_id and model.startswith("gemini")):
        return
    from plugins.coaching import engine
    engine.coach(Path(recording["folder_path"]), mode="free", speaker_id=speaker_id, model=model,
                 goals=db.get_setting("goals"))
