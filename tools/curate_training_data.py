#!/usr/bin/env python3
"""Curate and Prepare High-Fidelity Training Data for Whisper & LLM Fine-Tuning.

Uses Gemini 3.8 Flash on Vertex AI (global endpoint) to:
1. Generate gold-standard, spelling-consistent Romanized Hinglish transcripts from raw audio.
2. Log full traces and dataset items to Langfuse (https://us.cloud.langfuse.com).
3. Build paired training datasets for future H100 Whisper-Hinglish fine-tuning.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paths  # noqa: E402
import tempfile  # noqa: E402

import tracing  # noqa: E402

RECORDINGS_DIR = paths.RECORDINGS_DIR
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def get_gemini_38_client():
    # Always go through credentials: it enforces enterprise lockdown and the
    # user's configured project. No hardcoded fallback project.
    import credentials
    return credentials.get_client()


def find_recording_folder(recording_id: str) -> Path:
    p = Path(recording_id)
    if p.is_dir():
        return p
    for base in [
        RECORDINGS_DIR,
        Path.cwd(),
    ]:
        cand = base / recording_id
        if cand.is_dir():
            return cand
    raise FileNotFoundError(f"No recording folder found matching '{recording_id}'")


def prepare_gold_standard_segment(audio_path: Path, start_sec: float, duration: float, client=None) -> str:
    """Use Gemini 3.8 Flash to transcribe and standardize a short speech slice in pure Romanized Hinglish."""
    from google.genai import types
    client = client or get_gemini_38_client()

    # Extract 16kHz WAV slice
    tmp_wav = Path(tempfile.gettempdir()) / f"slice_{int(time.time()*1000)}.wav"
    cmd = [
        FFMPEG, "-y", "-v", "error",
        "-ss", f"{start_sec:.2f}",
        "-i", str(audio_path),
        "-t", f"{duration:.2f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(tmp_wav),
    ]
    try:
        subprocess.run(cmd, check=True)
        audio_bytes = tmp_wav.read_bytes()
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav")

        prompt = (
            "Listen to this audio slice. Transcribe the exact words spoken. "
            "Output strictly in Latin alphabet / Romanized English and Hindi (Hinglish). "
            "Do NOT use Devanagari script. Standardize phonetic spellings (e.g. use 'karega', 'nahi', 'kya', 'hai', 'matlab'). "
            "Output only the transcribed text, nothing else."
        )

        t0 = time.time()
        res = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[audio_part, prompt],
        )
        latency = time.time() - t0
        text = res.text.strip() if res and res.text else ""

        # Trace individual generation in Langfuse
        tracing.trace_pipeline_run(
            recording_id=audio_path.parent.name,
            pipeline_type="gemini_3_8_data_curation",
            model="gemini-3.8-flash",
            input_summary={"start_sec": start_sec, "duration": duration, "file": audio_path.name},
            output_summary={"gold_transcript": text},
            latency_seconds=latency,
        )
        return text
    finally:
        tmp_wav.unlink(missing_ok=True)


def curate_meeting_dataset(recording_id: str, max_slices: int = 15, dataset_name: str = "whisper-hinglish-curated"):
    """Extract gold-standard training slices from a meeting recording and sync to Langfuse dataset."""
    folder = find_recording_folder(recording_id)
    audio_file = next((p for p in folder.iterdir() if p.is_file() and p.name.startswith("audio.")), None)
    if not audio_file:
        raise FileNotFoundError(f"No audio file in {folder}")

    diar_file = folder / "diarization.json"
    if not diar_file.exists():
        diar_file = folder / "gemini_diarization.json"
    segments = []
    if diar_file.exists():
        try:
            d = json.loads(diar_file.read_text())
            segments = d.get("segments", [])
        except Exception:
            pass

    print(f"Curating dataset from: {recording_id}")
    print(f"Target Langfuse Dataset: {dataset_name}")
    print(f"AI Engine: Gemini 3.8 Flash (Vertex AI global)")

    client = get_gemini_38_client()
    curated_count = 0

    for s in segments:
        if curated_count >= max_slices:
            break

        def parse_ts(val):
            p = [float(x) for x in re.findall(r"\d+", str(val))]
            return p[0]*60 + p[1] if len(p) == 2 else (p[0]*3600 + p[1]*60 + p[2] if len(p) >= 3 else 0.0)

        st = parse_ts(s.get("start", "0:0"))
        en = parse_ts(s.get("end", "0:0"))
        dur = en - st
        if 2.0 <= dur <= 30.0:
            print(f"[{curated_count+1}] Generating gold transcription for {st:.1f}s - {en:.1f}s ({dur:.1f}s)...", flush=True)
            gold_text = prepare_gold_standard_segment(audio_file, st, dur, client=client)
            if gold_text and len(gold_text) > 5:
                print(f"    Gold: \"{gold_text}\"")
                # Save to Langfuse Dataset
                inp = {
                    "recording_id": recording_id,
                    "start_seconds": st,
                    "duration_seconds": dur,
                    "source_meeting": folder.name,
                }
                outp = {
                    "text": gold_text,
                }
                meta = {
                    "model": "gemini-3.8-flash",
                    "speaker": s.get("speaker_name") or s.get("speaker_id"),
                }
                tracing.add_to_dataset(
                    dataset_name=dataset_name,
                    input_data=inp,
                    expected_output=outp,
                    metadata=meta,
                )
                try:
                    import db
                    db.add_training_pair(
                        pair_id=f"{folder.name}_{int(st)}_{int(dur)}",
                        recording_id=folder.name,
                        pair_type="asr_slice",
                        input_data=inp,
                        expected_output=outp,
                        metadata=meta,
                        dataset_name=dataset_name,
                    )
                except Exception:
                    pass
                curated_count += 1

    print(f"\nDone! Curated {curated_count} training pairs into Langfuse dataset '{dataset_name}'.")
    print(f"View in Langfuse UI: {tracing.LANGFUSE_HOST}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Curate training data with Gemini 3.8 Flash & Langfuse")
    parser.add_argument("recording_id", type=str, help="Recording ID or folder name")
    parser.add_argument("--slices", type=int, default=10, help="Number of slices to curate")
    parser.add_argument("--dataset", type=str, default="whisper-hinglish-v2", help="Langfuse dataset name")
    args = parser.parse_args()

    curate_meeting_dataset(args.recording_id, max_slices=args.slices, dataset_name=args.dataset)
