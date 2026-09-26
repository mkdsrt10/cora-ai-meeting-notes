"""Name the "Participant" turns that audio alone can't attribute.

The mic/system-track comparison only says *you* vs. *someone on the call*;
the Accessibility active-speaker timeline often has gaps. When the roster
has several other people, those remote turns stay a generic "Participant".
This fills them in from the conversation itself, in two passes:

1. Rules (no model): self-introductions in the turn ("this is Rahul",
   "Priya here") and hand-offs in the turn before it ("over to you, Priya",
   "thanks Rahul", "Rahul, what do you think?").
2. A small local LLM for what's left, given the roster, the title and the
   numbered turns, returning a name, confidence and verbatim evidence per turn.

Every guess is validated — name must be on the roster, evidence must appear
verbatim in the transcript, and a turn the mic says is yours is never
reassigned — and only guesses at or above MIN_CONFIDENCE replace the label.
The original label is always kept (original_speaker_id) and every guess,
applied or not, is stored on the segment as speaker_guess, so it can be
reviewed, corrected in the transcript editor, and used as training data.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

UNRESOLVED = "Participant"
MIN_CONFIDENCE = 0.6
LLM_WINDOW_CHARS = 6000
PROMPT_ID = "speaker_guess.v2"

INSTRUCTION = """You identify who is speaking in a meeting transcript.
Participants on the call (other than ME): {roster}.
Meeting title: {title}

Turns marked ME were spoken by the user; turns marked with a name were spoken by that person. Turns marked ??? were spoken by one of the other participants, but we don't know which.
For every ??? turn, decide who most likely said it using conversational evidence only: someone being addressed by name in the turn before, a self-introduction, someone answering a question directed at them, or references to their own role or work.
If there is no real evidence, answer "unknown". Do not guess from the order of the list.

Reply with JSON only, a list like:
[{{"turn": 12, "speaker": "<exact name from the list or unknown>", "confidence": 0.0-1.0, "evidence": "<exact quote, at most 8 words>"}}]
Keep evidence short — at most 8 words copied exactly from the transcript.

TRANSCRIPT:
{turns}"""

_INTRO = re.compile(r"\b(?:this is|i am|i'm|it's|myself|my name is)\s+([A-Z][\w'-]+)", re.I)
_HERE = re.compile(r"\b([A-Z][\w'-]+)\s+here\b")
_HANDOFF_PATTERNS = (
    r"(?:over to you|go ahead|your turn|you're up|take it away)[,\s]+{name}\b",
    r"\b{name}[,\s]+(?:what do you think|what are your thoughts|can you|could you|do you|would you|any thoughts|go ahead)",
    r"\b(?:thanks|thank you|thanks a lot)[,\s]+{name}\b",
    r"\b{name}\s*\?\s*$",
)


def other_participants(roster: list[str], self_name: Optional[str]) -> list[str]:
    self_tokens = set((self_name or "").lower().split())
    return [p for p in roster if p and not (self_tokens & set(p.lower().split()))]


def _match_name(token: str, others: list[str]) -> Optional[str]:
    token = token.lower().strip(".,!?")
    matches = [p for p in others if token in {w.lower() for w in p.split()}]
    return matches[0] if len(matches) == 1 else None


def _rule_guess(segments: list[dict[str, Any]], i: int, others: list[str]) -> Optional[dict[str, Any]]:
    text = segments[i].get("text", "")
    for pattern in (_INTRO, _HERE):
        for m in pattern.finditer(text):
            name = _match_name(m.group(1), others)
            if name:
                return {"name": name, "confidence": 0.9, "evidence": m.group(0), "method": "rule_self_intro"}
    if i > 0 and segments[i - 1].get("speaker_id") != UNRESOLVED:
        prev = segments[i - 1].get("text", "")
        for person in others:
            for token in {person, person.split()[0]}:
                for pattern in _HANDOFF_PATTERNS:
                    m = re.search(pattern.format(name=re.escape(token)), prev, re.I)
                    if m:
                        return {"name": person, "confidence": 0.75, "evidence": m.group(0), "method": "rule_handoff"}
    return None


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def _windows(segments: list[dict[str, Any]], unresolved: list[int]) -> list[list[int]]:
    """Groups of segment indices, each under LLM_WINDOW_CHARS, that together
    cover every unresolved turn with some surrounding context."""
    windows, current, size = [], [], 0
    for i, seg in enumerate(segments):
        line = len(seg.get("text", "")) + 20
        if current and size + line > LLM_WINDOW_CHARS:
            windows.append(current)
            current, size = current[-3:], sum(len(segments[j].get("text", "")) + 20 for j in current[-3:])
        current.append(i)
        size += line
    if current:
        windows.append(current)
    wanted = set(unresolved)
    return [w for w in windows if wanted & set(w)]


def parse_guess_list(raw: str, json_repair: Any) -> list[Any]:
    """The JSON list from the model, tolerating output cut off at the token
    limit (no closing bracket): complete objects are recovered, the
    truncated tail is dropped."""
    start = raw.find("[")
    if start < 0:
        return []
    end = raw.rfind("]")
    body = raw[start: end + 1] if end > start else raw[start:]
    try:
        parsed = json_repair.loads(body)
        if isinstance(parsed, list) and (end > start or len(parsed) > 1):
            return parsed[:-1] if end <= start else parsed  # last item of a cut-off list may be partial
    except Exception:
        pass
    items = []
    for match in re.finditer(r"\{[^{}]*\}", body):
        try:
            items.append(json_repair.loads(match.group(0)))
        except Exception:
            continue
    return items


def _label(seg: dict[str, Any], self_ids: set[str]) -> str:
    sid = seg.get("speaker_id") or ""
    if sid == UNRESOLVED:
        return "???"
    return "ME" if sid in self_ids else (seg.get("speaker_name") or sid)


def _llm_guesses(segments, unresolved, others, title, generate, self_ids) -> dict[int, dict[str, Any]]:
    import json_repair

    corpus = _normalise(" ".join(s.get("text", "") for s in segments))
    results: dict[int, dict[str, Any]] = {}
    for window in _windows(segments, unresolved):
        turns = "\n".join(
            f"[{i}] {_label(segments[i], self_ids)}: {segments[i].get('text', '')}"
            for i in window
        )
        prompt = INSTRUCTION.format(roster=", ".join(others), title=title or "(none)", turns=turns)
        raw = generate(prompt)
        raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.S)
        for item in parse_guess_list(raw, json_repair):
            if not isinstance(item, dict):
                continue
            try:
                turn = int(item.get("turn"))
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            name = str(item.get("speaker", "")).strip()
            evidence = str(item.get("evidence", "")).strip()
            if turn not in unresolved or turn not in window or name not in others:
                continue
            if not evidence or _normalise(evidence) not in corpus:
                confidence = min(confidence, 0.4)  # unverifiable evidence: keep as a hint only
            best = results.get(turn)
            if best is None or confidence > best["confidence"]:
                results[turn] = {"name": name, "confidence": round(confidence, 2), "evidence": evidence[:200],
                                 "method": "llm"}
    return results


def guess_speakers(segments: list[dict[str, Any]], roster: list[str], self_name: Optional[str], title: str,
                   generate: Optional[Callable[[str], str]] = None, model_id: str = "") -> dict[str, int]:
    """Mutates `segments` in place. `generate(prompt) -> str` runs the LLM
    (omit for rules only). Returns counts for logging."""
    others = other_participants(roster, self_name)
    unresolved = [i for i, s in enumerate(segments) if s.get("speaker_id") == UNRESOLVED]
    stats = {"unresolved": len(unresolved), "rule": 0, "llm": 0, "kept_generic": 0}
    if not unresolved or not others:
        stats["kept_generic"] = len(unresolved)
        return stats

    guesses: dict[int, dict[str, Any]] = {}
    for i in unresolved:
        guess = _rule_guess(segments, i, others)
        if guess:
            guesses[i] = guess
    remaining = [i for i in unresolved if i not in guesses]
    if remaining and generate is not None:
        self_ids = {"You", self_name or "You"}
        guesses.update({i: g for i, g in _llm_guesses(segments, remaining, others, title, generate, self_ids).items()
                        if i not in guesses})

    for i in unresolved:
        guess = guesses.get(i)
        seg = segments[i]
        if not guess:
            stats["kept_generic"] += 1
            continue
        seg["speaker_guess"] = {**guess, "model": model_id if guess["method"] == "llm" else None,
                                "prompt_id": PROMPT_ID if guess["method"] == "llm" else None}
        if guess["confidence"] >= MIN_CONFIDENCE:
            seg["original_speaker_id"] = seg.get("speaker_id")
            seg["speaker_id"] = seg["speaker_name"] = guess["name"]
            seg["speaker_source"] = "llm_guess" if guess["method"] == "llm" else "rule_guess"
            seg["speaker_confidence"] = guess["confidence"]
            stats["llm" if guess["method"] == "llm" else "rule"] += 1
        else:
            stats["kept_generic"] += 1
    return stats
