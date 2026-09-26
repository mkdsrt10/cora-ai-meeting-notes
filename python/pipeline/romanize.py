"""Romanized Hinglish transcripts: Devanagari -> Latin script.

Tara (and other Hinglish Whisper fine-tunes) write Hindi words in Devanagari
some of the time even when told to transcribe English. Cora's transcripts,
search, speaker naming and training data use Romanized Hinglish ("theek hai,
main kal bhej dunga"), so turns containing Devanagari are converted:

1. A local LLM rewrites them, which also restores English words the model
   spelled phonetically in Devanagari (समराइजेशन -> "summarization").
2. Every LLM line is validated (no Devanagari left, plausible length versus
   the rule-based version, nothing added); failures fall back to
3. a rule-based transliterator with Hindi schwa deletion — also used alone
   when the LLM pass is disabled or unavailable.

The original text is kept on the segment (`text_native`) as training data.
Config (config.json): "transcript_script": "roman" (default) or "native".
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

import paths

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
BATCH_CHARS = 1500
PROMPT_ID = "romanize.v1"

INSTRUCTION = """Rewrite each numbered line of this meeting transcript in Romanized Hinglish (Latin script only).
- Hindi words: write them the way Indians type Hinglish (e.g. "theek hai", "kya kar rahe ho", "matlab").
- English words written in Devanagari: restore the normal English spelling (e.g. "समराइजेशन" -> "summarization").
- Keep names, numbers and word order. Do not translate to English, do not summarize, do not add anything.
- Lines already in Latin script: copy them unchanged.
Output exactly the same numbering, one line each, like: [3] text

{lines}"""

# ---- rule-based transliteration ------------------------------------------------

_VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
           "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
_MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o",
           "ौ": "au", "ॉ": "o", "ॅ": "e"}
_CONSONANTS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
               "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
               "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
               "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l"}
_NUKTA = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "r", "ढ": "rh", "फ": "f", "य": "y"}
_PRECOMPOSED_NUKTA = {"क़": "क", "ख़": "ख", "ग़": "ग", "ज़": "ज", "ड़": "ड", "ढ़": "ढ", "फ़": "फ", "य़": "य"}
_OTHER = {"ं": "n", "ँ": "n", "ः": "h", "।": ".", "॥": ".", "ॐ": "om"}
_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
VIRAMA, NUKTA = "्", "़"


def _word_units(word: str) -> list[list[str]]:
    """Syllable-ish units: [consonant_roman, vowel_roman, kind] for each akshara."""
    for composed, base in _PRECOMPOSED_NUKTA.items():
        word = word.replace(composed, base + NUKTA)
    units: list[list[str]] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in _CONSONANTS:
            roman = _CONSONANTS[ch]
            if i + 1 < len(word) and word[i + 1] == NUKTA:
                roman = _NUKTA.get(ch, roman)
                i += 1
            vowel, kind = "a", "inherent"
            if i + 1 < len(word) and word[i + 1] in _MATRAS:
                vowel, kind = _MATRAS[word[i + 1]], "matra"
                i += 1
            elif i + 1 < len(word) and word[i + 1] == VIRAMA:
                vowel, kind = "", "virama"
                i += 1
            units.append([roman, vowel, kind])
        elif ch in _VOWELS:
            units.append(["", _VOWELS[ch], "vowel"])
        elif ch in _OTHER or ch in _DIGITS:
            units.append([_OTHER.get(ch) or _DIGITS[ch], "", "sign"])
        elif ch == NUKTA:
            pass
        else:
            units.append([ch, "", "sign"])
        i += 1
    return units


def _delete_schwas(units: list[list[str]]) -> None:
    """Hindi schwa deletion: drop the word-final inherent 'a', and a medial
    one in the pattern V C[a] C V (e.g. समझना -> samajhna, not samajhana)."""
    letters = [u for u in units if u[2] != "sign"]
    if not letters:
        return
    if len(letters) > 1 and letters[-1][2] == "inherent":
        letters[-1][1] = ""
    for k in range(len(letters) - 2, 0, -1):
        cur, prev, nxt = letters[k], letters[k - 1], letters[k + 1]
        if (cur[2] == "inherent" and prev[1] and prev[2] != "virama" and nxt[0] and nxt[1]):
            cur[1] = ""
            break


def transliterate(text: str) -> str:
    """Casual Hinglish romanization of any Devanagari in `text`."""
    def word(match: re.Match) -> str:
        units = _word_units(match.group(0))
        _delete_schwas(units)
        out = "".join(c + v for c, v, _ in units)
        out = re.sub(r"(.)\1{2,}", r"\1\1", out)
        # Casual Hinglish spelling: final long vowels are written short
        # (kya, karna, doonga, priya; nahin) except in tiny words (aa, haan).
        if len(out) > 3:
            out = re.sub(r"aa$", "a", out)
            out = re.sub(r"een$", "in", out)
        return out
    return re.sub(r"[ऀ-ॿ]+", word, text)


# ---- orchestration --------------------------------------------------------------

def target_script() -> str:
    try:
        return json.loads(paths.CONFIG_PATH.read_text()).get("transcript_script", "roman")
    except (OSError, ValueError):
        return "roman"


def _valid(candidate: str, reference: str) -> bool:
    if not candidate or DEVANAGARI.search(candidate):
        return False
    ratio = len(candidate) / max(len(reference), 1)
    return 0.5 <= ratio <= 2.2


def romanize_segments(segments: list[dict[str, Any]], generate: Optional[Callable[[str], str]] = None) -> dict[str, int]:
    """Convert Devanagari in segment texts in place. Returns counts for logging."""
    todo = [i for i, s in enumerate(segments) if DEVANAGARI.search(s.get("text", ""))]
    stats = {"segments": len(todo), "llm": 0, "rules": 0}
    if not todo or target_script() != "roman":
        return stats
    llm_out: dict[int, str] = {}
    if generate is not None:
        batch: list[int] = []
        size = 0
        for i in todo + [None]:
            text = segments[i]["text"] if i is not None else ""
            if batch and (i is None or size + len(text) > BATCH_CHARS):
                prompt = INSTRUCTION.format(lines="\n".join(f"[{j}] {segments[j]['text']}" for j in batch))
                try:
                    reply = generate(prompt) or ""
                except Exception:
                    reply = ""
                for m in re.finditer(r"^\s*\[(\d+)\]\s*(.+?)\s*$", re.sub(r"<think>.*?</think>", "", reply, flags=re.S), re.M):
                    j = int(m.group(1))
                    if j in batch:
                        llm_out[j] = m.group(2)
                batch, size = [], 0
            if i is not None:
                batch.append(i)
                size += len(text)
    for i in todo:
        seg = segments[i]
        rules = transliterate(seg["text"])
        candidate = llm_out.get(i, "")
        seg.setdefault("text_native", seg["text"])
        if _valid(candidate, rules):
            seg["text"] = candidate
            seg["text_script_method"] = "llm"
            stats["llm"] += 1
        else:
            seg["text"] = rules
            seg["text_script_method"] = "rules"
            stats["rules"] += 1
    return stats


ROMAN_PRIMER = "Haan, theek hai, main kal tak bhej dunga. Okay, let's continue."
