#!/usr/bin/env python3
"""Benchmark speech-to-text models on one of your own meetings.

Standalone on purpose: it runs on a bare Linux/CUDA VM or a Mac Studio, not
just inside a Cora checkout. Output is metrics only (no transcript text)
unless you pass --dump-hyp, so results are safe to paste/share.

Step 1 (on the Mac that has the meeting) — make a bundle to benchmark on:

    python tools/asr_bench.py prepare <recording-id> --out bench-bundle

  bundle/audio.wav      speech-only 16 kHz mono audio (Cora's audio_transcribed.wav)
  bundle/reference.txt  the transcript text from the recording — fix it in the
                        transcript editor first so it is a real reference

Step 2 (anywhere) — run models against it:

    python tools/asr_bench.py run bench-bundle \\
        --model mlx-whisper:/Users/me/tara-mlx \\
        --model hf-whisper:Trelis/tara \\
        --model indic-conformer:ai4bharat/indic-conformer-600m-multilingual \\
        --model "cmd:python my_asr.py {wav}"

Backends (each imports lazily, so only what you use needs installing):
  mlx-whisper:<repo|dir>      Apple Silicon        pip install mlx-whisper
  hf-whisper:<repo>           CUDA / CPU / MPS     pip install transformers torch accelerate
  indic-conformer:<repo>      CUDA / CPU           pip install transformers torch torchaudio
  gemini:<model>              needs Cora's Google creds (run from a checkout)
  cmd:<template>              anything else: a shell command that prints the
                              transcript on stdout; {wav} is the clip path.
                              Use this for Qwen3-ASR, Voxtral, Sarvam, etc.

Audio is split into <=25 s chunks like Cora's pipeline (so a model's
long-form hallucination behaviour is not what's being measured) and each
model sees identical chunks. Scores: WER and CER (lowercased, punctuation
stripped, Hindi optionally Romanized so Devanagari output isn't penalised
against Roman references) and real-time factor (audio seconds per second).
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

CHUNK_S = 25.0
REPO = Path(__file__).resolve().parents[1]


# --- text normalisation and scoring ----------------------------------------

def _romanize(text: str) -> str:
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    sys.path.insert(0, str(REPO / "python"))
    try:
        from pipeline.romanize import transliterate
        return transliterate(text)
    except Exception:
        print("  (note: Devanagari output but Cora's romanizer isn't importable here — scores will be pessimistic)",
              file=sys.stderr)
        return text


def normalise(text: str, romanize: bool) -> str:
    if romanize:
        text = _romanize(text)
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    return edit_distance(r, h) / max(len(r), 1)


def cer(ref: str, hyp: str) -> float:
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    return edit_distance(r, h) / max(len(r), 1)


# --- audio ------------------------------------------------------------------

def ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        sys.exit("ffmpeg is required (brew install ffmpeg / apt install ffmpeg)")
    return path


def duration(wav: Path) -> float:
    out = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(wav)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def split_chunks(wav: Path, workdir: Path, limit_s: float | None) -> list[Path]:
    total = min(duration(wav), limit_s) if limit_s else duration(wav)
    chunks, start, idx = [], 0.0, 0
    while start < total:
        length = min(CHUNK_S, total - start)
        out = workdir / f"chunk_{idx:04d}.wav"
        subprocess.run([ffmpeg(), "-y", "-ss", str(start), "-i", str(wav), "-t", str(length), "-ac", "1", "-ar", "16000",
                        str(out)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        chunks.append(out)
        start += length
        idx += 1
    return chunks


# --- backends: each returns a callable wav_path -> text ----------------------

def backend_mlx_whisper(spec: str):
    import mlx_whisper
    return lambda wav: mlx_whisper.transcribe(str(wav), path_or_hf_repo=spec, language="en",
                                              condition_on_previous_text=False, word_timestamps=False)["text"]


def backend_hf_whisper(spec: str):
    import torch
    from transformers import pipeline
    device = "cuda:0" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    asr = pipeline("automatic-speech-recognition", model=spec, device=device,
                   torch_dtype=torch.float16 if device != "cpu" else torch.float32)
    return lambda wav: asr(str(wav), generate_kwargs={"language": "en", "task": "transcribe"})["text"]


def backend_indic_conformer(spec: str):
    # Loading/calling convention follows the model card for
    # ai4bharat/indic-conformer-600m-multilingual (trust_remote_code,
    # model(wav, lang, decoder)). If the card has changed, adjust here or
    # use the cmd: backend with your own script.
    import torch
    import torchaudio
    from transformers import AutoModel
    model = AutoModel.from_pretrained(spec, trust_remote_code=True)

    def run(wav: Path) -> str:
        samples, sr = torchaudio.load(str(wav))
        samples = torch.mean(samples, dim=0, keepdim=True)
        if sr != 16000:
            samples = torchaudio.transforms.Resample(sr, 16000)(samples)
        return str(model(samples, "hi", "rnnt"))
    return run


def backend_gemini(spec: str):
    sys.path.insert(0, str(REPO / "python"))
    import db
    from pipeline import cloud_asr
    db.set_setting("cloud_asr_model", spec)
    return lambda wav: cloud_asr.transcribe_gemini(wav, "")["text"]


def backend_cmd(spec: str):
    def run(wav: Path) -> str:
        argv = [part.replace("{wav}", str(wav)) for part in shlex.split(spec)]
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout
    return run


BACKENDS = {
    "mlx-whisper": backend_mlx_whisper,
    "hf-whisper": backend_hf_whisper,
    "indic-conformer": backend_indic_conformer,
    "gemini": backend_gemini,
    "cmd": backend_cmd,
}


# --- commands ---------------------------------------------------------------

def cmd_prepare(args) -> None:
    sys.path.insert(0, str(REPO / "python"))
    import paths
    folder = paths.RECORDINGS_DIR / args.recording_id
    audio = folder / "audio_transcribed.wav"
    diarization = folder / "diarization.json"
    if not audio.is_file() or not diarization.is_file():
        sys.exit(f"{folder} needs audio_transcribed.wav and diarization.json (process the meeting first, and keep audio on).")
    segments = json.loads(diarization.read_text()).get("segments", [])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(audio, out / "audio.wav")
    (out / "reference.txt").write_text("\n".join(s.get("text", "") for s in segments) + "\n")
    print(f"Wrote {out}/audio.wav and {out}/reference.txt — this is a real meeting: keep it private, "
          f"or pick a non-sensitive one. Edit speakers/text in Cora first if the reference has errors.")


def cmd_run(args) -> None:
    bundle = Path(args.bundle)
    wav, ref_raw = bundle / "audio.wav", (bundle / "reference.txt").read_text()
    total = min(duration(wav), args.limit_seconds) if args.limit_seconds else duration(wav)
    ref = normalise(ref_raw, args.romanize)
    if args.limit_seconds:
        # Reference isn't timestamped; trim it proportionally so a partial run
        # is compared against roughly the same stretch.
        words = ref.split()
        ref = " ".join(words[: int(len(words) * total / duration(wav))])
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        chunks = split_chunks(wav, Path(tmp), args.limit_seconds)
        print(f"{len(chunks)} chunks, {total:.0f}s of audio, reference {len(ref.split())} words\n")
        for spec in args.model:
            kind, _, arg = spec.partition(":")
            if kind not in BACKENDS:
                sys.exit(f"unknown backend {kind!r}; choose from {', '.join(BACKENDS)}")
            print(f"== {spec}")
            try:
                load_t = time.time()
                transcribe = BACKENDS[kind](arg)
                load_s = time.time() - load_t
                t0 = time.time()
                hyp = " ".join(str(transcribe(c)).strip() for c in chunks)
                run_s = time.time() - t0
            except Exception as exc:  # keep going so one broken backend doesn't waste the rest
                print(f"   FAILED: {exc}\n")
                results.append({"model": spec, "error": str(exc)})
                continue
            hyp_n = normalise(hyp, args.romanize)
            row = {"model": spec, "wer": round(wer(ref, hyp_n), 4), "cer": round(cer(ref, hyp_n), 4),
                   "rtf": round(total / run_s, 1), "load_s": round(load_s, 1), "hyp_words": len(hyp_n.split())}
            results.append(row)
            print(f"   WER {row['wer']:.1%}  CER {row['cer']:.1%}  {row['rtf']}x realtime  (load {row['load_s']}s)\n")
            if args.dump_hyp:
                (bundle / f"hyp_{re.sub(r'[^A-Za-z0-9]+', '_', spec)}.txt").write_text(hyp + "\n")
    print("| model | WER | CER | x realtime | words out |\n|---|---|---|---|---|")
    for r in results:
        if "error" in r:
            print(f"| {r['model']} | failed | | | |")
        else:
            print(f"| {r['model']} | {r['wer']:.1%} | {r['cer']:.1%} | {r['rtf']} | {r['hyp_words']} |")
    (bundle / "bench_results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nSaved {bundle}/bench_results.json (metrics only).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="build audio.wav + reference.txt from a Cora recording")
    prep.add_argument("recording_id")
    prep.add_argument("--out", default="bench-bundle")
    run = sub.add_parser("run", help="score models against a bundle")
    run.add_argument("bundle")
    run.add_argument("--model", action="append", required=True, help="backend:spec (repeatable)")
    run.add_argument("--limit-seconds", type=float, help="only the first N seconds (quick smoke test)")
    run.add_argument("--no-romanize", dest="romanize", action="store_false", help="compare scripts as-is")
    run.add_argument("--dump-hyp", action="store_true", help="also write each model's transcript (private!)")
    args = parser.parse_args()
    (cmd_prepare if args.command == "prepare" else cmd_run)(args)


if __name__ == "__main__":
    main()
