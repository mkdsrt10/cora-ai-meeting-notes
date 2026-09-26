#!/usr/bin/env python3
"""Compare a recording's current transcript with an archived version.

Reference-free checks, useful when changing prompts or models:

  * term coverage — how many of the meeting's known terms (attendees,
    screenshot/notes terms from transcription_context.json) appear, spelled
    exactly, in each transcript;
  * prompt leakage — segments that look copied from the prompt ("Attendees:",
    "Terms:", long runs of comma-separated names), a known Whisper failure
    mode when a prompt is fed into near-silence;
  * volume — words and segments;
  * script — share of Devanagari letters (target 0% for Romanized Hinglish).

    python tools/eval_asr.py <recording-id> [--against versions/<stamp>]

Prints counts only (no transcript text), so output is safe to share.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paths  # noqa: E402

DEVANAGARI = re.compile(r"[\u0900-\u097F]")
LETTERS = re.compile(r"[\u0900-\u097FA-Za-z]")
LEAK = re.compile(r"\b(?:Attendees|Terms|Meeting)\s*:|(?:\b[A-Z][\w-]+,\s*){5,}")


def load_segments(folder: Path) -> list[dict]:
    try:
        return json.loads((folder / "diarization.json").read_text()).get("segments", [])
    except (OSError, ValueError):
        return []


def known_terms(folder: Path) -> tuple[list[str], list[str]]:
    try:
        ctx = json.loads((folder / "transcription_context.json").read_text())
    except (OSError, ValueError):
        return [], []
    attendees = ctx.get("attendees", [])
    names = sorted({part for a in attendees for part in a.split() if len(part) >= 3})
    terms = sorted({t["term"] for t in ctx.get("top_terms", []) if set(t["sources"]) & {"ocr", "notes", "title"}}
                   | {t["term"] for t in ctx.get("screenshot_terms", [])})
    return names, terms


def score(segments: list[dict], names: list[str], terms: list[str]) -> dict:
    text = " ".join(s.get("text", "") for s in segments)
    words = re.findall(r"\w+", text)
    present = lambda items: sum(1 for t in items if re.search(rf"\b{re.escape(t)}\b", text))  # noqa: E731
    return {
        "segments": len(segments),
        "words": len(words),
        "attendee_names_heard": f"{present(names)}/{len(names)}",
        "context_terms_heard": f"{present(terms)}/{len(terms)}",
        "prompt_leak_segments": sum(1 for s in segments if LEAK.search(s.get("text", ""))),
        "devanagari_share": f"{100 * len(DEVANAGARI.findall(text)) / max(len(LETTERS.findall(text)), 1):.0f}%",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording_id")
    parser.add_argument("--against", help="archived version folder, relative to the recording (default: newest)")
    args = parser.parse_args()
    folder = paths.RECORDINGS_DIR / args.recording_id
    versions = sorted((folder / "versions").glob("*/diarization.json"))
    baseline = folder / args.against if args.against else (versions[-1].parent if versions else None)
    names, terms = known_terms(folder)
    print(f"known: {len(names)} attendee name parts, {len(terms)} context terms")
    print(f"current   {score(load_segments(folder), names, terms)}")
    if baseline:
        print(f"baseline  {score(load_segments(baseline), names, terms)}  ({baseline.relative_to(folder)})")


if __name__ == "__main__":
    main()
