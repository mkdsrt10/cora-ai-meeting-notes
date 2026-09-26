"""Meeting context for Whisper's initial prompt.

Whisper spells names, products and jargon far better when its prompt
already contains them. This gathers everything Cora knows about a meeting
and turns it into a short, prose-like prompt per transcription chunk:

  source (priority)          where it comes from
  -------------------------  ---------------------------------------------
  attendees       1.00       participants.json (+ renames), your own name
  nearby_ocr      0.95       screenshot text captured within ±2 min of the chunk
  title           0.90       meeting title
  notes           0.80       notes you typed for this meeting
  ocr             0.60       screenshot text from elsewhere in the meeting
  past_meetings   0.50       keywords of earlier meetings with the same people
                             or a similar title
  curated         0.40       curated domain vocabulary (your data dir, or the example)
  learned         0.30       vocabulary learned from past transcripts

Terms found in more than one source get a boost. Terms are packed into the
prompt by score until the token budget is used (Whisper only keeps the last
~224 prompt tokens, so this stays under it with room to spare).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import db
import paths
from participants import clean_and_validate_participant

from .config import DEFAULT_KEYWORDS
from .vocabulary import _COMMON_WORDS, _VOCAB_STOPWORDS

PROMPT_TOKEN_BUDGET = 200
NEARBY_OCR_WINDOW_S = 120.0
MAX_TERMS_PER_SCREENSHOT = 12

WEIGHTS = {
    "attendees": 1.00, "nearby_ocr": 0.95, "title": 0.90, "notes": 0.80, "ocr": 0.60,
    "past_meetings": 0.50, "curated": 0.40, "learned": 0.30,
}
MULTI_SOURCE_BOOST = 0.10

_ISO_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})(?:-(\d{3}))?Z")
_RAW_TITLE = re.compile(r"^(?:meeting|recording|no speech|untitled|\d{4}-\d{2}-\d{2})", re.I)
_TERM = re.compile(
    r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}"      # multi-word proper names: "Google Meet"
    r"|[A-Za-z]+-?\d+(?:\.\d+)*[A-Za-z]*"          # alphanumerics: Q3, GPT-4, v2.1
    r"|[A-Z][a-z]*[A-Z]\w*"                        # CamelCase: OpenAI, iPhone-like
    r"|[A-Z]{2,6}s?"                               # acronyms: API, OKRs
    r"|[A-Z][a-z]{2,})\b"                          # Capitalised words
)
_UI_NOISE = {"file", "edit", "view", "window", "help", "share", "mute", "unmute", "chat", "reactions",
             "participants", "leave", "end", "record", "recording", "more", "apps", "settings", "zoom",
             "meeting", "search", "home", "new", "open", "close", "save", "copy", "paste", "today",
             "yesterday", "tomorrow", "monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "january", "february", "march", "april", "may", "june", "july",
             "august", "september", "october", "november", "december", "the", "this", "that"}


@dataclass
class Term:
    text: str
    score: float
    sources: set[str] = field(default_factory=set)
    at: Optional[float] = None  # seconds into the recording, for screenshot terms


@dataclass
class MeetingContext:
    title: str = ""
    attendees: list[str] = field(default_factory=list)
    terms: dict[str, Term] = field(default_factory=dict)      # untimed, keyed by lowercase
    timed: list[Term] = field(default_factory=list)           # screenshot terms with a time
    base_hint: str = ""
    prompts: list[dict[str, Any]] = field(default_factory=list)

    # ---- building ---------------------------------------------------------
    def add(self, text: str, source: str, weight: Optional[float] = None) -> None:
        text = _clean(text)
        if not text:
            return
        key = text.lower()
        score = WEIGHTS[source] if weight is None else weight
        term = self.terms.get(key)
        if term is None:
            self.terms[key] = Term(text, score, {source})
        else:
            if source not in term.sources:
                term.sources.add(source)
                term.score = max(term.score, score) + MULTI_SOURCE_BOOST
            else:
                term.score = max(term.score, score)

    # ---- using -------------------------------------------------------------
    def prompt(self, start: Optional[float] = None, end: Optional[float] = None,
               budget: int = PROMPT_TOKEN_BUDGET) -> str:
        """Prompt for the audio between start and end (seconds; None = whole meeting)."""
        nearby: dict[str, Term] = {}
        if start is not None:
            mid = (start + (end if end is not None else start)) / 2
            for term in self.timed:
                if term.at is not None and abs(term.at - mid) <= NEARBY_OCR_WINDOW_S:
                    nearby.setdefault(term.text.lower(), term)
        head = [self.base_hint.strip()] if self.base_hint.strip() else []
        if self.title:
            head.append(f"Meeting: {self.title}.")
        attendee_keys = {a.lower() for a in self.attendees}
        if self.attendees:
            head.append("Attendees: " + ", ".join(self.attendees) + ".")
        ranked = sorted(
            [Term(t.text, WEIGHTS["nearby_ocr"] + (0.1 if k in self.terms else 0), {"nearby_ocr"}) for k, t in nearby.items()]
            + list(self.terms.values()),
            key=lambda t: -t.score,
        )
        used = set(attendee_keys) | {self.title.lower()}
        chosen: list[str] = []
        text = " ".join(head)
        for term in ranked:
            key = term.text.lower()
            if key in used:
                continue
            candidate = " ".join(head + ["Terms: " + ", ".join(chosen + [term.text]) + "."])
            if count_tokens(candidate) > budget:
                continue
            chosen.append(term.text)
            used.add(key)
            text = candidate
        if count_tokens(text) > budget:  # head alone too long (huge roster/hint): trim by words
            words = text.split()
            while words and count_tokens(" ".join(words)) > budget:
                words.pop()
            text = " ".join(words)
        return text

    def record(self, start: float, end: float, prompt: str) -> None:
        self.prompts.append({"start": round(start, 2), "end": round(end, 2), "prompt": prompt})

    def summary(self) -> dict[str, Any]:
        top = sorted(self.terms.values(), key=lambda t: -t.score)[:60]
        return {
            "title": self.title,
            "attendees": self.attendees,
            "base_hint": self.base_hint,
            "top_terms": [{"term": t.text, "score": round(t.score, 2), "sources": sorted(t.sources)} for t in top],
            "screenshot_terms": [{"term": t.text, "at": t.at} for t in self.timed],
            "chunk_prompts": self.prompts,
        }

    def save(self, folder: Path) -> None:
        (folder / "transcription_context.json").write_text(json.dumps(self.summary(), indent=2, ensure_ascii=False) + "\n")


# ---- helpers ------------------------------------------------------------------

@lru_cache(maxsize=1)
def _tokenizer():
    try:
        from mlx_whisper.tokenizer import get_tokenizer
        return get_tokenizer(multilingual=True)
    except Exception:
        return None


def count_tokens(text: str) -> int:
    tok = _tokenizer()
    if tok is None:
        return max(1, len(text) // 3)  # conservative fallback
    return len(tok.encode(" " + text))


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip(" .,:;!?\"'()[]{}-")
    if len(text) < 2 or len(text) > 60 or text.isdigit():
        return ""
    low = text.lower()
    if low in _COMMON_WORDS or low in _VOCAB_STOPWORDS or low in _UI_NOISE:
        return ""
    return text


def extract_terms(text: str, limit: Optional[int] = None) -> list[str]:
    """Proper nouns, acronyms, product names and codes — the words Whisper
    tends to misspell — from free text (notes, OCR). Sentence-initial
    capitals are ignored unless the word recurs or is capitalised mid-sentence."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for sentence in re.split(r"(?<=[.!?\n])\s+", text or ""):
        for i, match in enumerate(_TERM.finditer(sentence)):
            term = _clean(match.group(0))
            if not term:
                continue
            first_word = match.start() == len(sentence) - len(sentence.lstrip())
            simple_cap = re.fullmatch(r"[A-Z][a-z]+", term) is not None
            key = term.lower()
            if key not in counts:
                order.append(term)
            counts[key] = counts.get(key, 0) + (0 if (first_word and simple_cap and i == 0) else 1)
    terms = [t for t in order if counts[t.lower()] > 0]
    terms.sort(key=lambda t: -counts[t.lower()])
    return terms[:limit] if limit else terms


def _recording_start(folder: Path) -> Optional[dt.datetime]:
    m = _ISO_IN_NAME.search(folder.name)
    if not m:
        return None
    base = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").replace(tzinfo=dt.timezone.utc)
    return base + dt.timedelta(milliseconds=int(m.group(2) or 0))


def _screenshot_texts(folder: Path) -> Iterable[tuple[Optional[float], str]]:
    """(seconds into the recording or None, OCR text) from every place screenshots land."""
    start = _recording_start(folder)
    seen: set[str] = set()
    shots = folder / "screenshots"
    for txt in sorted(shots.glob("*.txt")) if shots.is_dir() else []:
        text = txt.read_text(errors="replace")
        m = _ISO_IN_NAME.search(txt.name)
        at = None
        if m and start:
            taken = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H-%M-%S").replace(tzinfo=dt.timezone.utc)
            taken += dt.timedelta(milliseconds=int(m.group(2) or 0))
            at = max(0.0, (taken - start).total_seconds())
        seen.add(text.strip())
        yield at, text
    try:
        slides = json.loads((folder / "slides_ocr.json").read_text())
    except (OSError, ValueError):
        slides = []
    for entry in slides if isinstance(slides, list) else []:
        text = str(entry.get("text") or "")
        if text.strip() and text.strip() not in seen:
            seen.add(text.strip())
            yield entry.get("timestamp_seconds"), text
    for entry in db.get_live_transcript_entries(folder.name):
        text = str(entry.get("text") or "")
        if entry.get("type") == "screenshot" and text.strip() and text.strip() not in seen:
            seen.add(text.strip())
            yield entry.get("start_seconds"), text


def _attendees(folder: Path, recording_id: str) -> list[str]:
    try:
        raw = json.loads((folder / "participants.json").read_text())
    except (OSError, ValueError):
        raw = []
    overrides = (db.get_recording_data(recording_id, "metadata") or {}).get("participant_overrides") or {}
    names: list[str] = []
    for name in raw if isinstance(raw, list) else []:
        clean = clean_and_validate_participant(str(name))
        if not clean:
            continue
        override = overrides.get(name) or overrides.get(clean) or {}
        if override.get("hidden"):
            continue
        display = override.get("display_name") or clean
        if display.lower() not in {n.lower() for n in names}:
            names.append(display)
    self_name = db.get_setting("pending_self_name") or (db.get_person(db.get_self_person_id() or "") or {}).get("name")
    if self_name and not any(self_name.lower().split()[0] in n.lower() for n in names):
        names.append(self_name)
    return names


def _past_meeting_keywords(recording_id: str, attendees: list[str], title: str, limit: int = 12) -> list[tuple[str, float]]:
    """Keywords from earlier meetings that share people or title words, weighted by overlap."""
    people = {a.lower() for a in attendees}
    title_words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)} - _COMMON_WORDS
    scored: dict[str, float] = {}
    for row in db.get_all_recordings():
        if row.get("id") == recording_id:
            continue
        folder = Path(row.get("folder_path") or "")
        try:
            their_people = {str(p).lower() for p in json.loads((folder / "participants.json").read_text())}
        except (OSError, ValueError, TypeError):
            their_people = set()
        their_title = str((row.get("metadata") or {}).get("recording_name") or row.get("title") or "")
        overlap = len(people & their_people) + len(title_words & {w.lower() for w in re.findall(r"[A-Za-z]{4,}", their_title)})
        if not overlap:
            continue
        summary = row.get("call_summary") or {}
        for kw in summary.get("keywords") or []:
            key = _clean(kw)
            if key:
                scored[key] = scored.get(key, 0.0) + overlap
    top = sorted(scored.items(), key=lambda kv: -kv[1])[:limit]
    if not top:
        return []
    best = top[0][1]
    return [(term, WEIGHTS["past_meetings"] * (0.6 + 0.4 * score / best)) for term, score in top]


def _curated_terms() -> list[str]:
    source = paths.VOCAB_PATH if paths.VOCAB_PATH.is_file() else paths.VOCAB_EXAMPLE
    try:
        data = json.loads(source.read_text())
    except (OSError, ValueError):
        return []
    return [t for cat, items in data.items() if isinstance(items, list) for t in items]


def build_context(folder: Path, title: str = "") -> MeetingContext:
    """Everything known about this meeting, ranked for Whisper's prompt."""
    recording_id = folder.name
    from .romanize import ROMAN_PRIMER, target_script
    # A Romanized Hinglish sample nudges the ASR to write Hindi in Latin script.
    hint = " ".join(h for h in (ROMAN_PRIMER if target_script() == "roman" else "", DEFAULT_KEYWORDS or "") if h)
    ctx = MeetingContext(base_hint=hint)
    ctx.title = title if title and not _RAW_TITLE.match(title) else ""
    ctx.attendees = _attendees(folder, recording_id)
    for name in ctx.attendees:
        ctx.add(name, "attendees")
        first = name.split()[0]
        if len(first) >= 3:
            ctx.add(first, "attendees", WEIGHTS["attendees"] - 0.05)
    for term in extract_terms(ctx.title):
        ctx.add(term, "title")
    for term in extract_terms(db.get_notes(recording_id) or "", limit=30):
        ctx.add(term, "notes")
    for at, text in _screenshot_texts(folder):
        for term in extract_terms(text, limit=MAX_TERMS_PER_SCREENSHOT):
            ctx.add(term, "ocr")
            if at is not None:
                ctx.timed.append(Term(term, WEIGHTS["nearby_ocr"], {"nearby_ocr"}, at))
    for term, weight in _past_meeting_keywords(recording_id, ctx.attendees, title):
        ctx.add(term, "past_meetings", weight)
    for row in db.get_vocabulary_terms(40):
        ctx.add(row.get("term", ""), "learned", WEIGHTS["learned"] * min(1.0, 0.5 + (row.get("weight") or 1) / 20))
    for term in _curated_terms():
        ctx.add(term, "curated")
    return ctx
