"""View models for the UI: recording/dashboard payloads, participants, titles."""
from __future__ import annotations
import datetime as dt
import difflib
import json
import re
import shutil
import sys
import urllib.parse
from pathlib import Path
from typing import Any

import paths  # noqa: E402

ROOT = paths.APP_ROOT
APP = paths.PYTHON_DIR
STATIC = paths.STATIC_DIR
RECORDINGS = paths.RECORDINGS_DIR
INBOX = paths.INBOX_DIR
PEOPLE_DIR = paths.PEOPLE_DIR
COACH_DATA = paths.COACH_DATA_PATH
STATE = paths.STATE_PATH
PIPELINE = APP / "voice_memo_pipeline.py"
PYTHON = paths.venv_python()
API_TOKEN_FILE = paths.API_TOKEN_FILE
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
from participants import clean_and_validate_participant  # noqa: E402
import credentials  # noqa: E402
from plugin_registry import get_coaching_plugin  # noqa: E402
from diarization import (  # noqa: E402
    LATEST_AUDIO_MODEL,
    speaker_profiles,
    timestamp_seconds,
)
from api.core import ARCHETYPE_OPTIONS, INBOX, MODE_LABELS, PEOPLE_DIR, RECORDINGS, current_self_name, file_size_tree


def live_transcript_payload(recording_id: str) -> list[dict[str, Any]]:
    """The live chat-style feed for one recording, with screenshot entries
    resolved to a servable URL (their filename is stored bare in the DB —
    it can live in either the inbox, while still recording, or the
    archived folder, after processing)."""
    entries = db.get_live_transcript_entries(recording_id)
    for entry in entries:
        if entry.get("type") == "screenshot" and entry.get("image_path"):
            entry["image_url"] = f"/media-screenshot/{urllib.parse.quote(recording_id)}/{urllib.parse.quote(entry['image_path'])}"
    return entries


def fuzzy_match_person(raw_name: str, people: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Auto-link an AX-detected participant name to an existing Person:
    exact match first, then shared-token (handles "Jane" auto-linking to
    "Jane Doe" — AX often only gets a short display name, not the full
    one on file), then a high-confidence difflib ratio as a last resort.
    None rather than a low-confidence guess."""
    raw_lower = raw_name.strip().lower()
    if not raw_lower:
        return None
    raw_tokens = set(raw_lower.split())
    best: dict[str, Any] | None = None
    best_score = 0.0
    for person in people:
        name = (person.get("name") or "").strip()
        if not name:
            continue
        name_lower = name.lower()
        if raw_lower == name_lower:
            return person
        score = 0.9 if raw_tokens & set(name_lower.split()) else difflib.SequenceMatcher(None, raw_lower, name_lower).ratio()
        if score > best_score:
            best_score = score
            best = person
    return best if best_score >= 0.75 else None








def participants_payload(recording_id: str, folder: Path | None) -> list[dict[str, Any]]:
    """The AX-discovered roster (participants.json — live in inbox/ while
    recording, archived alongside the audio after), merged with any user
    edits (rename/hide/map-to-person) stored in
    metadata.participant_overrides, keyed by the raw name speaker-watch
    originally detected. Hidden entries (false-positive detections like
    stray junk names) are left out entirely rather than flagged, since
    "remove" here only means "stop showing me this," not "delete history."
    Absent an explicit map/unlink from the user, auto-suggests a Person via
    fuzzy_match_person() — recomputed fresh every call (not persisted) so
    it stays current as the People directory grows, and a person picking
    "Not linked" (an explicit person_id: null override) is never
    silently re-linked."""
    raw_path = (folder / "participants.json") if folder else (INBOX / f"{recording_id}_participants.json")
    try:
        raw_names = json.loads(raw_path.read_text()) if raw_path.exists() else []
    except Exception:
        raw_names = []
    if not isinstance(raw_names, list):
        raw_names = []

    metadata = db.get_recording_data(recording_id, "metadata") or {}
    overrides = metadata.get("participant_overrides") or {}
    people = db.get_all_people()
    people_by_id = {p["id"]: p for p in people}

    result = []
    seen = set()
    for name in raw_names:
        clean_name = clean_and_validate_participant(name)
        if not clean_name:
            continue
        if clean_name.lower() in seen:
            continue
        seen.add(clean_name.lower())

        ov = overrides.get(name) or overrides.get(clean_name) or {}
        if ov.get("hidden"):
            continue
        if "person_id" in ov:
            person = people_by_id.get(ov["person_id"])
        else:
            person = fuzzy_match_person(clean_name, people)
        result.append({
            "raw_name": clean_name,
            "display_name": ov.get("display_name") or (person["name"] if person else clean_name),
            "person_id": person["id"] if person else None,
            "person_name": person["name"] if person else None,
        })
    return result


def key_phrases_payload(recording_id: str) -> list[dict[str, str]]:
    """Terms Cora should bias transcription toward for this recording:
    manually-added ones (metadata.key_phrases_manual) plus whatever the
    structured-notes LLM already surfaced as keywords (call_summary.keywords)
    — merged and case-insensitively deduped, with metadata.key_phrases_removed
    letting a user permanently dismiss an auto-derived one without it
    reappearing next time call_summary is read (it isn't regenerated by
    this read, only by an actual reprocess)."""
    metadata = db.get_recording_data(recording_id, "metadata") or {}
    manual = metadata.get("key_phrases_manual") or []
    removed = {t.strip().lower() for t in (metadata.get("key_phrases_removed") or [])}
    call_summary = db.get_recording_data(recording_id, "call_summary") or {}
    auto = call_summary.get("keywords") or []

    seen: set[str] = set()
    result = []
    for term, source in [(t, "manual") for t in manual] + [(t, "auto") for t in auto]:
        key = str(term).strip().lower()
        if not key or key in seen or key in removed:
            continue
        seen.add(key)
        result.append({"term": str(term).strip(), "source": source})
    return result


def delivery_payload(raw_metrics: dict[str, Any], coaching: dict[str, Any], target_speaker: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if not raw_metrics or not target_speaker or raw_metrics.get("target_speaker") != target_speaker:
        return {}, {}
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
            "alternative_source": "gemini_coaching",
        }

    moments = {
        "best": moment((coaching.get("strongest_moments") or [None])[0], "best"),
        "fix": moment((coaching.get("improvement_moments") or [None])[0], "fix"),
    }
    for m in moments.values():
        if m:
            m["alternative_source"] = "coaching"
    timeline = metrics.setdefault("timeline", {})
    events = list(timeline.get("events", []))
    events.extend(value for value in moments.values() if value)
    timeline["events"] = sorted(events, key=lambda event: float(event.get("time", 0)))
    return metrics, moments


RAW_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+_\d{4}-\d{2}-\d{2}T")


def extract_smart_title_from_overview(overview: str) -> str:
    if not overview or overview.lower().startswith("no speech"):
        return ""
    first_sent = overview.split(".")[0].strip()
    cleaned = re.sub(
        r"^(?:the\s+(?:meeting|team|leadership\s+team|group|discussion)\s+(?:focused\s+on|discussed|reviewed|explored|covered|addressed|formalized|examined|analyzed|evaluated|centered\s+on|evaluated\s+the\s+performance\s+and\s+reliability\s+of)\s+)",
        "",
        first_sent,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    if len(cleaned) > 55:
        parts = re.split(r"\s+(?:,\s*|where\s+|which\s+|while\s+|with\s+|to\s+|and\s+|highlighting\s+|evaluating\s+|including\s+)", cleaned, flags=re.I)
        candidate = parts[0].strip()
        if len(candidate) < 20 and len(parts) > 1:
            candidate = f"{candidate} {parts[1]}".strip()
        cleaned = candidate[:60].strip()
    if cleaned and len(cleaned) >= 4:
        return cleaned[0].upper() + cleaned[1:]
    return ""


def display_title(metadata: dict[str, Any], call_summary: dict[str, Any], speaker_count: int, timestamp: str | None) -> str:
    """A human-readable label — never the raw meeting_<timestamp> folder name."""
    name = (metadata.get("recording_name") or "").strip()
    if name and not RAW_ID_PATTERN.match(name) and not name.startswith("Recording ·") and not name.startswith("Call with "):
        return name
    summary_title = (call_summary or {}).get("title", "").strip()
    if summary_title and len(summary_title) <= 70:
        return summary_title
    purpose = (call_summary or {}).get("purpose", "").strip()
    if purpose:
        return purpose if len(purpose) <= 70 else purpose[:67].rstrip() + "…"
    overview = (call_summary or {}).get("overview", "")
    derived = extract_smart_title_from_overview(overview)
    if derived:
        return derived
    topics = (call_summary or {}).get("topics") or []
    first_topic = (topics[0].get("title", "").strip() if topics else "")
    if first_topic:
        return first_topic
    when = ""
    if timestamp:
        try:
            when = dt.datetime.fromisoformat(timestamp).strftime("%-I:%M %p, %b %-d")
        except ValueError:
            when = ""
    if speaker_count > 1:
        return f"Call with {speaker_count} people" + (f" · {when}" if when else "")
    return "Recording" + (f" · {when}" if when else "")


PENDING_TITLES = {"recording": "Recording in progress…", "processing": "Processing…", "paused": "Recording paused"}


def pending_recording_item(rec_data: dict[str, Any]) -> dict[str, Any]:
    """A live placeholder row — created the instant Start was clicked, before
    any folder/audio file exists on disk. Never touch the filesystem here."""
    status = rec_data["status"]
    meta = rec_data.get("metadata") or {}
    arch_info = meta.get("archetype") or {}
    return {
        "id": rec_data["id"],
        "title": PENDING_TITLES.get(status, "Recording"),
        "recorded_at": rec_data.get("recorded_at"),
        "status": status,
        "duration_seconds": 0,
        "audio_url": None,
        "analysis_stage": status,
        "has_analysis": False,
        "has_diarization": False,
        "speaker_profiles": [],
        "speaker_count": 0,
        "scores": {},
        "call_summary": {},
        "size_bytes": 0,
        "archetype": arch_info.get("archetype_name"),
        "archetype_id": arch_info.get("archetype_id"),
        "archetype_info": arch_info,
    }


def recording_item(folder: Path | dict, detailed: bool = False) -> dict[str, Any]:
    if isinstance(folder, dict):
        rec_data = folder
        if rec_data.get("status") in PENDING_TITLES:
            return pending_recording_item(rec_data)
        folder = Path(rec_data["folder_path"])
        metadata = rec_data.get("metadata") or {}
        diarization = rec_data.get("diarization") or {}
        speaker_labels = rec_data.get("speaker_labels") or {"speakers": {}}
        call_summary = rec_data.get("call_summary") or diarization.get("call_summary", {})
        identity = rec_data.get("identity") or {}
        raw_coaching = rec_data.get("coaching") or {}
        raw_delivery = rec_data.get("delivery_metrics") or {}
    else:
        rec_data = db.get_recording(folder.name)
        if not rec_data:
            rec_data = {}
        metadata = rec_data.get("metadata") or {}
        diarization = rec_data.get("diarization") or {}
        speaker_labels = rec_data.get("speaker_labels") or {"speakers": {}}
        call_summary = rec_data.get("call_summary") or diarization.get("call_summary", {})
        identity = rec_data.get("identity") or {}
        raw_coaching = rec_data.get("coaching") or {}
        raw_delivery = rec_data.get("delivery_metrics") or {}

    audio = next((p for p in folder.iterdir() if p.is_file() and p.name.startswith("audio.")), None)
    # The archive keeps mic + system audio as separate tracks (needed for
    # speaker attribution); browsers would only play the first (your mic),
    # so the player gets the mixed playback copy when there is one.
    playback = folder / "playback.m4a"
    if playback.is_file():
        audio = playback
    timestamp = metadata.get("source_modified_at") or metadata.get("processed_at")
    profiles = speaker_profiles(diarization) if diarization else []
    
    matches = db.get_speaker_matches(folder.name) if not isinstance(folder, dict) else []

    for profile in profiles:
        match = next((m for m in matches if m["speaker_id"] == profile["speaker_id"]), None)
        if match and match.get("confidence") in ["high", "medium"]:
            person = db.get_person(match["person_id"])
            if person:
                profile["suggested_person"] = person
                profile["suggestion_confidence"] = match.get("confidence")
        
        profile["label"] = speaker_labels.get("speakers", {}).get(profile["speaker_id"], {})
    self_speaker_id = identity.get("speaker_id")
    
    # Check if there are any high/medium confidence matches to prefill
    suggested_self = None
    if matches and not self_speaker_id:
        for match in matches:
            if match.get("confidence") in ["high", "medium"]:
                p = db.get_person(match["person_id"])
                if p and p.get("is_self"):
                    suggested_self = match["speaker_id"]
                    break
    
    coaching = raw_coaching if (
        diarization
        and self_speaker_id
        and (raw_coaching.get("model") in {LATEST_AUDIO_MODEL, "gemini-3.7-flash", "gemini-3.8-flash", "gemini-2.5-flash"} or bool(raw_coaching.get("executive_assessment")))
        and raw_coaching.get("target_speaker") == self_speaker_id
    ) else {}
    delivery_metrics, delivery_moments = delivery_payload(raw_delivery, coaching, self_speaker_id)
    self_profile = next((p for p in profiles if p["speaker_id"] == self_speaker_id), {})
    segments = diarization.get("segments", [])
    duration = max((timestamp_seconds(segment.get("end", "")) for segment in segments), default=0)
    if not diarization:
        stage = "needs_diarization"
    elif not self_speaker_id:
        stage = "needs_speaker_confirmation"
    elif not coaching:
        stage = "ready_for_coaching"
    else:
        stage = "coached"
    scores = {
        name: int(value.get("score", 0))
        for name, value in coaching.get("scores", {}).items()
        if isinstance(value, dict)
    }
    if scores:
        scores["overall"] = round(sum(scores.values()) / len(scores))
    languages = [segment.get("language") for segment in segments if segment.get("language")]
    arch_info = coaching.get("archetype") or metadata.get("archetype") or {}
    archetype_name = arch_info.get("archetype_name")
    archetype_id = arch_info.get("archetype_id")
    item = {
        "id": folder.name,
        "folder_path": str(folder.resolve()),
        "folder_uri": folder.resolve().as_uri(),
        "title": display_title(metadata, call_summary, len(profiles), timestamp),
        "recorded_at": timestamp,
        "duration_seconds": float(duration or metadata.get("duration_seconds") or 0),
        "language": languages[0] if languages else metadata.get("detected_language"),
        "audio_url": f"/media/{urllib.parse.quote(folder.name)}/{urllib.parse.quote(audio.name)}" if audio else None,
        "analysis_stage": stage,
        "has_analysis": bool(coaching),
        "has_diarization": bool(diarization),
        "needs_speaker_confirmation": stage == "needs_speaker_confirmation",
        "suggested_self_speaker_id": suggested_self,
        "self_speaker_id": self_speaker_id,
        "speaker_profiles": profiles,
        "speaker_count": len(profiles),
        "mode": coaching.get("mode"),
        "mode_label": MODE_LABELS.get(coaching.get("mode"), coaching.get("mode")),
        "archetype": archetype_name,
        "archetype_id": archetype_id,
        "archetype_info": arch_info,
        "participant_names": sorted({
            name for name in (
                (profile.get("label", {}).get("name") or profile.get("suggested_person", {}).get("name"))
                for profile in profiles
            ) if name
        }),
        "meeting_tool": metadata.get("meeting_tool"),
        "folder_id": metadata.get("folder_id"),
        "turn_count": len(segments),
        "scores": scores,
        "word_count": self_profile.get("words"),
        "speaking_seconds": self_profile.get("speaking_seconds"),
        "top_priority": ((coaching.get("improvement_moments") or [{}])[0]).get("observation"),
        "has_gemini_coaching": bool(coaching),
        "has_delivery_metrics": bool(delivery_metrics),
        "gemini_coaching": coaching,
        "call_summary": call_summary,
        "size_bytes": audio.stat().st_size if audio else 0,
    }
    if detailed:
        transcript_path = folder / "transcript_diarized.md"
        transcript = transcript_path.read_text(errors="replace") if transcript_path.exists() else ""
        enhanced_notes_path = folder / "enhanced_notes.md"
        enhanced_notes = enhanced_notes_path.read_text(errors="replace") if enhanced_notes_path.exists() else ""
        versions_dir = folder / "versions"
        versions = sorted((p.name for p in versions_dir.iterdir() if p.is_dir()), reverse=True) if versions_dir.is_dir() else []
        transcript_segments = []
        for segment in segments:
            entry = speaker_labels.get("speakers", {}).get(segment.get("speaker_id"), {})
            transcript_segments.append({
                **segment,
                "speaker_name": entry.get("name") or segment.get("speaker_id"),
                "speaker_role": entry.get("role", ""),
                "speaker_organization": entry.get("organization", ""),
            })
        item.update({
            "metadata": metadata,
            "diarization": diarization,
            "identity": identity,
            "transcript": transcript,
            "enhanced_notes": enhanced_notes,
            "versions": versions,
            "continues_recording_id": metadata.get("continues_recording_id"),
            "gemini_coaching": coaching,
            "delivery_metrics": delivery_metrics,
            "delivery_moments": delivery_moments,
            "speaker_labels": speaker_labels,
            "transcript_segments": transcript_segments,
            "self_name": current_self_name(),
            "notes": db.get_notes(folder.name),
            "summaries": db.get_summaries(folder.name),
        })
    return item


def _parse_recorded_at(value: str | None) -> dt.datetime:
    """Parse recorded_at for sorting. Sites writing this field disagree on
    format — Python's own writes use a local-offset ISO string (+05:30),
    but main.js sends `new Date().toISOString()` (UTC, trailing "Z") for a
    just-started recording. Comparing those as raw strings (the old
    behavior) doesn't account for the offset at all, so a recording ahead
    of UTC could sort as older than it really is — a live "recording" row
    could appear several rows down instead of at the top. Always parse to
    a real, timezone-aware datetime instead."""
    if not value:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except ValueError:
        return dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def all_recordings() -> list[dict[str, Any]]:
    rows = db.get_all_recordings()
    items = []
    for row in rows:
        # A recording started via pause/resume (or the detail page's
        # "Continue this meeting" button) carries continues_recording_id and
        # is always transient: the pipeline merges its content into the
        # parent recording and deletes this row once processing finishes
        # (pipeline/runner.py). Showing it in the dashboard in the meantime
        # makes one meeting look like two — the parent sitting there and
        # this one going through its own recording/processing status — so
        # it's left out of the main list entirely; its content still shows
        # up, just under the parent, once the merge completes.
        if (row.get("metadata") or {}).get("continues_recording_id"):
            continue
        if row.get("status") in PENDING_TITLES:
            items.append(recording_item(row))
            continue
        folder = Path(row["folder_path"])
        if not folder.is_dir():
            continue
        item = recording_item(row)
        # Keep meetings whose audio was deleted after processing
        # (retain_audio off) — the transcript and notes are what matter.
        if item.get("audio_url") or item.get("analysis_stage") != "needs_diarization":
            items.append(item)
    return sorted(items, key=lambda x: _parse_recorded_at(x.get("recorded_at")), reverse=True)


def dashboard_payload() -> dict[str, Any]:
    records = all_recordings()
    disk = shutil.disk_usage(paths.DATA_DIR)
    # get_public_status() shells out to the macOS Keychain (a few hundred ms
    # per call) — call it once and reuse, rather than once per field below.
    cred_status = credentials.get_public_status()
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "storage": {
            # ROOT doubles as this repo's checkout (node_modules, .venv, .git,
            # build output, etc.) as well as the data directory — walking the
            # whole thing here would both misreport "archive size" as the
            # dev environment's footprint and take seconds. Only the actual
            # data directories count.
            "archive_bytes": file_size_tree(RECORDINGS) + file_size_tree(INBOX) + file_size_tree(PEOPLE_DIR),
            "recordings_bytes": file_size_tree(RECORDINGS),
            "disk_free_bytes": disk.free, "disk_total_bytes": disk.total,
            "estimated_days_at_four_hours": round(disk.free / (44.7 * 4 * 1_000_000), 1),
        },
        "recordings": records,
        "modes": ARCHETYPE_OPTIONS,
        "plugins": {
            "coaching": {"enabled": get_coaching_plugin() is not None},
        },
        "ai_engine": {
            "available": credentials.is_available(),
            "model": LATEST_AUDIO_MODEL,
            "sends_original_audio": True,
            "speaker_diarization": True,
            "analysis_engine": "Google Vertex AI" if cred_status.get("provider") == "vertex" else "Google AI Studio",
            "provider": cred_status.get("provider", "vertex"),
            "project": cred_status.get("vertex_project"),
            "location": cred_status.get("vertex_location"),
            "auth_type": cred_status.get("vertex_auth_type"),
            "storage_mode": cred_status.get("storage_mode"),
        },
    }
