"""Whisper initial-prompt vocabulary and the learned-terms store."""
from __future__ import annotations

import json
import re
import time

import db
import paths
from .config import DEFAULT_KEYWORDS


_COMMON_WORDS = {
    "the", "a", "an", "and", "but", "or", "so", "if", "is", "it", "in", "on",
    "at", "to", "for", "of", "we", "i", "you", "he", "she", "they", "this",
    "that", "there", "here", "what", "when", "where", "why", "how", "yeah",
    "okay", "ok", "right", "well", "just", "like", "now", "then", "also",
    "not", "can", "will", "would", "should", "could", "have", "has", "had",
    "do", "does", "did", "are", "was", "were", "be", "been", "my", "your",
    "our", "their", "its", "let", "lets", "thanks", "thank", "hi", "hello",
}


_VOCAB_STOPWORDS = {
    "participant", "i'm", "i'll", "yes", "it's", "that's", "none", "none noted",
    "let's", "because", "we're", "to ek", "the", "and", "but", "so", "if", "is", "it",
    "that", "there", "this", "they", "them", "what", "when", "where", "why", "how",
    "yeah", "okay", "ok", "right", "well", "just", "like", "now", "then", "also", "not",
    "can", "will", "would", "should", "could", "have", "has", "had", "meeting",
    "transcripts", "recording", "recorded", "seconds", "minutes", "hours", "total",
    "discussion", "overview", "action", "items", "decisions", "timeline", "entities",
    "speaker", "speakers", "screen", "profile", "view", "channel"
}


def build_vocabulary_prompt(title: str = "", max_chars: int = 800) -> str:
    """Compose Whisper's initial_prompt from clean, curated domain entities & known people."""
    base_hint = DEFAULT_KEYWORDS.strip()
    seen: set[str] = set()
    entities: list[str] = []

    # 1. Curated vocabulary file
    # The user's own vocabulary (real names — lives in DATA_DIR, never in
    # the repo); a fresh install falls back to the generic example.
    curated_path = paths.VOCAB_PATH if paths.VOCAB_PATH.is_file() else paths.VOCAB_EXAMPLE
    if curated_path.is_file():
        try:
            curated_data = json.loads(curated_path.read_text())
            for cat in ["people", "clients_and_orgs", "products_and_projects", "technical_terms", "hinglish_phrases"]:
                for term in curated_data.get(cat, []):
                    k = term.strip().lower()
                    if k and k not in seen and k not in _VOCAB_STOPWORDS:
                        seen.add(k)
                        entities.append(term.strip())
        except Exception:
            pass

    # 2. Known real people from DB
    for person in db.get_all_people():
        name = (person.get("name") or "").strip()
        k = name.lower()
        if k and k not in seen and k not in _VOCAB_STOPWORDS and len(name) >= 3:
            seen.add(k)
            entities.append(name)

    # 3. Dynamic terms matching the meeting title
    if title and not re.match(r"^(?:meeting|recording|no speech|\d{4}-\d{2}-\d{2})", title, re.I):
        title_words = [w for w in re.findall(r"[A-Za-z]{3,}", title) if w.lower() not in _COMMON_WORDS and w.lower() not in _VOCAB_STOPWORDS]
        for row in db.search_vocabulary_terms(title_words, limit=8):
            term = row["term"].strip()
            k = term.lower()
            if k and k not in seen and k not in _VOCAB_STOPWORDS and len(term) >= 3 and ":" not in term:
                seen.add(k)
                entities.append(term)

    entities_str = ", ".join(entities[:35])
    if entities_str:
        prompt = f"{base_hint} Entities: {entities_str}." if base_hint else f"Entities: {entities_str}."
    else:
        prompt = base_hint or "Transcribe Indian English and Hindi Hinglish."

    return prompt[:max_chars]


def learn_from_transcript(text: str, source: str = "auto") -> None:
    """Grow the vocabulary store from a finished transcript."""
    tokens = re.findall(r"\b[A-Z][a-zA-Z'-]{2,}\b", text)
    counts: dict[str, int] = {}
    for token in tokens:
        t_low = token.lower()
        if t_low in _COMMON_WORDS or t_low in _VOCAB_STOPWORDS or len(token) < 3:
            continue
        counts[token] = counts.get(token, 0) + 1
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    for term, count in counts.items():
        if count >= 2:
            db.upsert_vocabulary_term(term, source, now_iso)
