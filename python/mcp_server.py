#!/usr/bin/env python3
"""Cora MCP Server — Model Context Protocol interface for Cora Desktop.

Exposes:
- Real-time recording state and pipeline status
- Full diarized transcripts with speaker turns, timestamps, emotions
- Executive coaching reports, domain rubric scores, and suggested phrasing
- Objective voice delivery mechanics (pacing, fillers, pauses, pitch/volume)
- Multi-meeting participant directory and relationship context
- Decisions, action items, practice drills, and speech trends
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# Ensure python directory is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

paths.ensure_data_dir()
ROOT = paths.APP_ROOT
RECORDINGS = paths.RECORDINGS_DIR

import db
import credentials


def _recording_folder(recording_id: str) -> Optional[Path]:
    """Resolve a recording's on-disk folder, refusing anything that would
    escape RECORDINGS (defends the same path-traversal case server.py's
    safe_folder() does, for the handful of fields — enhanced notes, key
    phrases, versions — that only exist on disk, not in the DB)."""
    candidate = (RECORDINGS / recording_id).resolve()
    if not candidate.is_relative_to(RECORDINGS.resolve()) or not candidate.is_dir():
        return None
    return candidate
from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="cora",
    version="1.0.0",
    description=(
        "Cora Executive Communication Intelligence & Voice Coach. "
        "Provides access to live meeting audio analysis, neural speaker diarization, "
        "exact spoken transcripts, executive coaching rubrics, and action items."
    ),
)


def _resolve_speaker_name(speaker_id: str, speaker_labels: dict[str, Any], identity: dict[str, Any]) -> str:
    """Resolve a raw speaker_1/speaker_2 ID into a human-friendly name."""
    self_id = identity.get("speaker_id")
    if self_id and speaker_id == self_id:
        self_name = identity.get("identity") or db.get_setting("pending_self_name") or "You"
        return f"{self_name} (Self)"

    entry = speaker_labels.get("speakers", {}).get(speaker_id, {})
    if entry.get("name"):
        parts = [entry["name"]]
        if entry.get("role"):
            parts.append(entry["role"])
        if entry.get("organization"):
            parts.append(f"({entry['organization']})")
        return " — ".join(parts)
    return speaker_id


@mcp.tool()
def cora_get_live_status() -> dict[str, Any]:
    """Get the live operational status of Cora.

    Returns whether a meeting is actively recording right now, pending pipeline tasks,
    configured AI engine details (Vertex AI / Gemini), and overall library statistics.
    """
    all_recs = db.get_all_recordings()
    pending = [r for r in all_recs if r.get("status") in {"recording", "processing"}]
    active_recording = next((r for r in pending if r.get("status") == "recording"), None)

    cred_status = credentials.get_public_status()
    unprocessed = db.get_unprocessed_recording()

    coached_recs = [r for r in all_recs if r.get("coaching") and r["coaching"].get("scores")]
    clarity_scores = [
        int(r["coaching"]["scores"]["clarity"]["score"])
        for r in coached_recs
        if r["coaching"]["scores"].get("clarity", {}).get("score") is not None
    ]
    avg_clarity = round(sum(clarity_scores) / len(clarity_scores), 1) if clarity_scores else None

    return {
        "status": "recording" if active_recording else ("processing" if pending else "idle"),
        "active_recording": {
            "id": active_recording["id"],
            "started_at": active_recording.get("recorded_at"),
            "archetype": (active_recording.get("metadata") or {}).get("archetype", {}).get("archetype_name"),
        } if active_recording else None,
        "queue_summary": {
            "pending_recordings": len(pending),
            "unprocessed_recording_id": unprocessed["id"] if unprocessed else None,
            "total_recordings_archived": len(all_recs),
            "total_meetings_coached": len(coached_recs),
            "average_clarity_score": avg_clarity,
        },
        "ai_engine": {
            "provider": cred_status.get("provider"),
            "project": cred_status.get("vertex_project"),
            "location": cred_status.get("vertex_location"),
            "auth_type": cred_status.get("vertex_auth_type"),
            "model": credentials.get_default_model(),
            "is_configured": cred_status.get("is_configured"),
            "storage": cred_status.get("storage_mode"),
        },
    }


@mcp.tool()
def cora_list_recordings(
    limit: int = 20,
    stage: Optional[str] = None,
    archetype: Optional[str] = None,
    meeting_tool: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    folder_id: Optional[str] = None,
    person: Optional[str] = None,
    query: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List meeting recordings tracked by Cora — the same filters the desktop
    app's session list supports.

    Args:
        limit: Maximum number of recordings to return (1-100, default 20).
        stage: Optional filter by analysis stage ('recording', 'needs_diarization',
               'needs_speaker_confirmation', 'ready_for_coaching', 'coached').
        archetype: Optional substring filter for archetype (e.g. 'Technical Steering',
                   'Strategic L10', 'Client Solutioning', 'Standup', '1:1').
        meeting_tool: Optional exact-ish filter for which app the meeting was in
                      (e.g. 'Zoom', 'Google Meet', 'Microsoft Teams', 'Slack Huddle').
                      Only populated for meetings started from the auto-detected
                      "Start Recording?" notification; manually started recordings
                      have no meeting_tool.
        date_from: Optional ISO date (YYYY-MM-DD) — only recordings on/after this date.
        date_to: Optional ISO date (YYYY-MM-DD) — only recordings on/before this date.
        folder_id: Optional folder id — see cora_list_folders for valid ids.
        person: Optional participant name — only recordings that included them.
        query: Optional text match against the title or notes overview.
    """
    limit = max(1, min(100, limit))
    recs = db.get_all_recordings()
    items = []
    query_lower = (query or "").lower()

    for r in recs:
        diarization = r.get("diarization") or {}
        coaching = r.get("coaching") or {}
        call_sum = r.get("call_summary") or diarization.get("call_summary") or {}
        identity = r.get("identity") or {}
        meta = r.get("metadata") or {}
        labels = r.get("speaker_labels") or {}

        # Determine stage
        rec_status = r.get("status")
        if rec_status in {"recording", "processing"}:
            current_stage = rec_status
        elif not diarization or not diarization.get("segments"):
            current_stage = "needs_diarization"
        elif not identity.get("speaker_id"):
            current_stage = "needs_speaker_confirmation"
        elif not coaching or not coaching.get("executive_assessment"):
            current_stage = "ready_for_coaching"
        else:
            current_stage = "coached"

        if stage and current_stage.lower() != stage.lower():
            continue

        arch_info = coaching.get("archetype") or meta.get("archetype") or {}
        arch_name = arch_info.get("archetype_name") or "General Call"

        if archetype and archetype.lower() not in arch_name.lower():
            continue

        if meeting_tool and (meta.get("meeting_tool") or "").lower() != meeting_tool.lower():
            continue

        if folder_id and meta.get("folder_id") != folder_id:
            continue

        recorded_at = r.get("recorded_at") or ""
        if date_from and recorded_at[:10] < date_from:
            continue
        if date_to and recorded_at[:10] > date_to:
            continue

        speakers = diarization.get("speakers") or []
        participant_names = [_resolve_speaker_name(s.get("speaker_id"), labels, identity) for s in speakers]
        if person and person not in participant_names:
            continue

        overview = call_sum.get("overview") or ""
        title = r.get("title") or "Meeting"
        if query_lower and query_lower not in title.lower() and query_lower not in overview.lower():
            continue

        scores = coaching.get("scores") or {}
        overall = None
        if scores:
            score_vals = [int(v.get("score", 0)) for v in scores.values() if isinstance(v, dict) and "score" in v]
            if score_vals:
                overall = round(sum(score_vals) / len(score_vals))

        items.append({
            "id": r["id"],
            "title": title,
            "recorded_at": r.get("recorded_at"),
            "duration_seconds": r.get("duration_seconds", 0),
            "stage": current_stage,
            "archetype": arch_name,
            "folder_id": meta.get("folder_id"),
            "participants": participant_names,
            "turn_count": len(diarization.get("segments", [])),
            "meeting_tool": meta.get("meeting_tool"),
            "overall_score": overall,
            "keywords": call_sum.get("keywords", []),
            "overview": overview[:200],
        })

        if len(items) >= limit:
            break

    return items


@mcp.tool()
def cora_list_folders() -> list[dict[str, Any]]:
    """List the folders recordings can be organized into — same as the
    desktop app's folder filter dropdown. Use a returned id as
    cora_list_recordings' folder_id argument."""
    return [{"id": f["id"], "name": f["name"]} for f in db.get_folders()]


@mcp.tool()
def cora_get_recording(recording_id: str) -> dict[str, Any]:
    """Retrieve the complete meeting record for a given recording ID.

    Includes purpose, topics, decisions, action items, participants,
    coaching executive summary, and key turning points.

    Args:
        recording_id: The unique identifier of the recording.
    """
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")

    diarization = rec.get("diarization") or {}
    coaching = rec.get("coaching") or {}
    call_sum = rec.get("call_summary") or diarization.get("call_summary") or {}
    identity = rec.get("identity") or {}
    labels = rec.get("speaker_labels") or {}
    delivery = rec.get("delivery_metrics") or {}
    meta = rec.get("metadata") or {}

    # Resolve participants
    participants = []
    for spk in diarization.get("speakers", []):
        sid = spk.get("speaker_id")
        participants.append({
            "speaker_id": sid,
            "name": _resolve_speaker_name(sid, labels, identity),
            "is_self": sid == identity.get("speaker_id"),
            "description": spk.get("description"),
        })

    folder = _recording_folder(recording_id)
    versions: list[str] = []
    if folder:
        versions_dir = folder / "versions"
        if versions_dir.is_dir():
            versions = sorted((p.name for p in versions_dir.iterdir() if p.is_dir()), reverse=True)

    return {
        "id": rec["id"],
        "title": rec.get("title"),
        "recorded_at": rec.get("recorded_at"),
        "duration_seconds": rec.get("duration_seconds"),
        "archetype": coaching.get("archetype") or meta.get("archetype"),
        "folder_id": meta.get("folder_id"),
        "participants": participants,
        "self_speaker_id": identity.get("speaker_id"),
        "versions": versions,
        # overview/decisions/action_items/unresolved_questions/keywords are the
        # current (markdown-pipeline) fields — see cora_get_enhanced_notes for
        # the full formatted document these are extracted from.
        "summary": {
            "overview": call_sum.get("overview"),
            "decisions": call_sum.get("decisions", []),
            "action_items": call_sum.get("action_items", []),
            "unresolved_questions": call_sum.get("unresolved_questions", []),
            "keywords": call_sum.get("keywords", []),
        },
        "coaching": {
            "executive_assessment": coaching.get("executive_assessment"),
            "scores": coaching.get("scores", {}),
            "strongest_moments": coaching.get("strongest_moments", []),
            "improvement_moments": coaching.get("improvement_moments", []),
            "next_practice": coaching.get("next_practice", {}),
            "interaction_dynamics": coaching.get("interaction_dynamics", {}),
        } if coaching.get("executive_assessment") else None,
        "delivery_mechanics": {
            "pace": delivery.get("metrics", {}).get("pace"),
            "fillers": delivery.get("metrics", {}).get("fillers"),
            "pause_control": delivery.get("metrics", {}).get("pause_control"),
            "pitch_variety": delivery.get("metrics", {}).get("pitch_variety"),
        } if delivery.get("metrics") else None,
        "notes": rec.get("notes") or "",
        "available_summary_formats": list((rec.get("summaries") or {}).keys()),
        "meeting_tool": (rec.get("metadata") or {}).get("meeting_tool"),
        "turn_count": len(diarization.get("segments", [])),
    }


@mcp.tool()
def cora_get_notes(recording_id: str) -> str:
    """Get the user's own freeform notes for a meeting (typed during or after it,
    separate from the transcript and any generated summary).

    Args:
        recording_id: The recording ID.
    """
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")
    return rec.get("notes") or ""


@mcp.tool()
def cora_get_enhanced_notes(recording_id: str) -> str:
    """Get the full generated meeting notes as formatted Markdown — Overview,
    Action Items, Key Discussion & Decisions, Timeline, Open Questions, and
    Key Entities. This is the primary notes document the desktop app shows;
    cora_get_recording's 'summary' field has the same content pre-parsed into
    lists if you need it structured instead of as one document.

    Args:
        recording_id: The recording ID.
    """
    folder = _recording_folder(recording_id)
    if not folder:
        raise ValueError(f"Recording not found: {recording_id}")
    notes_path = folder / "enhanced_notes.md"
    if not notes_path.exists():
        return "No enhanced notes generated yet for this recording."
    return notes_path.read_text(errors="replace")


@mcp.tool()
def cora_get_summary(recording_id: str, format: str = "executive") -> dict[str, Any]:
    """Get one generated summary variant for a meeting.

    Args:
        recording_id: The recording ID.
        format: Which summary format to fetch — one of 'executive',
            'detailed_minutes', 'action_items_only', 'client_one_pager'.
            Use cora_get_recording's available_summary_formats to see which
            ones already exist for a given recording.
    """
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")
    summary = (rec.get("summaries") or {}).get(format)
    if not summary:
        raise ValueError(f"No '{format}' summary has been generated yet for {recording_id}.")
    return summary


@mcp.tool()
def cora_get_transcript(recording_id: str, format: str = "markdown") -> str:
    """Get the full speaker-diarized transcript for a meeting.

    Args:
        recording_id: The recording ID.
        format: Format style: 'markdown' (formatted text turns) or 'json' (raw structured turns).
    """
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")

    diarization = rec.get("diarization") or {}
    segments = diarization.get("segments") or []
    if not segments:
        return "No transcript segments available for this recording."

    labels = rec.get("speaker_labels") or {}
    identity = rec.get("identity") or {}

    if format.lower() == "json":
        turns = []
        for s in segments:
            sid = s.get("speaker_id")
            turns.append({
                "start": s.get("start"),
                "end": s.get("end"),
                "speaker": _resolve_speaker_name(sid, labels, identity),
                "speaker_id": sid,
                "text": s.get("text"),
                "emotion": s.get("emotion"),
                "language": s.get("language"),
            })
        return json.dumps(turns, indent=2, ensure_ascii=False)

    # Markdown format
    lines = [f"# Transcript: {rec.get('title') or recording_id}", ""]
    if diarization.get("summary"):
        lines.extend([f"> {diarization['summary']}", ""])

    for s in segments:
        sid = s.get("speaker_id")
        speaker_name = _resolve_speaker_name(sid, labels, identity)
        timestamp = f"{s.get('start', '00:00')} - {s.get('end', '00:00')}"
        emotion = f" · *{s.get('emotion')}*" if s.get("emotion") else ""
        lines.append(f"### [{timestamp}] {speaker_name}{emotion}")
        lines.append(f"{s.get('text', '')}\n")

    return "\n".join(lines)


@mcp.tool()
def cora_get_coaching_report(recording_id: str) -> dict[str, Any]:
    """Get the executive communication coaching report and domain rubric scores for a meeting.

    Includes domain scores (Clarity, Coherence, Concision, Influence, Responsiveness,
    Listener Direction), crucial turning points, specific quotes, and suggested alternative phrasing.

    Args:
        recording_id: The recording ID.
    """
    rec = db.get_recording(recording_id)
    if not rec:
        raise ValueError(f"Recording not found: {recording_id}")

    coaching = rec.get("coaching") or {}
    if not coaching or not coaching.get("executive_assessment"):
        raise ValueError(f"Recording {recording_id} has not been coached yet.")

    return {
        "recording_id": recording_id,
        "title": rec.get("title"),
        "recorded_at": rec.get("recorded_at"),
        "model": coaching.get("model", credentials.get_default_model()),
        "archetype": coaching.get("archetype"),
        "executive_assessment": coaching.get("executive_assessment"),
        "scores": coaching.get("scores", {}),
        "strongest_moments": coaching.get("strongest_moments", []),
        "improvement_moments": coaching.get("improvement_moments", []),
        "interaction_dynamics": coaching.get("interaction_dynamics", {}),
        "pronunciation_delivery": coaching.get("pronunciation_delivery", {}),
        "next_practice": coaching.get("next_practice", {}),
        "delivery_metrics": rec.get("delivery_metrics", {}).get("metrics"),
    }


@mcp.tool()
def cora_search_meetings(query: str, search_in: str = "all", limit: int = 15) -> list[dict[str, Any]]:
    """Search across meeting transcripts, executive summaries, decisions, and coaching reports.

    Args:
        query: Search term, keyword, or phrase.
        search_in: Scope: 'all', 'transcripts', 'summaries', 'coaching', or 'notes'.
        limit: Maximum results to return (default 15).
    """
    query_lower = query.lower()
    recs = db.get_all_recordings()
    results = []

    for r in recs:
        matches = []
        diarization = r.get("diarization") or {}
        call_sum = r.get("call_summary") or diarization.get("call_summary") or {}
        coaching = r.get("coaching") or {}

        # Search transcripts
        if search_in in {"all", "transcripts"}:
            for seg in diarization.get("segments", []):
                text = seg.get("text", "")
                if query_lower in text.lower():
                    matches.append({
                        "type": "transcript",
                        "timestamp": f"{seg.get('start')}-{seg.get('end')}",
                        "speaker_id": seg.get("speaker_id"),
                        "text": text,
                    })

        # Search summaries & decisions (current pipeline emits plain-string
        # bullets for decisions/action_items, not the old {decision,
        # timestamp} dicts — handle both so older archived recordings still
        # search correctly too)
        if search_in in {"all", "summaries"}:
            overview = call_sum.get("overview", "")
            if query_lower in overview.lower():
                matches.append({"type": "summary_overview", "text": overview})

            for dec in call_sum.get("decisions", []):
                d_str = dec.get("decision", "") if isinstance(dec, dict) else str(dec)
                if query_lower in d_str.lower():
                    matches.append({"type": "decision", "text": d_str, "timestamp": dec.get("timestamp") if isinstance(dec, dict) else None})

        # Search coaching
        if search_in in {"all", "coaching"}:
            assessment = coaching.get("executive_assessment", "")
            if query_lower in assessment.lower():
                matches.append({"type": "coaching_assessment", "text": assessment[:300]})

            for imp in coaching.get("improvement_moments", []):
                combined = f"{imp.get('quote', '')} {imp.get('observation', '')} {imp.get('better_response', '')}"
                if query_lower in combined.lower():
                    matches.append({"type": "improvement_moment", "quote": imp.get("quote"), "fix": imp.get("better_response")})

        # Search the user's own notes
        if search_in in {"all", "notes"}:
            notes = r.get("notes") or ""
            if query_lower in notes.lower():
                matches.append({"type": "notes", "text": notes[:300]})

        if matches:
            results.append({
                "recording_id": r["id"],
                "title": r.get("title"),
                "recorded_at": r.get("recorded_at"),
                "match_count": len(matches),
                "top_matches": matches[:3],
            })

        if len(results) >= limit:
            break

    return results


@mcp.tool()
def cora_list_people(limit: int = 50) -> list[dict[str, Any]]:
    """List all contacts and participants identified across meetings in Cora.

    Returns people with their name, role, organization, tags, meeting count,
    and whether the entry is marked as the user (self).

    Args:
        limit: Maximum number of people to return (default 50).
    """
    people = db.get_all_people()
    return people[:limit]


@mcp.tool()
def cora_get_person(person_id: str) -> dict[str, Any]:
    """Get details for a specific person, including all past meetings attended with them.

    Args:
        person_id: The ID of the person in Cora.
    """
    person = db.get_person(person_id)
    if not person:
        raise ValueError(f"Person not found: {person_id}")

    recs = db.get_person_recordings(person_id)
    return {
        "person": person,
        "meetings_count": len(recs),
        "meetings": [
            {
                "id": r["id"],
                "title": r.get("title"),
                "recorded_at": r.get("recorded_at"),
                "duration_seconds": r.get("duration_seconds"),
            }
            for r in recs
        ],
    }


_ACTION_META = re.compile(r"\s*\((?=[^)]*\b(?:owner|due)\s*:)([^)]*)\)\s*$", re.I)


def _parse_action_bullet(text: str) -> dict[str, Any]:
    text = text.strip().lstrip("-*• ").strip()
    item: dict[str, Any] = {"action": text}
    match = _ACTION_META.search(text)
    if match:
        item["action"] = text[: match.start()].strip()
        for part in match.group(1).split(","):
            key, _, value = part.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "owner" and value:
                item["owner"] = value
            elif key == "due" and value:
                item["due_date"] = value
    return item


@mcp.tool()
def cora_get_action_items(status: str = "pending", limit: int = 40) -> list[dict[str, Any]]:
    """List action items and decisions extracted from recent meetings.

    Args:
        status: Filter by status: 'pending', 'done', or 'all'.
        limit: Maximum items to return (default 40).
    """
    recs = db.get_all_recordings()
    todo_states = {f"{ts['recording_id']}_{ts['item_index']}": ts for ts in db.get_todo_states()}
    items = []

    for r in recs:
        call_sum = r.get("call_summary") or (r.get("diarization") or {}).get("call_summary") or {}
        actions = call_sum.get("action_items") or []
        identity = r.get("identity") or {}
        labels = r.get("speaker_labels") or {}

        for idx, act in enumerate(actions):
            ts_key = f"{r['id']}_{idx}"
            is_done = todo_states.get(ts_key, {}).get("done", False)

            if status == "pending" and is_done:
                continue
            if status == "done" and not is_done:
                continue

            if isinstance(act, str):
                # Local pipeline (call_summary v2) stores flat bullets like
                # "Ship the fix (Owner: Priya, Due: Friday)".
                act = _parse_action_bullet(act)
            owner_id = act.get("owner_speaker_id", "")
            owner_name = (_resolve_speaker_name(owner_id, labels, identity) if owner_id
                          else act.get("owner") or "Unassigned")

            items.append({
                "recording_id": r["id"],
                "meeting_title": r.get("title"),
                "recorded_at": r.get("recorded_at"),
                "item_index": idx,
                "action": act.get("action"),
                "owner": owner_name,
                "due_date": act.get("due_date"),
                "timestamp": act.get("timestamp"),
                "is_done": is_done,
            })

            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    return items


# -------------------------------------------------------------------------
# MCP Resources
# -------------------------------------------------------------------------

@mcp.resource("cora://recordings/recent")
def resource_recent_recordings() -> str:
    """JSON list of recent meetings in Cora."""
    recs = cora_list_recordings(limit=15)
    return json.dumps(recs, indent=2, ensure_ascii=False)


@mcp.resource("cora://people")
def resource_people_directory() -> str:
    """Directory of contacts and meeting participants."""
    people = db.get_all_people()
    return json.dumps(people, indent=2, ensure_ascii=False)


@mcp.resource("cora://action-items/pending")
def resource_pending_action_items() -> str:
    """All pending action items extracted across meetings."""
    items = cora_get_action_items(status="pending", limit=50)
    return json.dumps(items, indent=2, ensure_ascii=False)


@mcp.resource("cora://live-status")
def resource_live_status() -> str:
    """Current live recording and system state."""
    status = cora_get_live_status()
    return json.dumps(status, indent=2, ensure_ascii=False)


# -------------------------------------------------------------------------
# MCP Prompts
# -------------------------------------------------------------------------

@mcp.prompt()
def meeting_prep_brief(person_name_or_id: str) -> str:
    """Prepare an executive briefing before a call with a specific person.

    Consolidates past decisions, commitments, action items, and context.
    """
    return f"""Prepare a comprehensive executive meeting preparation brief for an upcoming conversation with: {person_name_or_id}.

Instructions:
1. Use `cora_list_people` to find the person's profile, role, and organization.
2. Use `cora_get_person` to inspect past meetings attended with them.
3. For the 2-3 most recent meetings, inspect the transcripts and summaries using `cora_get_recording`.
4. Synthesize:
   - Relationship summary & their key priorities
   - Agreements and decisions made in past calls
   - Outstanding or overdue action items for both parties
   - Strategic context or friction points to be aware of
   - 3 recommended objectives or calibrated questions for the upcoming conversation
"""


@mcp.prompt()
def executive_coaching_audit(recording_id: str) -> str:
    """Perform a deep executive coaching evaluation audit on a completed call."""
    return f"""Perform an in-depth communication and strategic evaluation audit on meeting: {recording_id}.

Instructions:
1. Retrieve the meeting transcript using `cora_get_transcript(recording_id='{recording_id}')`.
2. Retrieve the existing coaching report using `cora_get_coaching_report(recording_id='{recording_id}')`.
3. Provide an executive breakdown:
   - Bottom Line Up Front (BLUF): Was the main point established in the first 30 seconds?
   - Strategic leverage: How effectively were decisions directed and objections handled?
   - Verbal economy: Identify specific rambling passages and show how to cut words by 50% without losing meaning.
   - 3 highest-priority practice drills for the speaker's next call.
"""


def main():
    """Run the Cora MCP Server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
