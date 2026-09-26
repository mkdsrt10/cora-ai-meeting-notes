"""Who said what: Accessibility timeline, mic/system tracks, roster, LLM naming."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import db
from participants import _BAD_PARTICIPANT_WORDS, clean_and_validate_participant  # noqa: F401
from .audio import track_mean_volume
from .common import _parse_ts, _write_progress


def _load_continuation_segments(folder: Path) -> tuple[list[dict[str, Any]], float]:
    """If this recording is linked as a continuation of an earlier one
    (metadata.continues_recording_id, set when it was started via the
    notepad's "Add to this recording" button), load that parent's already-
    diarized segments and the time offset to shift
    this recording's own segments by — so the transcript reads as one
    continuous timeline (parent ends at 10:00, this recording's 00:00 becomes
    10:00) even though the two recordings stay entirely separate audio files
    on disk. Returns ([], 0.0) if there's no parent or it can't be read —
    this recording's own segments are used unshifted, same as before."""
    parent_id = (db.get_recording_data(folder.name, "metadata") or {}).get("continues_recording_id")
    if not parent_id:
        return [], 0.0
    parent_diarization_path = folder.parent / parent_id / "diarization.json"
    if not parent_diarization_path.exists():
        parent_diarization_path = folder.parent / parent_id / "gemini_diarization.json"
    if not parent_diarization_path.exists():
        print(f"[Local Pipeline] continues_recording_id={parent_id} but that recording has no diarization yet — skipping merge.", flush=True)
        return [], 0.0
    try:
        parent_segments = json.loads(parent_diarization_path.read_text()).get("segments", [])
    except Exception as exc:
        print(f"[Local Pipeline] Failed to load parent segments for continuation: {exc}", flush=True)
        return [], 0.0
    offset = max((_parse_ts(s.get("end", "00:00")) for s in parent_segments), default=0.0)
    return parent_segments, offset


def load_accessibility_timeline(folder: Path) -> list[dict[str, Any]]:
    """Load real speaker turns captured via AXUIElement watcher during meeting."""
    path = folder / "speakers_timeline.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []








def load_ax_participants(path: Path) -> list[str]:
    """Zoom/Meet participant roster extracted from UI tiles, filtered of bots & jargon."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        cleaned = []
        seen = set()
        for p in data:
            valid = clean_and_validate_participant(p)
            if valid and valid.lower() not in seen:
                seen.add(valid.lower())
                cleaned.append(valid)
        return cleaned
    except Exception:
        return []


def resolve_other_participant_name(participants: list[str]) -> Optional[str]:
    """When the Accessibility-derived roster lists exactly one person besides
    you, that's who guess_speaker_from_tracks' generic "Participant" bucket
    actually is — swap in their real name. Deliberately gives up (returns
    None, never a guess) for 0 or 2+ others, since audio-level comparison
    alone can't say *which* of several other people is talking."""
    self_name = db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name")
    self_name = (self_name or "").strip().lower()
    self_tokens = set(self_name.split()) if self_name else set()

    def is_self(p: str) -> bool:
        p_low = p.strip().lower()
        if p_low == self_name:
            return True
        p_tokens = set(p_low.split())
        return bool(self_tokens and self_tokens.intersection(p_tokens))

    others = [p for p in participants if not is_self(p)]
    return others[0] if len(others) == 1 else None


def _guess_remote_speakers(folder: Path, segments: list[dict[str, Any]], roster: list[str], title: str, llm) -> None:
    import speaker_guess

    self_name = db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name")
    others = speaker_guess.other_participants(roster, self_name)
    if not any(s["speaker_id"] == speaker_guess.UNRESOLVED for s in segments) or not others:
        return
    _write_progress(folder, "identifying_speakers", "Working out who said what...", percent=48)
    def generate(prompt: str) -> str:
        return llm.generate(prompt, name="speaker_guess", prompt_template=speaker_guess.INSTRUCTION,
                            input_payload={"prompt": prompt, "roster": others})

    try:
        stats = speaker_guess.guess_speakers(segments, roster, self_name, title, generate=generate, model_id=llm.model_id)
        print(f"[Local Pipeline] Speaker naming: {stats}", flush=True)
    except Exception as exc:  # naming is an enhancement; never fail the pipeline over it
        print(f"[Local Pipeline] Speaker naming skipped: {exc}", flush=True)


def match_speaker_from_timeline(start_sec: float, end_sec: float, timeline: list[dict[str, Any]]) -> Optional[str]:
    """Find the active speaker from Accessibility timeline overlapping this interval."""
    best_speaker = None
    max_overlap = 0.0

    for item in timeline:
        t_start = item.get("start_sec", 0.0)
        t_end = item.get("end_sec", 0.0)
        name = item.get("speaker_name")
        if not name:
            continue

        overlap = max(0.0, min(end_sec, t_end) - max(start_sec, t_start))
        if overlap > max_overlap:
            max_overlap = overlap
            best_speaker = name

    # Require at least 25% overlap or 0.8s
    duration = end_sec - start_sec
    if max_overlap >= min(0.8, duration * 0.25):
        return best_speaker
    return None


def guess_speaker_from_tracks(audio_path: Path, start_sec: float, end_sec: float, margin_db: float = 0.5) -> Optional[str]:
    """Distinguish "you" from "someone else" using the recording's own
    separate mic (track 0) and system-audio (track 1) tracks.
    Returns "You" when mic is active/dominant, or "Participant" when
    system audio is dominant."""
    mic_db = track_mean_volume(audio_path, 0, start_sec, end_sec)
    sys_db = track_mean_volume(audio_path, 1, start_sec, end_sec)
    if mic_db <= -55 and sys_db <= -55:
        return None
    if sys_db > mic_db + margin_db:
        return "Participant"
    if mic_db >= sys_db - margin_db:
        return "You"
    return "You"
