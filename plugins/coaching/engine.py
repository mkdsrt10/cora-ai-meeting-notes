#!/usr/bin/env python3
"""Coaching plugin engine: archetypes, scoring rubrics, delivery metrics.

Everything here is reached only through plugin_registry.get_coaching_plugin(),
never imported directly by core code. It depends on diarization.py (core) for
shared Gemini-audio plumbing (client, interact_with_audio, speaker_profiles,
timestamp_seconds) but core never depends back on this module.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

import db
from diarization import (
    LATEST_AUDIO_MODEL,
    atomic_json,
    client_for_key,
    find_audio,
    interact_with_audio,
    now_iso,
    read_json,
    speaker_profiles,
    timestamp_seconds,
)

FILLER_PHRASES = (
    "you know", "kind of", "sort of", "theek hai", "thik hai", "ek baar",
    "basically", "actually", "literally", "matlab", "right", "like", "bro",
    "umm", "um", "uhh", "uh", "hmm",
)


def _rms_db(frame: np.ndarray) -> float:
    if not len(frame):
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(frame), dtype=np.float64)))
    return max(-120.0, 20.0 * np.log10(max(rms, 1e-6)))


def _pitch_hz(frame: np.ndarray, sample_rate: int) -> float | None:
    if len(frame) < sample_rate * 0.025 or _rms_db(frame) < -45:
        return None
    signal = (frame - np.mean(frame)) * np.hanning(len(frame))
    size = 1 << (len(signal) * 2 - 1).bit_length()
    spectrum = np.fft.rfft(signal, size)
    correlation = np.fft.irfft(spectrum * np.conj(spectrum), size)[: len(signal)]
    minimum_lag = max(1, int(sample_rate / 350))
    maximum_lag = min(len(correlation) - 1, int(sample_rate / 75))
    if maximum_lag <= minimum_lag or correlation[0] <= 0:
        return None
    lag = minimum_lag + int(np.argmax(correlation[minimum_lag : maximum_lag + 1]))
    if correlation[lag] / correlation[0] < 0.25:
        return None
    return round(sample_rate / lag, 2)


def _excerpt(text: str, limit: int = 180) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _repeated_phrases(text: str) -> list[dict[str, Any]]:
    tokens = [token.lower() for token in re.findall(r"\b[\w'-]+\b", text)]
    ignored = {"the", "a", "an", "and", "to", "of", "is", "it", "in", "for", "so"}
    counts: dict[str, int] = {}
    for width in (2, 3):
        for index in range(len(tokens) - width + 1):
            group = tokens[index : index + width]
            if all(token in ignored for token in group):
                continue
            phrase = " ".join(group)
            counts[phrase] = counts.get(phrase, 0) + 1
    return [
        {"phrase": phrase, "count": count}
        for phrase, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= 3
    ][:5]


def compute_delivery_metrics(
    samples: np.ndarray,
    sample_rate: int,
    diarization: dict[str, Any],
    target_speaker: str,
    goals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate factual, identity-gated delivery mechanics from decoded mono PCM."""
    goals = goals or {}
    target = [segment for segment in diarization.get("segments", []) if segment.get("speaker_id") == target_speaker]
    intervals = [
        (max(0.0, float(timestamp_seconds(item.get("start", "")))), max(0.0, float(timestamp_seconds(item.get("end", "")))), item)
        for item in target
    ]
    speaking_seconds = sum(max(0.0, end - start) for start, end, _ in intervals)
    text = " ".join(str(item.get("text", "")) for item in target)
    words = len(re.findall(r"\b[\w'-]+\b", text))
    pace = round(words * 60 / speaking_seconds, 1) if speaking_seconds else 0.0
    pace_min = float(goals.get("pace_min", 120))
    pace_max = float(goals.get("pace_max", 165))

    duration = len(samples) / sample_rate if sample_rate else 0.0
    step_seconds = 0.5
    frame_seconds = 0.08
    series: list[dict[str, Any]] = []
    target_frame_db: list[float] = []
    target_pitch: list[float] = []
    for moment in np.arange(0, duration, step_seconds):
        active = next((item for start, end, item in intervals if start <= moment < end), None)
        start_index = int(moment * sample_rate)
        frame = samples[start_index : start_index + int(frame_seconds * sample_rate)]
        volume = round(_rms_db(frame), 2)
        pitch = _pitch_hz(frame, sample_rate) if active is not None else None
        local_pace = None
        if active is not None:
            segment_seconds = max(1.0, timestamp_seconds(active.get("end", "")) - timestamp_seconds(active.get("start", "")))
            local_pace = round(len(re.findall(r"\b[\w'-]+\b", str(active.get("text", "")))) * 60 / segment_seconds, 1)
            if pitch:
                target_frame_db.append(volume)
                target_pitch.append(pitch)
        series.append({
            "time": round(float(moment), 2), "volume_db": volume if active is not None else None,
            "pitch_hz": pitch, "pace_wpm": local_pace,
            "speaker_id": active.get("speaker_id") if active else None,
        })

    pause_events: list[dict[str, Any]] = []
    silence_seconds = 0.0
    pause_frame_seconds = 0.1
    for segment_start, segment_end, segment in intervals:
        cursor = segment_start
        run_start: float | None = None
        while cursor < segment_end:
            index = int(cursor * sample_rate)
            frame = samples[index : index + int(pause_frame_seconds * sample_rate)]
            silent = _rms_db(frame) < -45
            if silent and run_start is None:
                run_start = cursor
            if not silent and run_start is not None:
                length = cursor - run_start
                silence_seconds += length
                if length >= 0.6:
                    pause_events.append({
                        "type": "pause", "time": round(run_start, 2), "end": round(cursor, 2),
                        "duration": round(length, 2), "severity": "long" if length >= 2 else "pause",
                        "excerpt": _excerpt(segment.get("text", "")),
                        "explanation": "A sustained silence occurred inside this turn.",
                        "alternative": "State the next point directly, or announce that you need a moment to check something.",
                        "alternative_source": "local_template",
                    })
                run_start = None
            cursor += pause_frame_seconds
        if run_start is not None:
            length = segment_end - run_start
            silence_seconds += length
            if length >= 0.6:
                pause_events.append({
                    "type": "pause", "time": round(run_start, 2), "end": round(segment_end, 2),
                    "duration": round(length, 2), "severity": "long" if length >= 2 else "pause",
                    "excerpt": _excerpt(segment.get("text", "")),
                    "explanation": "A sustained silence occurred inside this turn.",
                    "alternative": "State the next point directly, or announce that you need a moment to check something.",
                    "alternative_source": "local_template",
                })

    filler_events: list[dict[str, Any]] = []
    filler_counts: dict[str, int] = {}
    for segment_start, segment_end, segment in intervals:
        segment_text = str(segment.get("text", ""))
        matches = []
        for phrase in FILLER_PHRASES:
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", segment_text, re.I):
                matches.append((match.start(), match.end(), phrase, match.group(0)))
        matches.sort()
        accepted: list[tuple[int, int, str, str]] = []
        for match in matches:
            if any(match[0] < prior[1] and match[1] > prior[0] for prior in accepted):
                continue
            accepted.append(match)
        for start_char, _, phrase, rendered in accepted:
            fraction = start_char / max(1, len(segment_text))
            moment = segment_start + fraction * max(0, segment_end - segment_start)
            filler_counts[phrase] = filler_counts.get(phrase, 0) + 1
            filler_events.append({
                "type": "filler", "time": round(moment, 2), "phrase": rendered,
                "excerpt": _excerpt(segment_text),
                "explanation": f"“{rendered}” adds verbal clutter without changing the meaning.",
                "alternative": re.sub(rf"(?<!\w){re.escape(rendered)}(?!\w)[, ]*", "", segment_text, count=1, flags=re.I).strip(),
                "alternative_source": "local_edit",
            })
    filler_count = sum(filler_counts.values())
    filler_rate = round(filler_count * 60 / speaking_seconds, 2) if speaking_seconds else 0.0

    pitch_range = 0.0
    if len(target_pitch) >= 2:
        median_log_pitch = float(np.median(np.log2(target_pitch)))
        corrected_pitch = [float(value * (2 ** round(median_log_pitch - np.log2(value)))) for value in target_pitch]
        corrected_index = 0
        for point in series:
            if point.get("pitch_hz"):
                point["pitch_hz"] = round(corrected_pitch[corrected_index], 2)
                corrected_index += 1
        low, high = np.percentile(corrected_pitch, [10, 90])
        if low > 0:
            pitch_range = round(float(12 * np.log2(high / low)), 2)
    volume_range = 0.0
    if len(target_frame_db) >= 2:
        low, high = np.percentile(target_frame_db, [10, 90])
        volume_range = round(float(high - low), 2)

    if pace_min <= pace <= pace_max:
        pace_status = "In your target range"
    elif pace < pace_min:
        pace_status = "Below your target range"
    else:
        pace_status = "Above your target range"
    pitch_status = "Varied" if pitch_range >= 6 else "Moderate" if pitch_range >= 3 else "Limited variation"
    volume_status = "Expressive" if volume_range >= 10 else "Moderate" if volume_range >= 7 else "Slightly flat"
    filler_target = float(goals.get("filler_target_per_minute", 2.0))
    filler_status = "At or below target" if filler_rate <= filler_target else "Above target"

    return {
        "schema_version": "1.0", "target_speaker": target_speaker,
        "sample_rate": sample_rate, "speaking_seconds": round(speaking_seconds, 2),
        "metrics": {
            "pace": {"value": pace, "unit": "WPM", "target_min": pace_min, "target_max": pace_max, "status": pace_status},
            "pause_control": {
                "silence_percent": round(100 * silence_seconds / speaking_seconds, 1) if speaking_seconds else 0.0,
                "long_pause_count": sum(1 for event in pause_events if event["severity"] == "long"),
                "pauses_per_minute": round(len(pause_events) * 60 / speaking_seconds, 2) if speaking_seconds else 0.0,
                "status": "Review long pauses" if any(event["severity"] == "long" for event in pause_events) else "Controlled",
            },
            "pitch_variety": {"range_semitones": pitch_range, "unit": "semitones", "status": pitch_status},
            "volume_variety": {"range_db": volume_range, "unit": "dB", "status": volume_status},
            "fillers": {
                "per_minute": filler_rate, "count": filler_count, "unit": "/min", "status": filler_status,
                "phrases": [{"phrase": key, "count": value} for key, value in sorted(filler_counts.items(), key=lambda item: (-item[1], item[0]))],
                "repeated_phrases": _repeated_phrases(text),
            },
        },
        "timeline": {
            "duration_seconds": round(duration, 2), "series": series,
            "events": sorted(pause_events + filler_events, key=lambda event: event["time"]),
            "speaker_segments": [
                {"speaker_id": item.get("speaker_id"), "start": timestamp_seconds(item.get("start", "")), "end": timestamp_seconds(item.get("end", "")), "is_target": item.get("speaker_id") == target_speaker}
                for item in diarization.get("segments", [])
            ],
        },
    }


def analyze_delivery(folder: Path, target_speaker: str, goals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decode archived audio and persist identity-bound factual delivery metrics."""
    audio = find_audio(folder)
    diarization = db.get_recording_data(folder.name, "diarization")
    valid = {profile["speaker_id"] for profile in speaker_profiles(diarization)}
    if target_speaker not in valid:
        raise ValueError(f"Unknown speaker: {target_speaker}")
    completed = subprocess.run(
        [
            "/opt/homebrew/bin/ffmpeg", "-v", "error", "-i", str(audio),
            "-ac", "1", "-ar", "16000", "-f", "f32le", "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    samples = np.frombuffer(completed.stdout, dtype="<f4").copy()
    result = compute_delivery_metrics(samples, 16_000, diarization, target_speaker, goals)
    result.update({
        "source": "local_objective_audio_analysis",
        "audio_file": audio.name,
        "analyzed_at": now_iso(),
        "identity": target_speaker,
    })
    atomic_json(folder / "delivery_metrics.json", result)
    db.update_recording_data(folder.name, "delivery_metrics", result)
    return result


ARCHETYPES: dict[int, dict[str, Any]] = {
    1: {"archetype_id": 1, "archetype_name": "Technical Steering", "description": "Architecture, protocol design, schema, and trade-off resolutions", "coaching_enabled": True},
    2: {"archetype_id": 2, "archetype_name": "Execution Control", "description": "Standups, sprint reviews, blocker sweeps, rapid updates", "coaching_enabled": True},
    3: {"archetype_id": 3, "archetype_name": "Talent Multiplication", "description": "1:1 mentoring, junior walkthroughs, mental model transfers", "coaching_enabled": True},
    4: {"archetype_id": 4, "archetype_name": "Strategic L10 / Cross-Functional", "description": "Cross-functional alignment, EOS format, roadmaps, friction resolution", "coaching_enabled": True},
    5: {"archetype_id": 5, "archetype_name": "Client Solutioning", "description": "Client demos, commercial alignment, ROI defense, scope boundaries", "coaching_enabled": True},
    6: {"archetype_id": 6, "archetype_name": "Talent Acquisition", "description": "Interviews, evaluating candidate technical depth, vision selling", "coaching_enabled": True},
    7: {"archetype_id": 7, "archetype_name": "Solo Ideation", "description": "Voice memo, unstructured dictation, auto-structuring into specs", "coaching_enabled": False},
    8: {"archetype_id": 8, "archetype_name": "Content Creation", "description": "Async Loom demo, scripted presentation, zero filler tolerance", "coaching_enabled": True},
}


def build_classification_prompt(summary: dict[str, Any], speaker_count: int, title: str) -> str:
    return f"""You are Cora's Meeting Classifier.

Your job is to analyze the meeting summary, keywords, and participant count, and classify the session into exactly one of the 8 Archetypes below.

THE 8 ARCHETYPES:
1. Technical Steering (Architecture, schema, MCP, technical decisions. Usually 2-4 speakers).
2. Execution Control (Standups, blocker sweeps, sprints, rapid updates. Usually 4+ speakers).
3. Talent Multiplication (1:1 mentoring, walkthroughs, teaching junior devs. 2 speakers).
4. Strategic L10 / Cross-Functional (High-level alignment, EOS format, roadmaps, cross-team. Usually 5+ speakers).
5. Client Solutioning (External commercial, Hackathons, H2S, defending scope/cost. Usually 2-5 speakers).
6. Talent Acquisition (Interviewing candidates, evaluating depth. Usually 2 speakers).
7. Solo Ideation (Voice memo, brainstorming, untethered dictation. Always 1 speaker).
8. Content Creation (Scripted video recording, demo, Loom. Always 1 speaker).

MEETING DATA:
Title: {title}
Speaker Count: {speaker_count}
Overview: {summary.get('overview', '')}
Purpose: {summary.get('purpose', '')}
Keywords: {', '.join(summary.get('keywords', []))}

Respond strictly with the classification JSON schema."""


def classification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "archetype_id": {
                "type": "integer",
                "description": "Integer ID of the archetype (1 through 8)"
            },
            "archetype_name": {
                "type": "string",
                "description": "Name of the archetype"
            },
            "explanation": {
                "type": "string",
                "description": "Why this archetype was selected based on the data"
            },
            "coaching_enabled": {
                "type": "boolean",
                "description": "True for archetypes 1-6 and 8. False for archetype 7 (Solo Ideation)."
            }
        },
        "required": ["archetype_id", "archetype_name", "explanation", "coaching_enabled"]
    }


def build_coaching_prompt(diarization: dict[str, Any], target_speaker: str, archetype: dict[str, Any]) -> str:
    transcript = "\n".join(
        f"[{item.get('start')}-{item.get('end')}] {item.get('speaker_id')}: {item.get('text')}"
        for item in diarization.get("segments", [])
    )

    archetype_id = archetype.get("archetype_id", 1)

    # Archetype 7: Auto-Structuring (No coaching)
    if archetype_id == 7:
        return f"""You are an elite Technical Writer and Thought Partner.

This is an Archetype 7: Solo Ideation (Voice Memo) session.
Target Speaker: {target_speaker}

Your goal is NOT to coach delivery or pacing. Your goal is to auto-structure the rambling audio into a clean, highly readable Markdown spec document.

Extract and format the content into these three sections:
1. Core Thesis (The main idea being brainstormed)
2. Architecture Dependencies (What systems, tools, or concepts are involved)
3. Open Questions (What needs to be solved later)

Transcript:
---
{transcript}
---
Return the requested structured JSON."""

    # Dynamic Coaching Instructions based on Archetype
    coaching_rules = ""
    if archetype_id == 1:
        coaching_rules = "- Measure Headline-First delivery: Did the speaker state the verdict/direction before explaining the mechanics?\n- Check Boundary Specification: Were hard SLAs, token budgets, or security constraints defined?\n- Evaluate Decision Clarity."
    elif archetype_id == 2:
        coaching_rules = "- Evaluate Facilitation: Did the speaker intercept tangents and apply the 'Parking Lot' rule?\n- Check Rule-of-4 Rigor: Do action items have an Owner, Action, and Deadline?\n- Evaluate if the speaker kept their airtime lean to let engineers give updates."
    elif archetype_id == 3:
        coaching_rules = "- Measure Socratic Scaffolding: Did the speaker ask questions before giving answers?\n- Evaluate The Synthesis Test: Did the speaker force the learner to verbally summarize the plan at the end?\n- Flag if the speaker monologued and solved the code for the learner."
    elif archetype_id == 4:
        coaching_rules = "- Evaluate Translation: Did the speaker translate engineering bottlenecks into product/launch impact?\n- Check IDS Rigor (Identify, Discuss, Solve): Were issues assigned a problem-solver?"
    elif archetype_id == 5:
        coaching_rules = "- Evaluate Value-First Framing: Was the business outcome/SLA stated before technical pipeline details?\n- Measure Scope Defense: Did the speaker firmly push back on un-scoped requests (e.g., bucketing into Phase 2)?\n- Check Commercial Lock-in: Was a clear sign-off milestone established?"
    elif archetype_id == 6:
        coaching_rules = "- Evaluate Intro Concision: Was the company pitch under 2 minutes?\n- Measure Depth Probing: Did the speaker ask progressive follow-up questions (Why? What broke?) to test real depth?\n- Check if the candidate was given enough airtime to speak."
    elif archetype_id == 8:
        coaching_rules = "- Evaluate The 10-Second Hook: Was the precise value of the video stated immediately?\n- Check for absolute verbal polish (zero tolerance for filler words in scripted content)."

    return f"""You are an elite, demanding, evidence-grounded executive communication coach.

TARGET SPEAKER: {target_speaker}
ARCHETYPE CLASSIFICATION: {archetype.get("archetype_name")} (ID: {archetype_id})

Identity boundary:
- Coach and score only {target_speaker}. This speaker has been confirmed as the user.
- Other speakers exist only as conversational context. Never attribute their words, fillers, tone, mistakes, or behavior to {target_speaker}.
- Ground every finding in a timestamp and/or exact short quote from {target_speaker}.

Specific Coaching Mandates for this Archetype:
{coaching_rules}

Evaluate the speaker based strictly on the mandates above. Every score must be an integer on a 0 to 100 scale, where 50 is inconsistent, 75 is effective, and 90 is exceptional.

Transcript for reference:
---
{transcript}
---
Return only the requested structured result."""


def score_schema() -> dict[str, Any]:
    evidence = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Integer score from 0 to 100."},
            "assessment": {"type": "string"},
            "evidence": evidence,
        },
        "required": ["score", "assessment", "evidence"],
    }


def coaching_schema(archetype_id: int) -> dict[str, Any]:
    if archetype_id == 7:
        return {
            "type": "object",
            "properties": {
                "target_speaker": {"type": "string"},
                "executive_assessment": {
                    "type": "string",
                    "description": "Clean, highly readable Markdown formatted structured spec document with sections: Core Thesis, Architecture Dependencies, Open Questions, and Next Actions."
                },
                "structured_memo": {
                    "type": "object",
                    "properties": {
                        "core_thesis": {"type": "string", "description": "The primary thesis, goal, or technical vision being brainstormed"},
                        "architecture_dependencies": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Systems, frameworks, schemas, pipelines, or architectural components involved"
                        },
                        "open_questions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Unresolved questions, trade-offs, or decisions needing answers"
                        },
                        "action_items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Immediate deliverables, assignments, or experiments to run"
                        }
                    },
                    "required": ["core_thesis", "architecture_dependencies", "open_questions"]
                }
            },
            "required": ["target_speaker", "executive_assessment", "structured_memo"]
        }

    moment = {
        "type": "object",
        "properties": {
            "timestamp": {"type": "string"},
            "quote": {"type": "string"},
            "observation": {"type": "string"},
            "better_response": {"type": "string"},
        },
        "required": ["timestamp", "quote", "observation", "better_response"],
    }

    score_names = ["clarity", "coherence", "concision", "responsiveness", "influence", "listener_direction", "delivery", "storytelling"]

    return {
        "type": "object",
        "properties": {
            "target_speaker": {"type": "string"},
            "executive_assessment": {"type": "string"},
            "scores": {
                "type": "object",
                "properties": {name: score_schema() for name in score_names},
                "required": score_names,
            },
            "counterpart_reception": {
                "type": "object",
                "properties": {
                    "alignment_status": {"type": "string"},
                    "friction_level": {"type": "string"},
                    "key_metric_label": {"type": "string"},
                    "key_metric_value": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                    "speaker": {"type": "string"},
                    "timestamp": {"type": "string"}
                },
                "required": ["alignment_status", "friction_level", "key_metric_label", "key_metric_value", "evidence_quote", "speaker", "timestamp"]
            },
            "delivery_qualitative": {
                "type": "array",
                "items": {"type": "string"}
            },
            "jtbd": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "context": {"type": "string"}
                    },
                    "required": ["task", "context"]
                }
            },
            "structured_summary": {
                "type": "object",
                "properties": {
                    "overview": {"type": "string"},
                    "key_decision": {"type": "string"},
                    "edge_cases": {"type": "string"}
                },
                "required": ["overview", "key_decision", "edge_cases"]
            },
            "action_items_rule_of_4": {
                "type": "array",
                "items": {"type": "string"}
            },
            "crucial_turning_point": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "speaker": {"type": "string"},
                        "timestamp": {"type": "string"},
                        "text": {"type": "string"},
                        "is_target": {"type": "boolean"},
                        "is_highlight": {"type": "boolean"}
                    },
                    "required": ["speaker", "timestamp", "text", "is_target", "is_highlight"]
                }
            },
            "improvement_moments": {"type": "array", "items": moment},
        },
        "required": ["target_speaker", "executive_assessment", "scores", "counterpart_reception", "delivery_qualitative", "jtbd", "structured_summary", "action_items_rule_of_4", "crucial_turning_point", "improvement_moments"]
    }


def classify_meeting(folder: Path, client=None) -> dict[str, Any]:
    import credentials
    from google.genai import types
    import json as _json

    summary = read_json(folder / "call_summary.json")
    diarization = db.get_recording_data(folder.name, "diarization")
    title = summary.get("source_recording", folder.name)
    speaker_count = len(diarization.get("speakers", []))

    prompt = build_classification_prompt(summary, speaker_count, title)

    # We can use text-only generation for classification
    client = client or client_for_key()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=classification_schema(),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        temperature=0.2,
    )
    res = client.models.generate_content(
        model=credentials.get_default_model(),
        contents=prompt,
        config=config,
    )
    result = _json.loads(res.text)

    # Save the classification
    atomic_json(folder / "archetype_classification.json", result)
    db.update_recording_data(folder.name, "metadata", {**db.get_recording_data(folder.name, "metadata"), "archetype": result})
    return result


def resolve_archetype(mode_or_id: str | int | None, folder: Path, client=None) -> dict[str, Any]:
    if mode_or_id:
        clean = str(mode_or_id).strip().lower()
        if clean not in ["auto", "free", "none", ""]:
            # Direct integer check
            for aid, data in ARCHETYPES.items():
                if str(aid) == clean:
                    return {**data, "explanation": f"Mode selected: {data['archetype_name']}."}
                slug = data["archetype_name"].lower().replace(" ", "_").replace("/", "_").replace("-", "_")
                if slug in clean or clean in slug:
                    return {**data, "explanation": f"Mode selected: {data['archetype_name']}."}
                if clean in ["1:1", "one_on_one", "mentoring"] and aid == 3:
                    return {**data, "explanation": "Mode selected: 1:1 Mentoring."}
                if clean in ["standup", "sprint"] and aid == 2:
                    return {**data, "explanation": "Mode selected: Execution Control."}
                if clean in ["arch", "architecture", "technical"] and aid == 1:
                    return {**data, "explanation": "Mode selected: Technical Steering."}
                if clean in ["l10", "strategy", "cross_functional"] and aid == 4:
                    return {**data, "explanation": "Mode selected: Strategic L10."}
                if clean in ["client", "sales", "demo", "solutioning"] and aid == 5:
                    return {**data, "explanation": "Mode selected: Client Solutioning."}
                if clean in ["interview", "hiring"] and aid == 6:
                    return {**data, "explanation": "Mode selected: Talent Acquisition."}
                if clean in ["memo", "voice_memo", "solo", "braindump"] and aid == 7:
                    return {**data, "explanation": "Mode selected: Solo Ideation."}

    # Check if recording metadata already has an archetype
    meta = db.get_recording_data(folder.name, "metadata") or {}
    existing_arch = meta.get("archetype")
    if isinstance(existing_arch, dict) and existing_arch.get("archetype_id"):
        return existing_arch

    return classify_meeting(folder, client)


def coach(folder: Path, mode: str = "auto", speaker_id: str | None = None, model: str = LATEST_AUDIO_MODEL, client=None, goals: dict[str, Any] | None = None) -> dict[str, Any]:
    diarization = db.get_recording_data(folder.name, "diarization")
    if not diarization:
        raise FileNotFoundError("Run speaker separation first")
    if speaker_id is None:
        identity = db.get_recording_data(folder.name, "identity")
        if not identity:
            raise ValueError("Confirm your speaker identity before coaching")
        speaker_id = identity.get("speaker_id")
    valid = {profile["speaker_id"] for profile in speaker_profiles(diarization)}
    if speaker_id not in valid:
        raise ValueError(f"Unknown speaker: {speaker_id}")

    # Pass 1: Resolve Archetype (from explicit mode, existing metadata, or auto-classification)
    archetype = resolve_archetype(mode, folder, client)

    audio = find_audio(folder)

    # Pass 2: Coach based on the Archetype
    result = interact_with_audio(audio, build_coaching_prompt(diarization, speaker_id, archetype), coaching_schema(archetype.get("archetype_id", 1)), model, client)
    result.update({
        "model": model,
        "analyzed_at": now_iso(),
        "mode": mode,
        "archetype": archetype,
        "target_speaker": speaker_id,
        "identity": "User",
        "privacy_note": "Original audio was sent to Google Gemini and the remote Files API copy was deleted after analysis.",
    })
    atomic_json(folder / "gemini_coaching.json", result)
    db.update_recording_data(folder.name, "coaching", result)
    (folder / "gemini_coaching.md").write_text(render_coaching_markdown(result))

    if archetype.get("coaching_enabled", True):
        analyze_delivery(folder, speaker_id, goals)

    return result


def render_coaching_markdown(result: dict[str, Any]) -> str:
    arch = result.get("archetype", {})
    if arch.get("archetype_id") == 7:
        memo = result.get("structured_memo", {})
        lines = [
            f"# {arch.get('archetype_name', 'Solo Ideation')} — Structured Spec",
            "",
            arch.get("explanation", ""),
            "",
            "## Executive Assessment & Document",
            "",
            result.get("executive_assessment", ""),
            "",
            "## Core Thesis",
            "",
            memo.get("core_thesis", ""),
            "",
            "## Architecture Dependencies",
            "",
        ]
        lines += [f"- {item}" for item in memo.get("architecture_dependencies", [])]
        lines += ["", "## Open Questions", ""]
        lines += [f"- {item}" for item in memo.get("open_questions", [])]
        if memo.get("action_items"):
            lines += ["", "## Next Actions", ""]
            lines += [f"- {item}" for item in memo.get("action_items", [])]
        lines += ["", f"> {result.get('privacy_note', '')}", ""]
        return "\n".join(lines)

    lines = ["# Executive audio coaching", "", result.get("executive_assessment", ""), "", "## Scores", ""]
    for name, score in result.get("scores", {}).items():
        lines += [f"### {name.replace('_', ' ').title()} — {score.get('score')}/100", "", score.get("assessment", ""), ""]
    lines += ["## Improvement moments", ""]
    for item in result.get("improvement_moments", []):
        lines += [f"### {item.get('timestamp')}", "", f"> {item.get('quote')}", "", item.get("observation", ""), "", f"**Try:** {item.get('better_response')}", ""]
    practice = result.get("next_practice", {})
    lines += ["## Next practice", "", practice.get("exercise", ""), ""]
    lines += [f"- {item}" for item in practice.get("success_criteria", [])]
    lines += ["", f"> {result.get('privacy_note', '')}", ""]
    return "\n".join(lines)
