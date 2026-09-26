#!/usr/bin/env python3
"""Backfill identity-safe objective delivery metrics for coached recordings."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = ROOT / "recordings"
COACH_DATA = ROOT / "coach_data.json"

sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))
from diarization import LATEST_AUDIO_MODEL  # noqa: E402
from plugins.coaching.engine import analyze_delivery  # noqa: E402


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    goals = load(COACH_DATA).get("goals", {})
    completed = 0
    failures = 0
    for folder in sorted(RECORDINGS.iterdir()):
        if not folder.is_dir():
            continue
        identity = load(folder / "self_speaker.json")
        coaching = load(folder / "gemini_coaching.json")
        speaker_id = identity.get("speaker_id")
        if not speaker_id or coaching.get("model") != LATEST_AUDIO_MODEL or coaching.get("target_speaker") != speaker_id:
            continue
        try:
            result = analyze_delivery(folder, speaker_id, goals)
            metrics = result["metrics"]
            print(
                f"{folder.name}: {metrics['pace']['value']} WPM · "
                f"{metrics['pitch_variety']['range_semitones']} st · "
                f"{metrics['volume_variety']['range_db']} dB · "
                f"{metrics['fillers']['per_minute']} fillers/min"
            )
            completed += 1
        except Exception as error:
            print(f"ERROR {folder.name}: {error}")
            failures += 1
    print(f"Backfilled {completed} recording(s); {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
