"""End-to-end orchestration of the local meeting pipeline."""
from __future__ import annotations

import json
import os
import re
import resource
import shutil
import time
from pathlib import Path
from typing import Any

import ai_trace
import db
import paths
from .common import _parse_ts, _write_progress, format_ts
from .config import LOCAL_LLM_MODEL_DEFAULT, MLX_WHISPER_MODEL
from .llm import _last_llm_stats
from .notes import _markdown_bullets, generate_enhanced_notes
from .speakers import _guess_remote_speakers, _load_continuation_segments, guess_speaker_from_tracks, load_accessibility_timeline, load_ax_participants, match_speaker_from_timeline, resolve_other_participant_name
from .transcribe import transcribe_with_silence_removal
from .context import build_context
from .vocabulary import learn_from_transcript


def log_resource_usage(recording_id: str, stage_timings: dict[str, float], audio_duration: float, speech_duration: float, llm_stats: dict[str, Any] | None = None) -> None:
    """Append a JSONL entry with wall-clock, CPU, and peak-memory usage for a
    local processing run. GPU/power draw aren't available from plain Python on
    macOS without root (that needs `powermetrics`, which requires sudo) — this
    logs what's measurable from inside the process itself."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    transcription_seconds = stage_timings.get("transcription")
    # RTF (real-time factor): processing time / audio duration. Below 1 means
    # transcription ran faster than real-time playback of the recording.
    transcription_rtf = (
        round(transcription_seconds / audio_duration, 3) if transcription_seconds and audio_duration else None
    )
    entry = {
        "recording_id": recording_id,
        "logged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "audio_duration_seconds": round(audio_duration, 1),
        "speech_duration_seconds": round(speech_duration, 1),
        "silence_removed_seconds": round(max(0.0, audio_duration - speech_duration), 1),
        "stage_seconds": {k: round(v, 1) for k, v in stage_timings.items()},
        "transcription_rtf": transcription_rtf,
        "llm": llm_stats or None,
        "cpu_user_seconds": round(usage.ru_utime, 1),
        "cpu_sys_seconds": round(usage.ru_stime, 1),
        "peak_memory_mb": round(usage.ru_maxrss / (1024 * 1024), 1),  # macOS reports ru_maxrss in bytes
    }
    log_path = paths.LOGS_DIR / "local_pipeline_resource_usage.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[Local Pipeline] Resource usage: {entry}", flush=True)


def load_slides_ocr(folder: Path) -> list[dict[str, Any]]:
    """Load slides/screenshots and their OCR text captured during meeting."""
    path = folder / "slides_ocr.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


_VERSIONED_OUTPUTS = (
    "transcript_diarized.md",
    "enhanced_notes.md",
    "diarization.json",
    "gemini_diarization.json",
    "call_summary.json",
    "audio_transcribed.wav",
    "transcription_context.json",
)


def _archive_previous_outputs(folder: Path) -> None:
    """Copy any existing transcript/notes outputs into versions/<timestamp>/
    before a reprocess overwrites them, so a retranscribe or re-enhance
    is never a silent, unrecoverable loss of the prior pass."""
    existing = [folder / name for name in _VERSIONED_OUTPUTS if (folder / name).exists()]
    if not existing:
        return
    stamp = time.strftime("%Y%m%dT%H%M%S")
    version_dir = folder / "versions" / stamp
    version_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, version_dir / path.name)
    print(f"[Local Pipeline] Archived previous outputs for {folder.name} to versions/{stamp}", flush=True)


def process_recording_local(folder: Path) -> dict[str, Any]:
    """Complete end-to-end local processing: MLX Whisper + AX Speakers + OCR Slides + Qwen3-4B."""
    audio_file = next((p for p in folder.iterdir() if p.is_file() and p.name.startswith("audio.")), None)
    if not audio_file:
        raise FileNotFoundError(f"No audio file found in {folder}")

    _archive_previous_outputs(folder)
    _write_progress(folder, "starting", "Initializing local pipeline...", percent=5)
    try:
        with ai_trace.run("local_meeting_pipeline", recording_id=folder.name, audio_file=audio_file.name):
            result = _process_recording_local_inner(folder, audio_file)
        (folder / ".pipeline_progress.json").unlink(missing_ok=True)
        return result
    except Exception as exc:
        _write_progress(folder, "error", str(exc), percent=0)
        raise


def _process_recording_local_inner(folder: Path, audio_file: Path) -> dict[str, Any]:
    metadata = db.get_recording_data(folder.name, "metadata") or {}
    title = metadata.get("recording_name") or folder.name

    stage_timings: dict[str, float] = {}

    # 1. Transcribe via local MLX Whisper, skipping detected dead air, using a
    #    prompt built from known people + terms matched to this meeting's title
    #    + terms learned from past transcripts (see build_vocabulary_prompt).
    # Discovers all audio parts: audio.mov, audio_part2.mov, audio_part3.mov...
    part_files = [audio_file]
    part_idx = 2
    while (folder / f"audio_part{part_idx}.mov").is_file():
        part_files.append(folder / f"audio_part{part_idx}.mov")
        part_idx += 1

    # Per-chunk Whisper prompts from everything known about this meeting
    # (attendees, title, notes, nearby screenshot text, past meetings,
    # vocabulary) — see pipeline/context.py. Saved to
    # transcription_context.json for debugging and training.
    context = build_context(folder, title)
    prompt = context.prompt()
    raw_segments = []
    total_audio_duration = 0.0
    total_speech_duration = 0.0
    current_time_offset = 0.0
    t0 = time.time()

    for idx, pfile in enumerate(part_files):
        p_label = f" (Part {idx + 1}/{len(part_files)})" if len(part_files) > 1 else ""
        _write_progress(folder, "transcribing", f"Transcribing audio{p_label}...", percent=15 + int(idx * 25 / len(part_files)))
        def prompt_for(start: float, end: float, offset: float = current_time_offset) -> str:
            chunk_prompt = context.prompt(start + offset, end + offset)
            context.record(start + offset, end + offset, chunk_prompt)
            return chunk_prompt

        p_segs, p_dur, p_speech = transcribe_with_silence_removal(pfile, prompt, folder=(folder if idx == 0 else None),
                                                                  prompt_for=prompt_for)
        for s in p_segs:
            raw_segments.append({
                **s,
                "start": float(s.get("start", 0.0)) + current_time_offset,
                "end": float(s.get("end", 0.0)) + current_time_offset,
            })
        current_time_offset += p_dur
        total_audio_duration += p_dur
        total_speech_duration += p_speech

    audio_duration = total_audio_duration
    speech_duration = total_speech_duration
    context.save(folder)
    stage_timings["transcription"] = time.time() - t0
    raw_segments.sort(key=lambda s: s["start"])
    _write_progress(folder, "aligning_speakers", "Aligning speakers and audio tracks...", percent=45)

    # 2. Align speakers from Accessibility timeline
    ax_timeline = load_accessibility_timeline(folder)
    ax_participants = load_ax_participants(folder / "participants.json")
    other_participant_name = resolve_other_participant_name(ax_participants)
    assigned_speakers = set()
    aligned_segments = []

    for seg in raw_segments:
        start_sec = float(seg.get("start", 0.0))
        end_sec = float(seg.get("end", 0.0))
        text = seg.get("text", "").strip()
        if not text or text in {"!", ".", "?", "...", ",", "-", "!!", "!!!"} or re.fullmatch(r"[!?. ,\-_]+", text):
            continue

        # Real name from Accessibility — Zoom appends ", active speaker" to
        # a video tile's AXDescription while that person is talking (needs
        # AXEnhancedUserInterface set on the app; verified live in
        # SpeakerWatcher.swift). Falls back to comparing the mic vs.
        # system-audio tracks (You / Participant — or the other person's
        # real name, from the Accessibility-derived roster, when there's
        # exactly one of them) for whatever moments AX doesn't catch, and
        # only then to a single speaker rather than guessing (a round-
        # robin-by-segment fallback used to mislabel a single voice as
        # multiple people any time Whisper split on a pause).
        track_guess = guess_speaker_from_tracks(audio_file, start_sec, end_sec)
        if track_guess == "Participant" and other_participant_name:
            track_guess = other_participant_name
        self_default = db.get_setting("pending_self_name") or "You"
        spk_name = match_speaker_from_timeline(start_sec, end_sec, ax_timeline) or track_guess or self_default

        assigned_speakers.add(spk_name)
        aligned_segments.append({
            "speaker_id": spk_name,
            "speaker_name": spk_name,
            "start": format_ts(start_sec),
            "end": format_ts(end_sec),
            "text": text,
            "language": "en",
            "emotion": "neutral",
        })

    # 2a. Name the remote turns the audio couldn't attribute (several other
    # people on the call): conversational rules first, then the local LLM.
    _guess_remote_speakers(folder, aligned_segments, ax_participants, title)
    assigned_speakers = {s["speaker_name"] for s in aligned_segments}

    # 2b. If this recording is linked as a continuation of an earlier one,
    # shift this recording's own segments onto the end of that meeting's
    # timeline and prepend its segments — transcript-only, per the "keep
    # recordings separate, just merge transcripts" design: audio files,
    # metadata.duration_seconds, and everything else stay per-recording.
    parent_segments, time_offset = _load_continuation_segments(folder)
    if parent_segments:
        for seg in aligned_segments:
            seg["start"] = format_ts(_parse_ts(seg["start"]) + time_offset)
            seg["end"] = format_ts(_parse_ts(seg["end"]) + time_offset)
        aligned_segments = parent_segments + aligned_segments
        assigned_speakers = {s.get("speaker_name") for s in aligned_segments if s.get("speaker_name")}
        print(f"[Local Pipeline] Continuation of {folder.name!r}'s parent recording: merged {len(parent_segments)} prior segment(s), offset +{format_ts(time_offset)}", flush=True)

    # 3. Load slide OCR data
    slides_data = load_slides_ocr(folder)

    # 4. Generate enhanced notes: many narrow local-LLM calls, not one big
    # structured-JSON ask — see generate_enhanced_notes() for why.
    full_transcript = "\n".join(f"[{s['start']} - {s['end']}] {s['speaker_name']}: {s['text']}" for s in aligned_segments)
    t0 = time.time()
    notes = generate_enhanced_notes(full_transcript, slides_data, aligned_segments, folder=folder)
    stage_timings["summarization"] = time.time() - t0
    _write_progress(folder, "persisting", "Saving notes & updating Cora database...", percent=98)

    # Grow the vocabulary store from this transcript so future recordings
    # (especially ones with a similar title/topic) get a better prompt —
    # plus the Key Entities this pass already extracted specifically, which
    # are higher-signal than the generic capitalized-word heuristic alone.
    learn_from_transcript(full_transcript)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for term in notes["keywords"]:
        db.upsert_vocabulary_term(term, "enhanced_notes", now_iso)

    # 5. Build Cora-compatible diarization and summary objects
    speaker_profiles = [
        {"speaker_id": s, "name": s, "description": f"Participant ({s})"}
        for s in sorted(assigned_speakers)
    ]

    diarization_payload = {
        "summary": notes["overview"],
        "model": "local-whisper-hinglish-mlx",
        "analyzed_at": now_iso,
        "audio_file": audio_file.name,
        "privacy_note": (
            "Processed locally on Apple Silicon (MLX). Summary metadata was sent to your Langfuse project (tracing opt-in)."
            if __import__("tracing").tracing_opted_in()
            else "100% processed locally on Apple Silicon (MLX). Zero audio or text left this device."
        ),
        "speakers": speaker_profiles,
        "segments": aligned_segments,
        "slides_indexed": len(slides_data),
    }

    # call_summary.json stays around for anything else already reading it
    # (e.g. the keywords -> key-phrases flow) — populated from the same
    # Markdown bullets, just parsed into flat lists rather than the old
    # nested {action, owner, due_date} shape, since nothing downstream
    # depended on that structure surviving. enhanced_notes.md (below) is
    # the actual display source now, not this file.
    call_summary_payload = {
        "title": notes.get("title", ""),
        "overview": notes["overview"],
        "decisions": _markdown_bullets(notes["decisions_md"]),
        "action_items": _markdown_bullets(notes["action_items_md"]),
        "unresolved_questions": _markdown_bullets(notes["open_questions_md"]),
        "keywords": notes["keywords"],
        "model": db.get_setting("liquid_model", LOCAL_LLM_MODEL_DEFAULT),
        "generated_at": now_iso,
        "schema_version": "2.0",
        "source_recording": audio_file.name,
    }

    if notes.get("title") and not metadata.get("recording_name"):
        metadata["recording_name"] = notes["title"]
        metadata["recording_name_source"] = "ai"
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        db.update_recording_data(folder.name, "metadata", metadata)

    enhanced_notes_md = "\n\n".join([
        "## Overview", notes["overview"],
        "## Action Items", notes["action_items_md"],
        "## Key Discussion & Decisions", notes["decisions_md"],
        "## Timeline", notes["timeline_md"],
        "## Open Questions", notes["open_questions_md"],
        "## Key Entities", notes["key_entities_md"],
    ])

    # Save to disk
    (folder / "diarization.json").write_text(json.dumps(diarization_payload, indent=2, ensure_ascii=False) + "\n")
    (folder / "gemini_diarization.json").write_text(json.dumps(diarization_payload, indent=2, ensure_ascii=False) + "\n")
    (folder / "call_summary.json").write_text(json.dumps(call_summary_payload, indent=2, ensure_ascii=False) + "\n")
    (folder / "enhanced_notes.md").write_text(enhanced_notes_md + "\n")

    # Render transcript markdown
    t_lines = ["# Meeting Transcript (Local MLX + Accessibility Diarization)", "", notes["overview"], ""]
    if not aligned_segments:
        t_lines.append("_No speech was detected in this recording._")
    else:
        for s in aligned_segments:
            t_lines.append(f"**{s['start']}–{s['end']} · {s['speaker_name']}**")
            t_lines.append("")
            t_lines.append(s["text"])
            t_lines.append("")
    (folder / "transcript_diarized.md").write_text("\n".join(t_lines), encoding="utf-8")

    # Update Cora database
    db.init_db()
    db.update_recording_data(folder.name, "diarization", diarization_payload)
    db.update_recording_data(folder.name, "call_summary", call_summary_payload)

    log_resource_usage(folder.name, stage_timings, audio_duration, speech_duration, llm_stats=_last_llm_stats or None)

    try:
        import tracing
        tracing.trace_pipeline_run(
            recording_id=folder.name,
            pipeline_type="local_meeting_pipeline",
            model=Path(MLX_WHISPER_MODEL).name if os.path.isabs(MLX_WHISPER_MODEL) else MLX_WHISPER_MODEL,
            input_summary={
                "audio_file": audio_file.name,
                "audio_duration_seconds": round(audio_duration, 1),
                "speech_duration_seconds": round(speech_duration, 1),
                "participants": list(assigned_speakers),
                "slides_count": len(slides_data),
            },
            output_summary={
                "overview": notes["overview"],
                "decisions": call_summary_payload["decisions"],
                "action_items": call_summary_payload["action_items"],
                "segments_count": len(aligned_segments),
            },
            latency_seconds=stage_timings.get("transcription", 0) + stage_timings.get("summarization", 0),
            metadata={"llm_stats": _last_llm_stats or None, "source_meeting": title},
        )
    except Exception as exc:
        print(f"[Local Pipeline] Langfuse tracing failed for {folder.name}: {exc}", flush=True)

    # Audio retention is an explicit opt-out (default: keep it) set during
    # onboarding. Only delete here, at the very end, after every artifact that
    # reads the audio file (transcription, delivery metrics if coaching ran)
    # has already been generated and persisted. Note this is a one-way trade:
    # deleting the source audio also permanently removes playback/seek for
    # this recording in the UI, not just the processing dependency.
    if not db.get_setting("retain_audio", True):
        audio_file.unlink(missing_ok=True)
        print(f"[Local Pipeline] Deleted source audio for {folder.name} (retain_audio is off)", flush=True)

    # If this recording is a continuation of an earlier meeting, merge the combined
    # artifacts directly into the parent meeting folder and database record, then clean up
    # the redundant child entry so the dashboard stays clean with one unified meeting.
    parent_id = (metadata or {}).get("continues_recording_id")
    if parent_id and (folder.parent / parent_id).is_dir():
        parent_folder = folder.parent / parent_id
        _archive_previous_outputs(parent_folder)
        (parent_folder / "diarization.json").write_text(json.dumps(diarization_payload, indent=2, ensure_ascii=False) + "\n")
        (parent_folder / "gemini_diarization.json").write_text(json.dumps(diarization_payload, indent=2, ensure_ascii=False) + "\n")
        (parent_folder / "call_summary.json").write_text(json.dumps(call_summary_payload, indent=2, ensure_ascii=False) + "\n")
        (parent_folder / "enhanced_notes.md").write_text(enhanced_notes_md + "\n")
        (parent_folder / "transcript_diarized.md").write_text("\n".join(t_lines), encoding="utf-8")

        part_idx = len(list(parent_folder.glob("audio_part*.mov"))) + 2
        shutil.copy2(audio_file, parent_folder / f"audio_part{part_idx}.mov")

        child_screenshots = folder / "screenshots"
        parent_screenshots = parent_folder / "screenshots"
        if child_screenshots.is_dir():
            parent_screenshots.mkdir(exist_ok=True)
            for s in child_screenshots.glob("*"):
                shutil.copy2(s, parent_screenshots / s.name)

        parent_meta = db.get_recording_data(parent_folder.name, "metadata") or {}
        parent_dur = float(parent_meta.get("duration_seconds", 0.0)) + float(audio_duration)
        parent_meta["duration_seconds"] = round(parent_dur, 1)
        (parent_folder / "metadata.json").write_text(json.dumps(parent_meta, indent=2) + "\n")

        db.update_recording_data(parent_folder.name, "diarization", diarization_payload)
        db.update_recording_data(parent_folder.name, "call_summary", call_summary_payload)
        db.update_recording_data(parent_folder.name, "metadata", parent_meta)

        # Retag live transcript and timeline entries to the parent meeting
        live_rec_id = metadata.get("live_recording_id", "")
        with db.get_db() as conn:
            conn.execute(
                "UPDATE live_transcript_entries SET start_seconds = start_seconds + ?, recording_id = ? WHERE recording_id IN (?, ?)",
                (float(time_offset), parent_folder.name, folder.name, live_rec_id)
            )
            conn.commit()

        db.delete_recording(folder.name)
        shutil.rmtree(folder, ignore_errors=True)
        print(f"[Local Pipeline] Continuation merged directly into parent {parent_folder.name} and child removed.", flush=True)

    print(f"[Local Pipeline] All artifacts saved for {folder.name}", flush=True)
    return {
        "diarization": diarization_payload,
        "call_summary": call_summary_payload,
        "speaker_profiles": speaker_profiles,
    }


def main() -> None:
    import sys
    paths.ensure_data_dir()  # owner-only umask for everything this run writes
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.runner <recording_folder_or_id>")
        sys.exit(1)

    target_id = sys.argv[1].rstrip("/")
    target_folder = Path(target_id) if Path(target_id).is_dir() else (paths.RECORDINGS_DIR / target_id)
    res = process_recording_local(target_folder)
    print("\n--- Summary ---")
    print(json.dumps(res["call_summary"], indent=2))


if __name__ == "__main__":
    main()
