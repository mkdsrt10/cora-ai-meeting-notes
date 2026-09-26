#!/usr/bin/env python3
"""Incrementally archive, transcribe, and summarize Apple Voice Memos.

Scans Apple's Voice Memos recording directory plus a user-controlled inbox.
Each memo becomes a self-contained folder containing the original audio,
transcript, summary, and metadata. Processing is local.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import db
import paths

ROOT = paths.DATA_DIR
INBOX = paths.INBOX_DIR
OUTPUT = paths.RECORDINGS_DIR
STATE_PATH = paths.STATE_PATH
LOCK_PATH = paths.LOCK_PATH
CONFIG_PATH = paths.CONFIG_PATH
AUDIO_SUFFIXES = {".m4a", ".mp3", ".wav", ".aiff", ".aif", ".mp4", ".caf", ".mov"}


class SourceNotReady(RuntimeError):
    """The source changed while being archived and should be retried later."""


DEFAULT_CONFIG = {
    "voice_memos_source": str(INBOX),
    "whisper_model": "mlx-community/whisper-small-mlx",
    "language": None,
    "minimum_age_seconds": 30,
    "process_existing_on_first_run": False,
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from",
    "had", "has", "have", "he", "her", "his", "i", "if", "in", "is", "it", "its",
    "me", "my", "not", "of", "on", "or", "our", "she", "so", "that", "the", "their",
    "them", "there", "they", "this", "to", "up", "us", "was", "we", "were", "what",
    "when", "which", "who", "will", "with", "would", "you", "your", "um", "uh", "like",
}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def atomic_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def ensure_layout() -> dict:
    paths.ensure_data_dir()
    config = load_json(CONFIG_PATH, DEFAULT_CONFIG.copy())
    merged = DEFAULT_CONFIG | config
    if not CONFIG_PATH.exists():
        atomic_json(CONFIG_PATH, merged)
    return merged


def file_key(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()


def is_internal_voice_memos_path(path: Path) -> bool:
    """True for Apple's editable composition tree, whose audio files are incomplete chunks."""
    return any(part.lower().endswith(".composition") for part in path.parts)


def probe_audio(path: Path) -> float:
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        completed = subprocess.run(
            [
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path)
            ],
            capture_output=True,
            text=True,
            check=True
        )
        duration = float(json.loads(completed.stdout)["format"]["duration"])
        if duration <= 0:
            raise ValueError(f"Invalid duration {duration}")
        return duration
    except FileNotFoundError:
        raise FileNotFoundError("ffprobe not found. Please install ffmpeg.")
    except Exception as exc:
        raise ValueError(f"Failed to probe audio: {exc}")


def _track_levels(path: Path, track_index: int) -> tuple[float, float]:
    """(mean_db, max_db) for one audio track via ffmpeg's volumedetect.
    (-100, -100) — effectively silent/undetectable — on any failure, so
    callers never mistake "couldn't measure" for "actually loud"."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    try:
        result = subprocess.run(
            [ffmpeg, "-i", str(path), "-map", f"0:a:{track_index}", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        mean = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
        peak = re.search(r"max_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
        return (float(mean.group(1)) if mean else -100.0, float(peak.group(1)) if peak else -100.0)
    except Exception:
        return (-100.0, -100.0)


def clean_track_audio(src: Path, dst: Path) -> bool:
    """Denoise both tracks and bring them to comparable playback loudness.

    Always runs ffmpeg's `afftdn` (FFT noise reduction, adaptive noise
    tracking) on both the mic and system-audio tracks — the mic in
    particular picks up a constant low-level room/electrical hum for the
    entire recording, even during silence, since dual-capture applies no
    noise suppression at all.

    On top of that: dual-capture's mic track (AVCaptureSession, no AGC)
    typically ends up several dB quieter than the system-audio track (which
    already passed through the meeting app's own output leveling) —
    audible on playback as "my voice is quiet, theirs is loud." Boosts
    whichever track measures quieter across the whole recording by the
    measured gap, capped so its peak stays under -1 dBFS (no clipping) and
    the boost itself never exceeds +15dB (never amplify a near-silent/dead
    track into audible noise). Returns False — leaving dst untouched — on
    any failure or if either track can't be measured at all, so callers
    fall back to a plain copy.
    """
    HEADROOM_DB = 1.0
    MAX_BOOST_DB = 15.0
    mic_mean, mic_peak = _track_levels(src, 0)
    sys_mean, sys_peak = _track_levels(src, 1)
    if mic_mean <= -90 or sys_mean <= -90:
        return False

    gap = sys_mean - mic_mean
    mic_gain = min(gap, MAX_BOOST_DB, max(0.0, -HEADROOM_DB - mic_peak)) if gap > 0 else 0.0
    sys_gain = min(-gap, MAX_BOOST_DB, max(0.0, -HEADROOM_DB - sys_peak)) if gap < 0 else 0.0

    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    denoise = "afftdn=nr=20:nf=-45:tn=1"
    # The archived file MUST keep mic and system audio as two separate
    # tracks: speaker attribution ("You" vs. the other participants) is
    # decided by comparing their loudness per segment, and the transcription
    # mix (local_meeting_pipeline.ensure_mixed_audio) needs both. Mixing
    # them here once silently turned every speaker into "You". The single-
    # stream version browsers need is a separate file — see
    # build_playback_mix().
    filter_complex = (
        f"[0:a:0]highpass=f=120,{denoise},volume={mic_gain:.1f}dB[a0];"
        f"[0:a:1]{denoise},volume={sys_gain:.1f}dB[a1]"
    )
    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(src), "-filter_complex", filter_complex,
                "-map", "[a0]", "-map", "[a1]", "-c:a", "aac", "-b:a", "128k", str(dst),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        return False


PLAYBACK_NAME = "playback.m4a"


def audio_stream_count(path: Path) -> int:
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        return len(json.loads(probe.stdout).get("streams", []))
    except Exception:
        return 0


def build_playback_mix(src: Path, dst: Path) -> bool:
    """One listenable stream for the in-app player, built from the two-track
    archive. Browsers play only the first audio track of a multi-track file
    (i.e. just your mic), so playback needs its own mix. Echo control: while
    the other side is talking, the mic is ducked ~20dB so their voice
    leaking from your speakers into the mic doesn't double up."""
    if audio_stream_count(src) < 2:
        return False
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    # Both tracks are padded with silence and the output cut to the full
    # recording length: sidechaincompress ends when its sidechain does, so a
    # system track that stopped early (capture hiccup) would otherwise
    # truncate the whole mix to the shorter track.
    filter_complex = (
        "[0:a:0]apad[mic];[0:a:1]apad[sys_sc];[0:a:1]apad[sys_mix];"
        "[mic][sys_sc]sidechaincompress=threshold=0.001:ratio=20:attack=1:release=80[ducked_mic];"
        "[ducked_mic][sys_mix]amix=inputs=2:duration=longest:dropout_transition=0[a]"
    )
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", str(src), "-filter_complex", filter_complex, "-t", f"{probe_audio(src):.3f}",
             "-map", "[a]", "-c:a", "aac", "-b:a", "128k", str(dst)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return dst.exists() and dst.stat().st_size > 0
    except Exception:
        dst.unlink(missing_ok=True)
        return False


def load_voice_memo_titles(config: dict) -> dict:
    return {}


def recording_name(path: Path, config: dict) -> tuple[str, str]:
    titles = config.get("_voice_memo_titles")
    if titles is None:
        titles = load_voice_memo_titles(config) if config.get("voice_memos_source") else {}
    if path.name in titles:
        return titles[path.name], "apple_voice_memos_db"
    # No real title available yet — leave it empty so the dashboard falls
    # back to a call-summary-derived title instead of the raw filename/id.
    return "", "none"


def sync_recording_names(state: dict, titles: dict[str, str]) -> int:
    """Refresh metadata when the user renames a memo without changing its audio."""
    changed = 0
    for entry in state.get("processed", {}).values():
        source = Path(entry.get("source", ""))
        output = Path(entry["output"]) if entry.get("output") else None
        title = titles.get(source.name)
        metadata_path = output / "metadata.json" if output else None
        if not title or not metadata_path or not metadata_path.is_file():
            continue
        metadata = load_json(metadata_path, {})
        if metadata.get("recording_name") == title:
            continue
        metadata["recording_name"] = title
        metadata["recording_name_source"] = "apple_voice_memos_db"
        atomic_json(metadata_path, metadata)
        db.update_recording_data(output.name, "metadata", metadata)
        
        changed += 1
    return changed


def discover(config: dict) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    warnings: list[str] = []
    for source in (Path(config["voice_memos_source"]).expanduser(), INBOX):
        if not source.exists():
            warnings.append(f"Source does not exist: {source}")
            continue
        if not os.access(source, os.R_OK):
            warnings.append(f"Permission denied: {source}")
            continue
        try:
            for path in source.rglob("*"):
                try:
                    if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES:
                        files.append(path)
                except PermissionError:
                    continue
        except PermissionError:
            warnings.append(f"Permission denied while scanning: {source}")
    return sorted(set(files), key=lambda p: p.stat().st_mtime), warnings


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return value[:80] or "voice-memo"


def transcribe(path: Path, config: dict) -> dict:
    import mlx_whisper

    import ai_trace

    kwargs = {"path_or_hf_repo": config["whisper_model"], "verbose": False}
    if config.get("language"):
        kwargs["language"] = config["language"]
    with ai_trace.span("transcription", "whisper.voice_memo", provider="mlx", model=config["whisper_model"],
                       input={"audio": ai_trace.file_fingerprint(path)}, params=kwargs) as trace:
        result = mlx_whisper.transcribe(str(path), **kwargs)
        segments = result.get("segments", [])
        trace.set_output({"language": result.get("language"), "text": result.get("text")},
                         audio_s=segments[-1]["end"] if segments else None, segments=len(segments))
    return result


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def summarize(text: str, max_points: int = 6) -> str:
    sents = sentences(text)
    if not sents:
        return "# Summary\n\n_No speech was detected._\n"

    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower())
    freq = collections.Counter(w for w in words if w not in STOPWORDS)
    if freq:
        peak = max(freq.values())
        weights = {word: count / peak for word, count in freq.items()}
    else:
        weights = {}

    scored = []
    for index, sentence in enumerate(sents):
        tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", sentence.lower())
        content = [t for t in tokens if t not in STOPWORDS]
        score = sum(weights.get(t, 0) for t in content) / max(len(content), 1)
        if 5 <= len(tokens) <= 45:
            score *= 1.15
        scored.append((score, index, sentence))

    best = sorted(scored, reverse=True)[:max_points]
    chosen = sorted(best, key=lambda item: item[1])
    overview_parts = sorted(best[:2], key=lambda item: item[1])
    overview = " ".join(item[2] for item in overview_parts) if overview_parts else sents[0]
    action_re = re.compile(r"\b(need to|have to|should|must|todo|to-do|follow up|remember to|action items?|next steps?|deadline)\b", re.I)
    actions = [sentence for sentence in sents if action_re.search(sentence)][:8]

    lines = ["# Summary", "", "## Overview", "", overview, "", "## Key points", ""]
    lines.extend(f"- {sentence}" for _, _, sentence in chosen)
    lines.extend(["", "## Possible action items", ""])
    lines.extend(f"- {sentence}" for sentence in actions)
    if not actions:
        lines.append("- None detected.")
    lines.extend(["", "> Generated locally with an extractive summarizer; verify important details.", ""])
    return "\n".join(lines)


def process(path: Path, key: str, config: dict) -> Path:
    stat = path.stat()
    source_snapshot = (stat.st_size, stat.st_mtime_ns)
    if file_key(path) != key:
        raise SourceNotReady(f"Source changed before copy: {path}")
    recorded = dt.datetime.fromtimestamp(stat.st_mtime).astimezone()
    folder = OUTPUT / f"{recorded:%Y-%m-%d_%H-%M-%S}_{safe_name(path.stem)}_{key[:8]}"
    importing = OUTPUT / f".{folder.name}.importing-{os.getpid()}"
    if folder.exists():
        raise FileExistsError(f"Recording folder already exists: {folder}")
    if importing.exists():
        shutil.rmtree(importing)
    importing.mkdir(parents=True)
    temporary_audio = importing / ("audio.partial" + path.suffix.lower())
    final_audio = folder / ("audio" + path.suffix.lower())

    try:
        shutil.copy2(path, temporary_audio)
        after = path.stat()
        if (after.st_size, after.st_mtime_ns) != source_snapshot or temporary_audio.stat().st_size != stat.st_size:
            raise SourceNotReady(f"Source changed during copy: {path}")

        # Denoise and balance the mic vs. system-audio tracks once, here,
        # before anything downstream (playback, Whisper, the mic/system
        # loudness comparison used to guess "You" vs. "Participant") ever
        # sees this file.
        cleaned = importing / ("audio.cleaned" + path.suffix.lower())
        if clean_track_audio(temporary_audio, cleaned):
            temporary_audio.unlink(missing_ok=True)
            temporary_audio = cleaned

        duration = probe_audio(temporary_audio)
        archived = importing / final_audio.name
        temporary_audio.replace(archived)
        build_playback_mix(archived, importing / PLAYBACK_NAME)

        title, title_source = recording_name(path, config)
        # Check if a live pending row preserved anything set while the
        # meeting was still recording/processing — an archetype or meeting
        # tool chosen at start, and (importantly) any notes the user typed
        # or folder they assigned via the live notepad. The pending row is
        # deleted below once the real archived row exists, so anything not
        # carried forward here is lost.
        pending_rec = db.get_pending_recording(path.stem)
        pending_meta = (pending_rec or {}).get("metadata", {})
        pending_archetype = pending_meta.get("archetype")
        pending_meeting_tool = pending_meta.get("meeting_tool")
        pending_folder_id = pending_meta.get("folder_id")
        pending_continues_recording_id = pending_meta.get("continues_recording_id")
        pending_notes = (pending_rec or {}).get("notes") or ""

        # Analysis is intentionally deferred to Gemini's native audio pipeline.
        metadata = {
            # The id this recording was tracked under while still live
            # (main.js's `meeting_<timestamp>`, == path.stem here) — the
            # archived id below is different (date-prefixed, hash-suffixed).
            # A UI still polling the live id after archiving needs this to
            # find where the recording actually landed instead of 404ing
            # forever (see server.py's /api/recording live_recording_id
            # fallback).
            "live_recording_id": path.stem,
            "source_file": str(path),
            "archived_file": str(final_audio),
            "source_size_bytes": stat.st_size,
            "source_modified_at": recorded.isoformat(),
            "duration_seconds": duration,
            "recording_name": title,
            "recording_name_source": title_source,
            "processed_at": dt.datetime.now().astimezone().isoformat(),
            # Which model actually processes this isn't decided until
            # /api/gemini-diarize runs (local by default, cloud Gemini only
            # on explicit opt-in) — the real model name gets recorded
            # accurately in the diarization payload's own "model" field at
            # that point, so this is deliberately generic, not a guess.
            "analysis_status": "awaiting_diarization",
            "analysis_model": "pending",
            "pipeline_key": key,
        }
        if pending_archetype:
            metadata["archetype"] = pending_archetype
            atomic_json(importing / "archetype_classification.json", pending_archetype)
        if pending_meeting_tool:
            metadata["meeting_tool"] = pending_meeting_tool
        if pending_folder_id:
            metadata["folder_id"] = pending_folder_id
        if pending_continues_recording_id:
            metadata["continues_recording_id"] = pending_continues_recording_id

        # Companion Accessibility speaker timeline from speaker-watch
        speakers_source = path.parent / (path.stem + "_speakers.json")
        if speakers_source.exists():
            try:
                shutil.copy2(speakers_source, importing / "speakers_timeline.json")
                speakers_source.unlink(missing_ok=True)
            except Exception:
                pass

        # Companion participant roster (names only — Zoom exposes no
        # "who's speaking" text, but does expose this) from speaker-watch
        participants_source = path.parent / (path.stem + "_participants.json")
        if participants_source.exists():
            try:
                shutil.copy2(participants_source, importing / "participants.json")
                participants_source.unlink(missing_ok=True)
            except Exception:
                pass

        # Companion meeting screenshots from screenshot engine
        screenshots_source = path.parent / (path.stem + "_screenshots")
        if screenshots_source.is_dir():
            try:
                shutil.copytree(screenshots_source, importing / "screenshots", dirs_exist_ok=True)
                shutil.rmtree(screenshots_source, ignore_errors=True)
            except Exception:
                pass

        atomic_json(importing / "metadata.json", metadata)
        importing.replace(folder)
        db.create_recording(
            recording_id=folder.name,
            folder_path=str(folder.resolve()),
            title=title,
            recorded_at=metadata["source_modified_at"],
            duration_seconds=duration,
            size_bytes=stat.st_size,
            metadata=metadata
        )
        if pending_notes.strip():
            db.update_notes(folder.name, pending_notes)
        # Any live-transcribe speech turns and screenshot cards were written
        # against the pending row's id (path.stem) — re-point them at the
        # real archived id before that row is retired, or they'd be
        # orphaned under an id nothing references anymore.
        db.retag_live_transcript_entries(path.stem, folder.name)
        # Retire the live "recording"/"processing" placeholder row (created
        # the instant Start was clicked, before this folder existed) now
        # that the real archived row is in place.
        db.retire_pending_recording(path.stem)
    except Exception:
        shutil.rmtree(importing, ignore_errors=True)
        raise
    return folder


def run_once(dry_run: bool = False) -> int:
    config = ensure_layout()
    state = db.get_setting("state", {"processed": {}})
    state.setdefault("processed", {})
    files, warnings = discover(config)
    voice_memo_titles = load_voice_memo_titles(config)
    runtime_config = config | {"_voice_memo_titles": voice_memo_titles}
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    minimum_age = int(config.get("minimum_age_seconds", 30))
    now = time.time()

    # On the first successful scan of Apple's protected recording directory,
    # treat the existing library as a baseline. The daemon is intended to
    # process recordings created after installation, not silently import a
    # potentially large historical library. Inbox files are never baselined.
    source_root = Path(config["voice_memos_source"]).expanduser().resolve()
    if not state.get("voice_memos_baselined") and not config.get("process_existing_on_first_run", False):
        baselined = 0
        for path in files:
            try:
                path.resolve().relative_to(source_root)
                key = file_key(path)
            except (ValueError, FileNotFoundError, PermissionError):
                continue
            if key not in state["processed"]:
                state["processed"][key] = {
                    "source": str(path),
                    "status": "baseline_existing",
                    "processed_at": dt.datetime.now().astimezone().isoformat(),
                }
                baselined += 1
        state["voice_memos_baselined"] = True
        state["voice_memos_baselined_at"] = dt.datetime.now().astimezone().isoformat()
        db.set_setting("state", state)
        print(f"Baselined {baselined} existing Voice Memo(s); future recordings will be processed.")

    pending = []
    for path in files:
        try:
            if now - path.stat().st_mtime < minimum_age:
                continue
            key = file_key(path)
            if key not in state["processed"]:
                pending_rec = db.get_pending_recording(path.stem)
                if pending_rec and pending_rec.get("status") in {"recording", "paused"}:
                    continue
                pending.append((path, key))
        except (FileNotFoundError, PermissionError):
            continue

    print(f"Found {len(files)} audio file(s); {len(pending)} new and stable.")
    if dry_run:
        for path, _ in pending:
            print(path)
        return 0

    renamed = sync_recording_names(state, voice_memo_titles)
    if renamed:
        print(f"Updated {renamed} archived recording name(s).")

    failures = 0
    for path, key in pending:
        print(f"Processing: {path}", flush=True)
        try:
            folder = process(path, key, runtime_config)
            state["processed"][key] = {
                "source": str(path),
                "output": str(folder),
                "processed_at": dt.datetime.now().astimezone().isoformat(),
            }
            db.set_setting("state", state)
            print(f"Saved: {folder}", flush=True)
        except SourceNotReady as exc:
            print(f"Deferred until stable: {exc}", flush=True)
        except Exception as exc:
            failures += 1
            print(f"ERROR processing {path}: {exc}", file=sys.stderr, flush=True)
            # If the audio file is corrupted and unreadable (e.g. missing moov atom),
            # quarantine it so future runs don't get stuck in an endless error loop.
            if "Failed to probe audio" in str(exc) or "moov atom not found" in str(exc):
                corrupted_dest = path.parent / f".{path.name}.corrupted"
                try:
                    path.rename(corrupted_dest)
                    print(f"Quarantined corrupted file to {corrupted_dest}", file=sys.stderr, flush=True)
                    state["processed"][key] = {
                        "source": str(path),
                        "status": "corrupted",
                        "error": str(exc),
                        "processed_at": dt.datetime.now().astimezone().isoformat(),
                    }
                    db.set_setting("state", state)
                except Exception as rename_err:
                    print(f"Failed to quarantine {path}: {rename_err}", file=sys.stderr, flush=True)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Scan once (default behavior).")
    parser.add_argument("--dry-run", action="store_true", help="List new recordings without processing.")
    args = parser.parse_args()
    ensure_layout()
    with LOCK_PATH.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another pipeline run is active; exiting.")
            return 0
        return run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
