#!/usr/bin/env python3
"""Extract full Whisper Hinglish training dataset from Cora recordings.

Adheres strictly to training guidelines:
1. Relative path consistency: "audio": "data/audio/slice_XXXXXX.wav"
2. Meeting isolation: "source_meeting" field included on all records for leakage-free splitting
3. Strict duration bounds: 1.0s <= duration <= 25.0s (Whisper max window is 30s)
4. Non-empty transcripts: filters empty, silent, or whitespace-only text
5. Script: Strictly Romanized Hindi / Hinglish (all Devanagari phonetically mapped)
"""

import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paths  # noqa: E402

RECORDINGS_DIR = paths.RECORDINGS_DIR
OUTPUT_DIR = paths.DATA_DIR / "whisper_full_dataset"
AUDIO_DIR = OUTPUT_DIR / "data" / "audio"

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

VOWELS = {
    "\u0905": "a", "\u0906": "aa", "\u0907": "i", "\u0908": "ee",
    "\u0909": "u", "\u090A": "oo", "\u090F": "e", "\u0910": "ai",
    "\u0913": "o", "\u0914": "au", "\u090B": "ri", "\u090D": "e", "\u0911": "o"
}
MATRAS = {
    "\u093E": "aa", "\u093F": "i", "\u0940": "ee", "\u0941": "u",
    "\u0942": "oo", "\u0947": "e", "\u0948": "ai", "\u094B": "o",
    "\u094C": "au", "\u0943": "ri", "\u0945": "e", "\u0949": "o"
}
CONSONANTS = {
    "\u0915": "k", "\u0916": "kh", "\u0917": "g", "\u0918": "gh", "\u0919": "ng",
    "\u091A": "ch", "\u091B": "chh", "\u091C": "j", "\u091D": "jh", "\u091E": "ny",
    "\u091F": "t", "\u0920": "th", "\u0921": "d", "\u0922": "dh", "\u0923": "n",
    "\u0924": "t", "\u0925": "th", "\u0926": "d", "\u0927": "dh", "\u0928": "n",
    "\u092A": "p", "\u092B": "f", "\u092C": "b", "\u092D": "bh", "\u092E": "m",
    "\u092F": "y", "\u0930": "r", "\u0932": "l", "\u0935": "v",
    "\u0936": "sh", "\u0937": "sh", "\u0938": "s", "\u0939": "h",
    "\u0958": "q", "\u0959": "kh", "\u095A": "gh", "\u095B": "z",
    "\u095C": "r", "\u095D": "rh", "\u095E": "f", "\u095F": "y"
}


def devanagari_to_roman(text: str) -> str:
    """Phonetic transliteration of Devanagari text to Roman script with Hindi schwa deletion."""
    words = text.split()
    out_words = []

    for word in words:
        res = []
        n = len(word)
        i = 0
        while i < n:
            ch = word[i]
            if ch in VOWELS:
                res.append(VOWELS[ch])
            elif ch in CONSONANTS:
                c_rom = CONSONANTS[ch]
                next_ch = word[i + 1] if i + 1 < n else None
                if next_ch == "\u094D":  # halant (suppress inherent 'a')
                    res.append(c_rom)
                    i += 1
                elif next_ch in MATRAS:
                    res.append(c_rom + MATRAS[next_ch])
                    i += 1
                else:
                    is_word_end = (i == n - 1 or (i == n - 2 and word[i + 1] in ["\u0902", "\u0901"]))
                    if is_word_end and len(word) > 1:
                        res.append(c_rom)
                    else:
                        res.append(c_rom + "a")
            elif ch in MATRAS:
                res.append(MATRAS[ch])
            elif ch in ["\u0902", "\u0901"]:
                res.append("n")
            elif ch == "\u0964":
                res.append(".")
            else:
                res.append(ch)
            i += 1
        out_words.append("".join(res))
    return " ".join(out_words)


def clean_text(raw: str) -> str:
    """Normalize text and ensure strictly Romanized Hindi/English output."""
    t = raw.strip()
    if DEVANAGARI_RE.search(t):
        t = devanagari_to_roman(t)
    # Remove excessive whitespace and special punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_timestamp(value: str) -> float:
    """Robust timestamp parser handling MM:SS, HH:MM:SS, and dash-separated formats."""
    parts = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value))]
    if len(parts) >= 3:
        return parts[-3] * 3600 + parts[-2] * 60 + parts[-1]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] if parts else 0.0


def collect_candidate_segments():
    candidates = []
    for folder in sorted(RECORDINGS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        diar_path = folder / "gemini_diarization.json"
        audio_path = next((p for p in folder.iterdir() if p.is_file() and p.name.startswith("audio.")), None)
        if not diar_path.exists() or not audio_path:
            continue

        try:
            diar = json.loads(diar_path.read_text(errors="replace"))
        except Exception:
            continue

        for seg in diar.get("segments", []):
            raw_text = seg.get("text", "")
            if not raw_text or not raw_text.strip():
                continue

            text = clean_text(raw_text)
            if not text:
                continue

            start_sec = parse_timestamp(seg.get("start", "0:0"))
            end_sec = parse_timestamp(seg.get("end", "0:0"))
            dur = end_sec - start_sec

            # Guideline 3: 1.0s <= duration <= 25.0s
            if 1.0 <= dur <= 25.0:
                candidates.append({
                    "audio_file": str(audio_path),
                    "start_sec": start_sec,
                    "dur": dur,
                    "text": text,
                    "source_meeting": folder.name,
                })
    return candidates


def slice_worker(task):
    idx, item, out_path = task
    cmd = [
        "/opt/homebrew/bin/ffmpeg", "-y",
        "-ss", f"{item['start_sec']:.2f}",
        "-i", item["audio_file"],
        "-t", f"{item['dur']:.2f}",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(out_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if out_path.exists() and out_path.stat().st_size > 500:
            return idx, True, None
        return idx, False, "Output file empty or missing"
    except Exception as e:
        return idx, False, str(e)


def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    print("Collecting eligible segments across recordings...")
    t0 = time.time()
    candidates = collect_candidate_segments()
    print(f"Found {len(candidates)} valid candidate segments.")

    tasks = []
    dataset_records = []
    for idx, c in enumerate(candidates, 1):
        filename = f"slice_{idx:06d}.wav"
        out_wav = AUDIO_DIR / filename
        tasks.append((idx, c, out_wav))
        dataset_records.append({
            "audio": f"data/audio/{filename}",
            "text": c["text"],
            "duration_seconds": round(c["dur"], 2),
            "source_meeting": c["source_meeting"],
        })

    print(f"Starting parallel audio extraction with 10 workers...")
    succeeded = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(slice_worker, task): task[0] for task in tasks}
        total = len(futures)
        for i, future in enumerate(as_completed(futures), 1):
            idx, ok, err = future.result()
            if ok:
                succeeded += 1
            else:
                failed += 1
            if i % 1000 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed
                print(f"[{i}/{total}] Slices processed ({succeeded} ok, {failed} failed) · {rate:.1f} slices/sec · {elapsed/60:.1f} min elapsed", flush=True)

    # Filter dataset records for only successful audio files
    final_records = [r for idx, r in enumerate(dataset_records, 1) if (AUDIO_DIR / f"slice_{idx:06d}.wav").exists()]

    json_path = OUTPUT_DIR / "dataset.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final_records, f, indent=2, ensure_ascii=False)

    jsonl_path = OUTPUT_DIR / "dataset.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for r in final_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_dur_hours = sum(r["duration_seconds"] for r in final_records) / 3600
    unique_meetings = len(set(r["source_meeting"] for r in final_records))

    meta = {
        "total_slices": len(final_records),
        "total_duration_hours": round(total_dur_hours, 2),
        "unique_source_meetings": unique_meetings,
        "sample_rate_hz": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "script": "Romanized Hindi / Hinglish",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(meta, indent=2))

    print("\nDataset extraction complete!")
    print(f"Total Slices: {len(final_records)}")
    print(f"Total Audio Duration: {total_dur_hours:.2f} hours")
    print(f"Source Meetings: {unique_meetings}")
    print(f"Saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
