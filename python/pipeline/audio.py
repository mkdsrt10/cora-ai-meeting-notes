"""ffmpeg helpers: probing, silence detection, clipping and mic/system mixing."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from .config import _config


def probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def find_speech_segments(
    audio_path: Path,
    noise_db: Optional[str] = None,
    min_gap: Optional[float] = None,
    pad: float = 0.3,
    min_speech: float = 0.5,
) -> list[tuple[float, float]]:
    noise_db = noise_db or str(_config().get("silence_threshold_db", "-50dB"))
    min_gap = min_gap if min_gap is not None else float(_config().get("silence_min_gap_seconds", 1.2))
    """Detect the non-silent stretches of a recording so Whisper only ever sees
    speech, never dead air. Timestamps stay anchored to the ORIGINAL file —
    unlike trimming the whole file up front, each stretch is transcribed
    separately and its segments are shifted back by that stretch's start time,
    so AX-speaker matching, screenshot correlation, and click-to-seek in the
    UI (all keyed to the original audio.mov's timeline) keep working.

    Falls back to "the whole file is one speech segment" on any ffmpeg error,
    so a detection hiccup degrades to the old behavior rather than losing audio.
    """
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    try:
        duration = probe_duration(audio_path)
        cmd = [
            ffmpeg, "-i", str(audio_path), "-af",
            f"silencedetect=noise={noise_db}:d={min_gap}",
            "-f", "null", "-",
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        stderr = result.stderr

        starts = [float(m) for m in re.findall(r"silence_start:\s*([\d.]+)", stderr)]
        ends = [float(m) for m in re.findall(r"silence_end:\s*([\d.]+)", stderr)]
        silences = list(zip(starts, ends[: len(starts)]))

        speech: list[tuple[float, float]] = []
        cursor = 0.0
        for s_start, s_end in silences:
            if s_start > cursor:
                speech.append((cursor, s_start))
            cursor = max(cursor, s_end)
        if cursor < duration:
            speech.append((cursor, duration))
        if not speech:
            speech = [(0.0, duration)]

        padded = [(max(0.0, s - pad), min(duration, e + pad)) for s, e in speech]
        merged: list[tuple[float, float]] = []
        for s, e in padded:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        kept = [(s, e) for s, e in merged if e - s >= min_speech]
        return kept or [(0.0, duration)]
    except Exception as exc:
        print(f"[Local MLX] Silence detection failed ({exc}); transcribing the whole file.", flush=True)
        try:
            return [(0.0, probe_duration(audio_path))]
        except Exception:
            return [(0.0, 0.0)]


def extract_clip(audio_path: Path, start: float, end: float) -> Path:
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    cmd = [
        ffmpeg, "-y", "-ss", str(start), "-i", str(audio_path), "-t", str(max(0.05, end - start)),
        "-ac", "1", "-ar", "16000", str(tmp_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return tmp_path


def track_mean_volume(audio_path: Path, track_index: int, start_sec: float, end_sec: float) -> float:
    """Mean volume in dB (more negative = quieter) of one audio track over a
    time range, via ffmpeg's volumedetect filter. -100 (effectively silent)
    if it can't be determined, so callers never mistake a detection failure
    for actual silence-vs-signal information."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    duration = max(0.05, end_sec - start_sec)
    try:
        result = subprocess.run(
            [
                ffmpeg, "-ss", str(start_sec), "-t", str(duration), "-i", str(audio_path),
                "-map", f"0:a:{track_index}", "-af", "volumedetect", "-f", "null", "-",
            ],
            capture_output=True, text=True,
        )
        match = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", result.stderr)
        return float(match.group(1)) if match else -100.0
    except Exception:
        return -100.0


def build_trimmed_audio(audio_path: Path, speech_segments: list[tuple[float, float]]) -> tuple[Path, list[tuple[float, float, float]]]:
    """Extract each speech stretch and concatenate them into one continuous
    16kHz mono WAV. Returns (trimmed_path, mapping), where mapping is a list
    of (trimmed_start, trimmed_end, original_start) triples — enough to shift
    any timestamp in the trimmed audio back to the original recording's
    timeline. Caller must delete trimmed_path when done.
    """
    clip_paths: list[Path] = []
    mapping: list[tuple[float, float, float]] = []
    cursor = 0.0
    for seg_start, seg_end in speech_segments:
        clip_paths.append(extract_clip(audio_path, seg_start, seg_end))
        clip_dur = seg_end - seg_start
        mapping.append((cursor, cursor + clip_dur, seg_start))
        cursor += clip_dur

    if len(clip_paths) == 1:
        # Nothing to concatenate — the one clip already covers the case, and
        # the caller owns (and will delete) whatever path this returns.
        return clip_paths[0], mapping

    list_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    for clip in clip_paths:
        list_file.write(f"file '{clip}'\n")
    list_file.close()

    trimmed = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    try:
        subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file.name, "-c", "copy", str(trimmed)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    finally:
        Path(list_file.name).unlink(missing_ok=True)
        for clip in clip_paths:
            clip.unlink(missing_ok=True)
    return trimmed, mapping


def _to_original_time(trimmed_t: float, mapping: list[tuple[float, float, float]]) -> float:
    for t_start, t_end, orig_start in mapping:
        if trimmed_t <= t_end:
            return orig_start + max(0.0, trimmed_t - t_start)
    # Past the last mapped stretch (rounding at the very end) — anchor to it.
    t_start, t_end, orig_start = mapping[-1]
    return orig_start + (trimmed_t - t_start)


def ensure_mixed_audio(audio_path: Path) -> Path:
    """dual-capture writes audio.mov with the mic and system-audio tracks as
    two SEPARATE audio streams (verified: `ffprobe` on a real recording
    shows stream #0:0 = mic, #0:1 = system, both stereo AAC). Every ffmpeg
    call in this transcription path (silencedetect below, and the clip
    extraction in build_trimmed_audio/extract_clip) uses a single simple
    `-af`/`-ac` filter with no explicit `-map` — verified against a real
    recording's ffmpeg stream-mapping output that this silently selects
    ONLY stream #0:0 and drops #0:1 entirely. Concretely: whenever the
    local mic was quiet while the other person was talking (audio on the
    system track only), Whisper was being handed near-silence, not their
    speech — a major, independently confirmed contributor to the
    repetition-loop hallucination bug (170 of 207 turns in one real
    recording were speaker-labeled "Participant" by the separate,
    correctly per-track volume-based guess_speaker_from_tracks(), yet
    their transcribed text could only ever have come from the mic track).

    Mixes both tracks into one balanced mono stream before ANY silence
    detection or clipping happens, so Whisper hears both sides of the
    conversation. Returns audio_path unchanged for a single-track file
    (voice memos, already-mixed sources) or on any ffprobe/ffmpeg failure —
    never worse than the previous (mic-only) behavior.
    """
    ffprobe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "stream=index", "-select_streams", "a", "-of", "json", str(audio_path)],
            capture_output=True, text=True, check=True,
        )
        stream_count = len(json.loads(probe.stdout).get("streams", []))
    except Exception as exc:
        print(f"[Local MLX] Failed to probe audio streams for mixing, using file as-is: {exc}", flush=True)
        return audio_path
    if stream_count < 2:
        return audio_path

    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    mixed_path = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    try:
        # Acoustic Echo Cancellation via Fast Sidechain Ducking:
        # When Stream 1 (Remote System Audio) is active (someone is speaking on Zoom/Meet/Teams),
        # automatically duck Stream 0 (Microphone) by ~24dB to cancel room echo from laptop speakers into mic.
        # When remote speaker pauses, Microphone immediately returns to full sensitivity for your speech.
        # Pad both tracks and cut to the recording's full length: the
        # sidechain filter stops when the system track does, so a system
        # track that ended early (capture hiccup) used to truncate the whole
        # transcription mix — Whisper only heard the first seconds.
        filter_complex = (
            "[0:a:0]highpass=f=120,afftdn=nr=20:nf=-45,apad[clean_mic];"
            "[0:a:1]afftdn=nr=15:nf=-50,apad,asplit=2[sys_sc][sys_mix];"
            "[clean_mic][sys_sc]sidechaincompress=threshold=0.001:ratio=20:attack=1:release=80[ducked_mic];"
            "[ducked_mic][sys_mix]amix=inputs=2:duration=longest:dropout_transition=0,volume=1.4[a]"
        )
        subprocess.run(
            [
                ffmpeg, "-y", "-i", str(audio_path),
                "-filter_complex", filter_complex, "-t", f"{probe_duration(audio_path):.3f}",
                "-map", "[a]", "-ac", "1", "-ar", "16000", str(mixed_path),
            ],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return mixed_path
    except Exception as exc:
        print(f"[Local MLX] Failed to mix mic + system audio tracks, using mic-only: {exc}", flush=True)
        mixed_path.unlink(missing_ok=True)
        return audio_path
