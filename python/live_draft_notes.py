"""Draft notes at stop, from the Live transcript (docs/specs/live-transcript.md,
decision (b)): seconds after Stop, before processing has a full transcript.

Uses the configured Text model of the Processing profile (so lockdown and
provider rules are the Text model's) with a small budget: the transcript is
capped at MAX_CHARS (start and end kept), the reply at MAX_TOKENS. Written
beside the Live transcript as draft notes, shown marked "Draft" until the full
notes exist; never replaces them. Runs only when no processing run holds the
lock, so it never competes with the batch pipeline for the notes model.
"""
from __future__ import annotations

from typing import Any

import live_transcript

MAX_CHARS = 12000
MAX_TOKENS = 600
MIN_WORDS = 20

SYSTEM = ("You write short draft meeting notes from live captions. The captions are a rough draft: "
          "words can be wrong and the same speaker may appear under several labels. Never invent facts.")
PROMPT = """Live captions of a meeting ("You" is the person taking notes):

{transcript}

Write Markdown with three short sections: "## Summary" (2-3 sentences), "## Decisions" and "## Action items" (bullets; "- None noted." when there are none). Keep it under 200 words."""


def _capped(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    half = MAX_CHARS // 2
    return text[:half] + "\n[…]\n" + text[-half:]


def generate(recording_id: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """{ok, reason?, chars?}. Never raises for an expected refusal: no Live
    transcript, too short, processing busy, lockdown or a model failure."""
    import processing
    path = live_transcript.path_for(recording_id)
    if path is None:
        return {"ok": False, "reason": "no_live_transcript"}
    lines = [line for line in live_transcript.read_all_path(path) if str(line.get("text", "")).strip()]
    words = sum(len(str(line["text"]).split()) for line in lines)
    if words < MIN_WORDS:
        return {"ok": False, "reason": "too_short"}
    try:
        profile = profile or processing.resolve()
    except Exception:
        return {"ok": False, "reason": "profile"}
    text = _capped(live_transcript.as_text(lines))
    try:
        with processing.scope(profile, wait=False):
            from pipeline.text_model import text_model
            notes = text_model(profile).complete(PROMPT.format(transcript=text), system=SYSTEM,
                                                 max_tokens=MAX_TOKENS, trace="notes.draft_live").strip()
    except processing.ProcessingBusyError:
        return {"ok": False, "reason": "busy"}
    except Exception as exc:  # lockdown, provider down, model missing: no draft, nothing else changes
        print(f"[Live] draft notes not made: {type(exc).__name__}", flush=True)
        return {"ok": False, "reason": "model_failed"}
    if not notes:
        return {"ok": False, "reason": "empty"}
    target = (path.parent / live_transcript.DRAFT_NAME if path.name == live_transcript.FILE_NAME
              else live_transcript.draft_inbox_path(path.name[: -len(live_transcript.INBOX_SUFFIX)]))
    target.write_text(notes + "\n", encoding="utf-8")
    return {"ok": True, "chars": len(notes)}
