#!/usr/bin/env python3
"""Compare recordings in the main data dir with reruns of the same audio in another data dir.
Usage: python tools/compare_engine_reruns.py <rerun-data-dir>
Matches by live recording id. Prints counts only, no transcript text, so output is safe to share."""
import json, re, sys, glob, os, difflib, sqlite3
MAIN = os.path.expanduser("~/Library/Application Support/Cora AI Meeting Notes/recordings")
RERUN = sys.argv[1]
DEV = re.compile(r"[ऀ-ॿ]")
def live_id(folder): return re.sub(r"^[0-9_-]+_(meeting_[^_]+)_[0-9a-f]+$", r"\1", os.path.basename(folder))
def load(folder):
    out = {}
    md = json.load(open(folder+"/metadata.json")); out["dur"] = md.get("duration_seconds") or 0
    t = open(folder+"/transcript_diarized.md").read()
    words = [w.lower() for w in re.findall(r"[A-Za-zऀ-ॿ']+", t)]
    out["words"] = len(words); out["wordlist"] = words
    out["devanagari_share"] = len(DEV.findall(t)) / max(1, len(re.findall(r"[A-Za-zऀ-ॿ]", t)))
    dz = json.load(open(folder+"/diarization.json")); segs = dz.get("segments", dz)
    out["segments"] = len(segs); out["speakers"] = sorted({s.get("speaker_name") for s in segs if s.get("speaker_name")})
    out["speaker_turns"] = sum(1 for i in range(1, len(segs)) if segs[i].get("speaker_id") != segs[i-1].get("speaker_id"))
    notes = open(folder+"/enhanced_notes.md").read(); out["notes_chars"] = len(notes); out["notes_bullets"] = len(re.findall(r"^\s*[-*] ", notes, re.M))
    out["notes_sections"] = re.findall(r"^#{1,3} (.+)$", notes, re.M)
    cs = json.load(open(folder+"/call_summary.json"))
    for k in ("action_items", "decisions", "unresolved_questions", "keywords"): out["n_"+k] = len(cs.get(k) or [])
    out["overview_words"] = len((cs.get("overview") or "").split()); out["model"] = cs.get("model")
    return out
def wer(ref, hyp):
    sm = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False); errs = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal": errs += max(i2-i1, j2-j1)
    return errs / max(1, len(ref))
def stage_times(db, rid):
    if not os.path.exists(db): return {}
    c = sqlite3.connect(db); r = {}
    for kind, prov, n, dur, it, ot in c.execute("select kind, provider, count(*), round(sum(duration_s),1), sum(input_tokens), sum(output_tokens) from spans where recording_id=? group by kind, provider", (rid,)):
        r[f"{kind}/{prov}"] = dict(calls=n, seconds=dur, in_tok=it, out_tok=ot)
    return r
rerun = {live_id(f): f for f in glob.glob(RERUN+"/recordings/*") if os.path.isdir(f) and os.path.exists(f+"/call_summary.json")}
for f in sorted(glob.glob(MAIN+"/*")):
    lid = live_id(f)
    if lid not in rerun: continue
    L, G = load(f), load(rerun[lid])
    print(f"\n=== {lid}  audio={L['dur']:.0f}s")
    print(f"  model             local={L['model']}  gemini={G['model']}")
    for k in ("words","devanagari_share","segments","speaker_turns","notes_chars","notes_bullets","overview_words","n_action_items","n_decisions","n_unresolved_questions","n_keywords"):
        a, b = L[k], G[k]; fmt = (lambda v: f"{v:.2%}") if k=="devanagari_share" else (lambda v: f"{v}")
        print(f"  {k:<22} local={fmt(a):>8}  gemini={fmt(b):>8}")
    print(f"  speakers           local={L['speakers']}  gemini={G['speakers']}")
    print(f"  word diff rate (local vs gemini as ref) = {wer(G['wordlist'], L['wordlist']):.1%}")
    print(f"  sections local  = {L['notes_sections']}"); print(f"  sections gemini = {G['notes_sections']}")
    st = stage_times(RERUN+"/traces.db", os.path.basename(rerun[lid]))
    if st: print("  gemini rerun spans:", json.dumps(st))
