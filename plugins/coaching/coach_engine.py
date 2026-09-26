#!/usr/bin/env python3
"""Deterministic, local speech-coaching analysis for Voice Memo Archive."""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from typing import Any

STOPWORDS = {
    "a","an","and","are","as","at","be","been","but","by","for","from","had","has","have",
    "he","her","his","i","if","in","is","it","its","me","my","not","of","on","or","our",
    "she","so","that","the","their","them","there","they","this","to","up","us","was","we",
    "were","what","when","which","who","will","with","would","you","your","do","did","does",
}
FILLERS = ["um", "uh", "erm", "hmm", "like", "you know", "basically", "actually", "literally", "kind of", "sort of", "i mean"]
ACTION_RE = re.compile(r"\b(need to|have to|should|must|will|next steps?|action items?|follow up|deadline|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today))\b", re.I)
QUESTION_RE = re.compile(r"\?$|\b(what|why|how|when|where|who|could|would|should|can)\b", re.I)
MODE_LABELS = {
    "free": "Free thinking",
    "story": "Storytelling",
    "negotiation": "Negotiation",
    "direction": "Giving direction",
    "pronunciation": "Pronunciation practice",
}


def clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def atomic_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in chunks if s.strip()]


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower(), re.UNICODE)


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if len(w) > 2 and w not in STOPWORDS]


def detect_mode(text: str, requested: str | None = None) -> str:
    if requested in MODE_LABELS:
        return requested
    opening = text[:240].lower()
    explicit = re.search(r"mode\s*[:\-]?\s*(free thinking|storytelling|story|negotiation|giving direction|direction|pronunciation)", opening)
    if explicit:
        raw = explicit.group(1)
        return {"free thinking":"free", "storytelling":"story", "giving direction":"direction"}.get(raw, raw)
    scores = {
        "negotiation": sum(term in text.lower() for term in ["deal", "offer", "price", "terms", "batna", "concession", "walk away", "counter"]),
        "direction": sum(term in text.lower() for term in ["need you to", "owner", "deadline", "deliver", "success criteria", "by tomorrow", "next step"]),
        "story": sum(term in text.lower() for term in ["then", "but", "because", "eventually", "realized", "result", "happened"]),
        "pronunciation": sum(term in text.lower() for term in ["pronunciation", "practice passage", "repeat after"]),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "free"


def silence_metrics(audio: Path, duration: float) -> dict[str, Any]:
    if not audio.exists() or duration <= 0:
        return {"pause_count": 0, "pause_seconds": 0.0, "silence_ratio": 0.0, "pause_rate": 0.0}
    command = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af", "silencedetect=noise=-35dB:d=0.55", "-f", "null", "-"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=min(90, max(15, int(duration / 4))))
        ends = re.findall(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", result.stderr)
        pause_seconds = sum(float(item[1]) for item in ends)
        minutes = max(duration / 60, 1 / 60)
        return {
            "pause_count": len(ends),
            "pause_seconds": round(pause_seconds, 2),
            "silence_ratio": round(min(1.0, pause_seconds / duration), 3),
            "pause_rate": round(len(ends) / minutes, 2),
        }
    except (subprocess.TimeoutExpired, OSError):
        return {"pause_count": 0, "pause_seconds": 0.0, "silence_ratio": 0.0, "pause_rate": 0.0}


def repeated_sentence_ratio(items: list[str]) -> tuple[float, list[str]]:
    if len(items) < 2:
        return 0.0, []
    repeats: list[str] = []
    repeated = 0
    seen: list[set[str]] = []
    for sentence in items:
        bag = set(content_words(sentence))
        similarity = max((len(bag & old) / max(1, len(bag | old)) for old in seen), default=0)
        if similarity >= 0.62 and len(bag) >= 3:
            repeated += 1
            repeats.append(sentence)
        seen.append(bag)
    return repeated / len(items), repeats[:5]


def extractive_rewrite(items: list[str], maximum: int = 5) -> tuple[str, list[str]]:
    if not items:
        return "No usable speech was detected.", []
    corpus = collections.Counter(content_words(" ".join(items)))
    peak = max(corpus.values(), default=1)
    scored = []
    selected_bags: list[set[str]] = []
    for index, sentence in enumerate(items):
        bag = content_words(sentence)
        if not bag:
            continue
        score = sum(corpus[w] / peak for w in bag) / len(bag)
        if 6 <= len(words(sentence)) <= 32:
            score *= 1.25
        if ACTION_RE.search(sentence):
            score *= 1.12
        scored.append((score, index, sentence, set(bag)))
    chosen = []
    for score, index, sentence, bag in sorted(scored, reverse=True):
        if any(len(bag & old) / max(1, len(bag | old)) > .58 for old in selected_bags):
            continue
        chosen.append((index, sentence))
        selected_bags.append(bag)
        if len(chosen) >= maximum:
            break
    chosen.sort()
    clean = [sentence for _, sentence in chosen]
    return " ".join(clean), clean


def structure_score(text: str, mode: str) -> tuple[int, list[dict[str, Any]]]:
    lower = text.lower()
    rubrics = {
        "story": [
            ("Context", ["when", "at the time", "we were", "the situation", "context"]),
            ("Tension", ["problem", "challenge", "but", "risk", "conflict"]),
            ("Decision", ["decided", "chose", "realized", "decision"]),
            ("Action", ["did", "built", "created", "changed", "started"]),
            ("Result", ["result", "outcome", "eventually", "led to", "impact"]),
            ("Meaning", ["learned", "takeaway", "means", "lesson"]),
        ],
        "negotiation": [
            ("Objective", ["goal", "want", "objective", "outcome"]),
            ("Evidence", ["because", "data", "evidence", "market", "value"]),
            ("Anchor", ["offer", "price", "anchor", "terms"]),
            ("BATNA", ["alternative", "batna", "walk away", "otherwise"]),
            ("Questions", ["what", "why", "how", "could you", "would you"]),
            ("Next step", ["next step", "follow up", "deadline", "agree"]),
        ],
        "direction": [
            ("Outcome", ["goal", "outcome", "deliver", "need"]),
            ("Why", ["because", "why", "reason", "impact"]),
            ("Constraints", ["constraint", "must", "cannot", "within"]),
            ("Owner", ["owner", "you will", "responsible", "i need you"]),
            ("Deadline", ["deadline", "by tomorrow", "by monday", "date", "when"]),
            ("Success criteria", ["success", "done when", "measure", "acceptance"]),
        ],
        "free": [
            ("Main point", ["main point", "important", "focus", "idea"]),
            ("Reason", ["because", "reason", "why"]),
            ("Example", ["example", "for instance", "such as"]),
            ("Conclusion", ["therefore", "so", "conclusion", "takeaway"]),
        ],
        "pronunciation": [
            ("Controlled pace", []), ("Clear pauses", []), ("Consistent delivery", []),
        ],
    }
    checks = []
    for name, markers in rubrics[mode]:
        present = any(marker in lower for marker in markers) if markers else False
        checks.append({"name": name, "present": present})
    if mode == "pronunciation":
        return 0, checks
    return clamp(100 * sum(item["present"] for item in checks) / len(checks)), checks


def analyze_folder(folder: Path, requested_mode: str | None = None) -> dict[str, Any]:
    folder = folder.resolve()
    transcript_path = folder / "transcript.txt"
    metadata_path = folder / "metadata.json"
    if not transcript_path.exists():
        raise FileNotFoundError(f"Missing transcript: {transcript_path}")
    text = transcript_path.read_text(errors="replace").strip()
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    audio = next((p for p in folder.iterdir() if p.name.startswith("audio.") and p.is_file()), Path())
    duration = float(metadata.get("duration_seconds") or 0)
    tokens = words(text)
    sents = sentences(text)
    minutes = max(duration / 60, 1 / 60)
    wpm = len(tokens) / minutes if duration else 0

    filler_counts = {}
    lower = text.lower()
    for filler in FILLERS:
        count = len(re.findall(rf"\b{re.escape(filler)}\b", lower))
        if count:
            filler_counts[filler] = count
    filler_total = sum(filler_counts.values())
    filler_rate = filler_total / minutes if duration else 0
    content = content_words(text)
    lexical_diversity = len(set(content)) / max(1, len(content))
    avg_sentence_words = len(tokens) / max(1, len(sents))
    long_sentences = [s for s in sents if len(words(s)) > 35]
    repeat_ratio, repeated = repeated_sentence_ratio(sents)
    meaningful = [s for s in sents if len(content_words(s)) >= 5]
    idea_density = len(meaningful) / minutes if duration else 0
    action_items = [s for s in sents if ACTION_RE.search(s)][:8]
    questions = [s for s in sents if QUESTION_RE.search(s)][:8]
    mode = detect_mode(text, requested_mode)
    delivery = silence_metrics(audio, duration)
    structure, checklist = structure_score(text, mode)

    pace_score = 100 - min(55, abs(wpm - 145) * 0.65) if wpm else 35
    filler_score = 100 - min(70, filler_rate * 13)
    sentence_score = 100 - min(50, max(0, avg_sentence_words - 22) * 2.2)
    repetition_score = 100 - repeat_ratio * 120
    lexical_score = 45 + min(55, lexical_diversity * 75)
    clarity = clamp(.28 * pace_score + .25 * filler_score + .22 * sentence_score + .25 * repetition_score)
    concision = clamp(.38 * filler_score + .38 * repetition_score + .24 * sentence_score)
    delivery_score = clamp(.55 * pace_score + .25 * filler_score + .20 * (90 if 1 <= delivery["pause_rate"] <= 8 else 60))
    overall = clamp(.30 * clarity + .24 * concision + .20 * delivery_score + .26 * structure)

    priorities = []
    if filler_rate > 2:
        priorities.append({"title": "Replace fillers with silence", "detail": f"You used {filler_total} fillers ({filler_rate:.1f}/min). Pause for one beat instead.", "exercise": "Record 60 seconds and force a full pause whenever you feel a filler coming."})
    if repeat_ratio > .12:
        priorities.append({"title": "State each point once", "detail": f"About {repeat_ratio:.0%} of sentences substantially repeated an earlier idea.", "exercise": "Use: point → reason → example → next point."})
    if avg_sentence_words > 24:
        priorities.append({"title": "Shorten sentence units", "detail": f"Average sentence length is {avg_sentence_words:.1f} words.", "exercise": "End each sentence after one claim. Start a new sentence for evidence."})
    if structure < 65:
        missing = ", ".join(item["name"] for item in checklist if not item["present"])
        priorities.append({"title": f"Complete the {MODE_LABELS[mode].lower()} structure", "detail": f"Missing or weak: {missing or 'explicit structure'}.", "exercise": "Record a second version using the checklist in order."})
    if wpm > 175:
        priorities.append({"title": "Slow the decision points", "detail": f"Your estimated pace is {wpm:.0f} WPM.", "exercise": "Pause before the main claim, numbers, and requested action."})
    elif 0 < wpm < 105:
        priorities.append({"title": "Increase forward motion", "detail": f"Your estimated pace is {wpm:.0f} WPM.", "exercise": "Prepare three bullets, then deliver without searching for the next idea."})
    if not priorities:
        priorities.append({"title": "Add one sharper takeaway", "detail": "The mechanics are controlled. Make the final sentence unmistakable.", "exercise": "End with: ‘The one thing I want you to do is…’"})

    rewrite, selected = extractive_rewrite(sents)
    metrics = {
        "version": 1,
        "analyzed_at": dt.datetime.now().astimezone().isoformat(),
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "duration_seconds": round(duration, 2),
        "word_count": len(tokens),
        "sentence_count": len(sents),
        "words_per_minute": round(wpm, 1),
        "filler_count": filler_total,
        "fillers_per_minute": round(filler_rate, 2),
        "filler_breakdown": filler_counts,
        "average_sentence_words": round(avg_sentence_words, 1),
        "lexical_diversity": round(lexical_diversity, 3),
        "idea_density_per_minute": round(idea_density, 2),
        "repetition_ratio": round(repeat_ratio, 3),
        "long_sentence_count": len(long_sentences),
        "action_items": action_items,
        "questions": questions,
        "delivery": delivery,
        "scores": {"overall": overall, "clarity": clarity, "concision": concision, "delivery": delivery_score, "structure": structure},
        "structure_checklist": checklist,
        "priorities": priorities[:4],
        "repeated_passages": repeated,
        "strongest_sentences": selected,
        "improved_version": rewrite,
        "disclaimer": "Local heuristic coaching, not a clinical speech or pronunciation assessment.",
    }
    atomic_json(folder / "speech_metrics.json", metrics)
    (folder / "improved_version.md").write_text("# Tighter version\n\n" + rewrite + "\n")
    (folder / "speech_report.md").write_text(render_report(metrics))
    return metrics


def render_report(m: dict[str, Any]) -> str:
    scores = m["scores"]
    lines = [
        "# Personal speech-coaching report", "", f"**Mode:** {m['mode_label']}",
        f"**Overall:** {scores['overall']}/100", "", "## Scorecard", "",
        f"- Clarity: **{scores['clarity']}**", f"- Concision: **{scores['concision']}**",
        f"- Delivery: **{scores['delivery']}**", f"- Structure: **{scores['structure']}**", "",
        "## Measured signals", "", f"- Pace: {m['words_per_minute']} words/minute",
        f"- Fillers: {m['filler_count']} ({m['fillers_per_minute']}/minute)",
        f"- Idea density: {m['idea_density_per_minute']} substantive sentences/minute",
        f"- Repetition: {m['repetition_ratio']:.0%}",
        f"- Average sentence: {m['average_sentence_words']} words",
        f"- Pauses: {m['delivery']['pause_count']} ({m['delivery']['pause_rate']}/minute)", "",
        "## Coaching priorities", "",
    ]
    for item in m["priorities"]:
        lines += [f"### {item['title']}", item["detail"], "", f"**Exercise:** {item['exercise']}", ""]
    lines += ["## Structure checklist", ""]
    lines += [f"- {'✓' if item['present'] else '○'} {item['name']}" for item in m["structure_checklist"]]
    lines += ["", "## Tighter version", "", m["improved_version"], "", f"> {m['disclaimer']}", ""]
    return "\n".join(lines)


def analyze_all(recordings_root: Path) -> list[dict[str, Any]]:
    results = []
    for folder in sorted(recordings_root.iterdir()) if recordings_root.exists() else []:
        if folder.is_dir() and (folder / "transcript.txt").exists():
            try:
                results.append({"id": folder.name, "metrics": analyze_folder(folder)})
            except Exception as exc:
                results.append({"id": folder.name, "error": str(exc)})
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--mode", choices=list(MODE_LABELS))
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
    import paths
    root = paths.RECORDINGS_DIR
    result = analyze_all(root) if args.all else analyze_folder(args.folder, args.mode)
    print(json.dumps(result, indent=2))
