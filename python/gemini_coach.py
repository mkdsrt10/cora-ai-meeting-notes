#!/usr/bin/env python3
"""Optional Gemini deep-coaching analysis. API credentials remain server-side."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import credentials

DEFAULT_MODEL = credentials.get_default_model()


def load_api_key() -> str | None:
    status = credentials.get_public_status()
    if status.get("is_configured"):
        return "configured"
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if os.environ.get(name):
            return os.environ[name]
    return None


def available() -> bool:
    return credentials.is_available()


def schema() -> dict[str, Any]:
    string_array = {"type": "ARRAY", "items": {"type": "STRING"}}
    return {
        "type": "OBJECT",
        "required": ["executive_assessment", "coherence", "storytelling", "influence", "listener_direction", "best_moments", "problems", "better_version", "next_practice"],
        "properties": {
            "executive_assessment": {"type": "STRING"},
            "coherence": {"type": "OBJECT", "required": ["score", "assessment", "topic_map"], "properties": {
                "score": {"type": "INTEGER"}, "assessment": {"type": "STRING"}, "topic_map": string_array}},
            "storytelling": {"type": "OBJECT", "required": ["score", "assessment", "missing_elements"], "properties": {
                "score": {"type": "INTEGER"}, "assessment": {"type": "STRING"}, "missing_elements": string_array}},
            "influence": {"type": "OBJECT", "required": ["score", "assessment", "negotiation_risks"], "properties": {
                "score": {"type": "INTEGER"}, "assessment": {"type": "STRING"}, "negotiation_risks": string_array}},
            "listener_direction": {"type": "OBJECT", "required": ["score", "assessment", "missing_instructions"], "properties": {
                "score": {"type": "INTEGER"}, "assessment": {"type": "STRING"}, "missing_instructions": string_array}},
            "best_moments": string_array,
            "problems": {"type": "ARRAY", "items": {"type": "OBJECT", "required": ["quote", "issue", "fix"], "properties": {
                "quote": {"type": "STRING"}, "issue": {"type": "STRING"}, "fix": {"type": "STRING"}}}},
            "better_version": {"type": "STRING"},
            "next_practice": {"type": "OBJECT", "required": ["exercise", "success_criteria"], "properties": {
                "exercise": {"type": "STRING"}, "success_criteria": string_array}},
            "negotiation_preparation": {"type": "OBJECT", "properties": {
                "objective": {"type": "STRING"}, "batna_gap": {"type": "STRING"}, "anchor_gap": {"type": "STRING"}, "questions_to_ask": string_array,
                "next_step": {"type": "STRING"}}},
        },
    }


def prompt(transcript: str, mode: str, local_metrics: dict[str, Any]) -> str:
    safe_metrics = {key: local_metrics.get(key) for key in ["words_per_minute", "fillers_per_minute", "idea_density_per_minute", "repetition_ratio", "average_sentence_words", "scores"]}
    return f"""You are a demanding but practical executive communication, storytelling, and negotiation coach.
Analyze the transcript as spoken communication, not as polished writing. The speaker wants to know whether the message makes sense, whether it rambles, and whether it directs the listener toward the intended outcome.

MODE: {mode}
LOCAL MEASUREMENTS: {json.dumps(safe_metrics)}

Rules:
- Ground every criticism in the supplied transcript; never invent listener reactions or facts.
- Distinguish a transcription error from a communication problem when uncertain.
- Scores are integers from 0 to 100 and should be demanding, calibrated, and actionable.
- Quote short exact passages when identifying problems.
- The better_version must preserve the speaker's meaning, remove repetition, lead with the point, and end with a clear action or takeaway.
- For negotiation, identify missing objective, BATNA, anchor, concessions, calibrated questions, and explicit next step. If not applicable, keep those fields concise.
- Do not assess accent as good or bad. Comment only on intelligibility signals available in text and local measurements.

TRANSCRIPT:
---
{transcript[:60000]}
---
Return only the requested JSON object."""


def analyze(folder: Path, mode: str | None = None, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    client = credentials.get_client()
    if not client:
        raise RuntimeError("AI service is not configured")
    transcript_path = folder / "transcript.txt"
    if not transcript_path.exists():
        raise FileNotFoundError("Transcript not found")
    transcript = transcript_path.read_text(errors="replace").strip()
    if not transcript:
        raise ValueError("Transcript is empty")
    metrics_path = folder / "speech_metrics.json"
    local_metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    selected_mode = mode or local_metrics.get("mode_label") or "Free thinking"
    
    from google.genai import types
    config = types.GenerateContentConfig(
        temperature=0.25,
        response_mime_type="application/json",
        response_schema=schema(),
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt(transcript, selected_mode, local_metrics),
            config=config,
        )
        result = json.loads(response.text)
    except Exception as exc:
        raise RuntimeError(f"Coaching analysis failed: {exc}") from exc

    result["model"] = model
    result["analyzed_at"] = dt.datetime.now().astimezone().isoformat()
    result["privacy_note"] = "Transcript text was sent to Google Gemini / Vertex AI; audio remained local."
    target = folder / "gemini_coaching.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(target)
    (folder / "gemini_coaching.md").write_text(render_markdown(result))
    return result


def render_markdown(result: dict[str, Any]) -> str:
    lines = ["# Gemini deep coaching", "", result["executive_assessment"], ""]
    for key, title in [("coherence", "Coherence"), ("storytelling", "Storytelling"), ("influence", "Influence and negotiation"), ("listener_direction", "Listener direction")]:
        section = result[key]
        lines += [f"## {title} — {section['score']}/100", "", section["assessment"], ""]
    lines += ["## Specific problems", ""]
    for item in result.get("problems", []):
        lines += [f"> {item['quote']}", "", f"**Issue:** {item['issue']}", "", f"**Fix:** {item['fix']}", ""]
    lines += ["## Better version", "", result["better_version"], "", "## Next practice", "", result["next_practice"]["exercise"], ""]
    lines += [f"- {item}" for item in result["next_practice"].get("success_criteria", [])]
    lines += ["", f"> {result['privacy_note']}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--mode")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    print(json.dumps(analyze(args.folder, args.mode, args.model), indent=2, ensure_ascii=False))
