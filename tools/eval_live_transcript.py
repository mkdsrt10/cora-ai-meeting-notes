#!/usr/bin/env python3
"""Live transcript eval (docs/specs/live-transcript.md, T6 / design §13.8 L4).

Two modes; both print counts only (no text, no names) and write their numbers
as JSON under <data dir>/research/live-transcript-eval/ (outside the repo).

  engine   Run the capture helper's live path on WAV fixtures at real time
           (dual-capture --live-test), sampling the live engines' CPU and RSS
           every 0.5 s and their open network sockets. Reports caption delay
           (the engines' lag_ms per final, p50/p95), CPU/RSS, sockets, and word
           overlap against a reference text per fixture.

             tools/eval_live_transcript.py engine --mic you.wav --mic-ref "text" [--sys them.wav --sys-ref "text"]
               [--engine-arg --locale --engine-arg en-IN] [--label NAME]

  meetings Live vs full transcript on Recordings that have both: word overlap
           per track (mic = You, sys = everyone else), Hinglish meetings
           reported separately (--hinglish ID ...), and caption delay from the
           lag_ms recorded in live_transcript.jsonl.

             tools/eval_live_transcript.py meetings [ID ...] [--hinglish ID ...]

Word overlap: bag-of-words recall of the reference by the live text (how much
of what the full transcript heard the captions also had) and precision (how
much of the captions the full transcript confirms). Case and punctuation are
ignored; Devanagari and Latin words are compared as written.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))


def words(text: str) -> list[str]:
    return [w for w in (re.sub(r"[^\w']", "", t.lower()) for t in text.split()) if w]


def overlap(live: str, reference: str) -> dict:
    a, b = collections.Counter(words(live)), collections.Counter(words(reference))
    common = sum((a & b).values())
    return {"live_words": sum(a.values()), "ref_words": sum(b.values()),
            "recall": round(common / max(1, sum(b.values())), 3),
            "precision": round(common / max(1, sum(a.values())), 3)}


def pct(values: list[float], p: float):
    if not values:
        return None
    s = sorted(values)
    import math
    return s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))]   # nearest rank


def out_dir() -> Path:
    import paths
    d = paths.DATA_DIR / "research" / "live-transcript-eval"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- engine ---------------------------------------------------------------------

def _children(pid: int) -> list[tuple[int, str, float, int]]:
    """(pid, name, cpu%, rss KB) of pid's live engine children."""
    ps = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,pcpu=,rss=,comm="], capture_output=True, text=True).stdout
    rows = []
    for line in ps.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(.+)$", line)
        if m and int(m.group(2)) == pid:
            rows.append((int(m.group(1)), m.group(5).rsplit("/", 1)[-1], float(m.group(3)), int(m.group(4))))
    return rows


# Apple's on-device recognizer runs the model in this system XPC service, not in
# live-engine itself: it is sampled with the engines (it may also serve other apps).
SYSTEM_SPEECH = ("localspeechrecognition",)


def _system_speech() -> list[tuple[int, str, float, int]]:
    ps = subprocess.run(["ps", "-A", "-o", "pid=,pcpu=,rss=,comm="], capture_output=True, text=True).stdout
    rows = []
    for line in ps.splitlines():
        m = re.match(r"\s*(\d+)\s+([\d.]+)\s+(\d+)\s+(.+)$", line)
        if m and m.group(4).rsplit("/", 1)[-1] in SYSTEM_SPEECH:
            rows.append((int(m.group(1)), m.group(4).rsplit("/", 1)[-1], float(m.group(2)), int(m.group(3))))
    return rows


def _sockets(pids: list[int]) -> int:
    if not pids:
        return 0
    out = subprocess.run(["lsof", "-nP", "-a", "-i", "-p", ",".join(map(str, pids))], capture_output=True, text=True).stdout
    return max(0, len(out.strip().splitlines()) - 1) if out.strip() else 0


def engine_mode(args) -> dict:
    subprocess.run(["make", "capture/dual-capture", "capture/live-engine"], cwd=ROOT, check=True, capture_output=True)
    cmd = [str(ROOT / "capture" / "dual-capture"), "--live-test", args.mic] + ([args.sys] if args.sys else [])
    cmd += ["--live-engine", str(ROOT / "capture" / "live-engine")]
    for extra in args.engine_arg or []:
        cmd += ["--live-arg", extra]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    samples, sockets, all_pids = [], 0, set()
    stop = threading.Event()

    def sample():
        nonlocal sockets
        while not stop.is_set():
            kids = _children(proc.pid) + _system_speech()
            all_pids.update(k[0] for k in kids)
            if kids:
                samples.append((sum(k[2] for k in kids), sum(k[3] for k in kids)))
            sockets = max(sockets, _sockets([proc.pid] + [k[0] for k in kids]))
            stop.wait(0.5)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    stdout, _ = proc.communicate(timeout=600)
    stop.set()
    sampler.join()
    wall = time.monotonic() - started

    lines = []
    for raw in stdout.splitlines():
        kind, _, payload = raw.partition(" ")
        if kind.startswith("LIVE_"):
            lines.append((kind, json.loads(payload)))
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    lags = [p["lag_ms"] for p in finals]
    partial_lags = [p["lag_ms"] for k, p in lines if k == "LIVE_PARTIAL"]
    engines = sorted({p["engine"] for k, p in lines if k == "LIVE_ENGINE"})
    result = {
        "label": args.label, "engines": engines, "wall_s": round(wall, 1),
        "finals": len(finals), "partials": len(partial_lags),
        "final_lag_ms_p50": pct(lags, 50), "final_lag_ms_p95": pct(lags, 95),
        "partial_lag_ms_p50": pct(partial_lags, 50), "partial_lag_ms_p95": pct(partial_lags, 95),
        # live-engine processes plus the system speech service (SYSTEM_SPEECH)
        "engine_cpu_pct_avg": round(statistics.mean(s[0] for s in samples), 1) if samples else None,
        "engine_cpu_pct_max": round(max(s[0] for s in samples), 1) if samples else None,
        "engine_rss_mb_max": round(max(s[1] for s in samples) / 1024) if samples else None,
        "network_sockets_max": sockets,
        "paused": [p.get("code") for k, p in lines if k == "LIVE_STATUS" and p.get("state") == "paused"],
    }
    for track, ref in (("mic", args.mic_ref), ("sys", args.sys_ref)):
        if ref:
            text = " ".join(p["text"] for p in finals if p["track"] == track)
            result[f"overlap_{track}"] = overlap(text, ref)
    return result


# --- meetings -------------------------------------------------------------------

def meetings_mode(args) -> dict:
    import db
    import live_transcript
    db.init_db()
    ids = args.ids or [r["id"] for r in db.get_all_recordings() if live_transcript.path_for(r["id"])]
    hinglish = set(args.hinglish or [])
    groups = {"other": collections.defaultdict(lambda: collections.defaultdict(str)),
              "hinglish": collections.defaultdict(lambda: collections.defaultdict(str))}
    lags: dict[str, list[float]] = {"other": [], "hinglish": []}
    counted = {"other": 0, "hinglish": 0}
    for rec_id in ids:
        rec = db.get_recording(rec_id)
        segments = ((rec or {}).get("diarization") or {}).get("segments") or []
        live = [x for x in live_transcript.read_all(rec_id) if x.get("final")]
        if not segments or not live:
            continue
        g = "hinglish" if rec_id in hinglish else "other"
        counted[g] += 1
        for s in segments:
            groups[g]["mic" if s.get("speaker_id") == "You" else "sys"]["full"] += " " + str(s.get("text") or "")
        for x in live:
            groups[g][x.get("track", "sys")]["live"] += " " + str(x.get("text") or "")
            if isinstance(x.get("lag_ms"), (int, float)):
                lags[g].append(x["lag_ms"])
    result = {}
    for g, tracks in groups.items():
        result[g] = {"recordings": counted[g], "lag_ms_p50": pct(lags[g], 50), "lag_ms_p95": pct(lags[g], 95)}
        for track, texts in tracks.items():
            result[g][f"overlap_{track}"] = overlap(texts["live"], texts["full"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Live transcript eval: counts only.")
    sub = parser.add_subparsers(dest="mode", required=True)
    e = sub.add_parser("engine")
    e.add_argument("--mic", required=True)
    e.add_argument("--sys")
    e.add_argument("--mic-ref")
    e.add_argument("--sys-ref")
    e.add_argument("--engine-arg", action="append")
    e.add_argument("--label", default="fixtures")
    m = sub.add_parser("meetings")
    m.add_argument("ids", nargs="*")
    m.add_argument("--hinglish", nargs="*")
    args = parser.parse_args()
    result = engine_mode(args) if args.mode == "engine" else meetings_mode(args)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    (out_dir() / f"{args.mode}-{stamp}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
