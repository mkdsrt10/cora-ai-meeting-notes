import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
import db
import credentials

import paths

PEOPLE_DIR = paths.PEOPLE_DIR

def extract_reference_clip(audio_path: Path, segments: list[dict[str, Any]], target_speaker: str, output_path: Path):
    PEOPLE_DIR.mkdir(exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Find longest segment for this speaker
    speaker_segments = [s for s in segments if s.get("speaker_id") == target_speaker]
    if not speaker_segments:
        return
        
    def get_duration(seg):
        try:
            start_parts = [int(x) for x in seg.get("start", "00:00").split("-")[0].strip().split(":")]
            end_parts = [int(x) for x in seg.get("end", "00:00").split("-")[0].strip().split(":")]
            s = start_parts[-2]*60 + start_parts[-1] if len(start_parts) >= 2 else 0
            e = end_parts[-2]*60 + end_parts[-1] if len(end_parts) >= 2 else 0
            return max(0, e - s)
        except:
            return 0
            
    speaker_segments.sort(key=get_duration, reverse=True)
    best_seg = speaker_segments[0]
    
    if get_duration(best_seg) < 3:
        return # Too short
        
    start_time = best_seg.get("start", "00:00").split("-")[0].strip()
    end_time = best_seg.get("end", "00:00").split("-")[0].strip()
    
    try:
        subprocess.run([
            shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg", "-y", "-i", str(audio_path),
            "-ss", start_time, "-to", end_time,
            "-c", "copy", str(output_path)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Failed to extract clip: {e}")

def run_voice_match(recording_id: str, audio_path: Path, segments: list[dict[str, Any]], speakers: list[dict[str, Any]], client=None):
    candidates = db.get_recent_people(8)
    if not candidates:
        return
        
    from google.genai import types
    if not client:
        client = credentials.get_client()
        if not client:
            return

    candidate_parts = []
    for c in candidates:
        ref_path = Path(c["reference_clip_path"]) if c.get("reference_clip_path") else None
        if ref_path and ref_path.exists():
            candidate_parts.append({
                "person_id": c["id"],
                "name": c.get("name", "Unknown"),
                "bytes": ref_path.read_bytes(),
            })
            
    if not candidate_parts:
        return

    prompt = (
        "You are a voice matching assistant. Listen to the target audio clip first. "
        "Then listen to the candidate clips provided. Based strictly on the acoustic signature, "
        "voice tone, and timbre, determine which candidate best matches the target speaker. "
        "If none match well, return 'none'."
    )
    
    schema = {
        "type": "object",
        "properties": {
            "matched_person_id": {"type": "string", "description": "The ID of the best matching candidate, or 'none'"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low", "none"]}
        },
        "required": ["matched_person_id", "confidence"]
    }
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        temperature=0.1,
    )

    for speaker in speakers:
        speaker_id = speaker["speaker_id"]
        
        # Extract a temporary clip for this new unknown speaker to match against the candidates
        temp_clip = PEOPLE_DIR / f"temp_{recording_id}_{speaker_id}.m4a"
        extract_reference_clip(audio_path, segments, speaker_id, temp_clip)
        
        if not temp_clip.exists():
            continue
            
        try:
            target_part = types.Part.from_bytes(data=temp_clip.read_bytes(), mime_type="audio/mp4")
            contents = [prompt, "Target Speaker Clip:", target_part]
            for c in candidate_parts:
                contents.append(f"Candidate Person ID: {c['person_id']} ({c['name']})")
                contents.append(types.Part.from_bytes(data=c["bytes"], mime_type="audio/mp4"))
                
            res = client.models.generate_content(
                model=credentials.get_default_model(),
                contents=contents,
                config=config,
            )
            data = json.loads(res.text)
            match_id = data.get("matched_person_id")
            conf = data.get("confidence", "none")
            
            if match_id and match_id != "none" and match_id in [c["person_id"] for c in candidate_parts]:
                db.upsert_speaker_match(recording_id, speaker_id, match_id, conf, False)
        except Exception as e:
            print(f"Voice match failed for {speaker_id}: {e}")
        finally:
            temp_clip.unlink(missing_ok=True)
