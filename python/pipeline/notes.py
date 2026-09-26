"""Enhanced notes and summary variants (local MLX or a configured cloud LLM)."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

import db
from .common import _slug, _write_progress, format_ts
from .config import LOCAL_LLM_MODEL_DEFAULT, _clear_mlx_cache, _release_mlx_model
from .llm import _chunk_transcript, _last_llm_stats, _llm_extract, traced_generate
from .vocabulary import _COMMON_WORDS


SUMMARY_FORMATS = {
    "executive": {
        "label": "Executive Summary",
        "instructions": "Write a 2-4 sentence high-level synopsis for a busy executive who did not attend. Prose, no bullet points, no jargon.",
    },
    "detailed_minutes": {
        "label": "Detailed Minutes",
        "instructions": "Write structured minutes: topics discussed with sub-bullets, in chronological order, thorough enough that someone could skip the meeting and rely on this instead.",
    },
    "action_items_only": {
        "label": "Action Items Only",
        "instructions": "Output ONLY a checklist of action items, one per line as \"- [ ] action (owner, due date if mentioned)\". Nothing else — no preamble, no summary.",
    },
    "client_one_pager": {
        "label": "Client-Facing One-Pager",
        "instructions": "Write a polished, external-facing summary suitable to send to a client: professional tone, no internal jargon or internal-only names/systems, focused on value delivered and next steps.",
    },
}


def generate_summary_variant(transcript_text: str, notes_text: str, slides_data: list[dict[str, Any]], format_name: str) -> dict[str, Any]:
    """Generate one named summary format from the transcript + the user's own
    notes (typed during or after the meeting) + slide OCR. Notes are included
    deliberately: they're at least as good a signal of what mattered in the
    meeting as the transcript is — arguably better, since the user chose to
    write them down — matching the "raw notes + transcript -> structured
    notes" idea this whole feature is built around, not just biasing
    transcription vocabulary."""
    import mlx_lm

    fmt = SUMMARY_FORMATS.get(format_name)
    if not fmt:
        raise ValueError(f"Unknown summary format: {format_name}")

    liquid_model = db.get_setting("liquid_model", LOCAL_LLM_MODEL_DEFAULT)
    model, tokenizer = mlx_lm.load(liquid_model)

    slides_summary = ""
    if slides_data:
        slides_summary = "\n--- SLIDES & SCREENSHOTS OCR DATA ---\n"
        for s in slides_data[:6]:
            slides_summary += f"[{s.get('timestamp')}] {s.get('text', '')[:300]}\n"
    notes_block = f"\n--- USER'S OWN NOTES ---\n{notes_text[:4000]}\n" if notes_text.strip() else ""

    prompt_content = f"""<|im_start|>system
You are an executive chief of staff producing one specific summary format of a meeting.
{fmt['instructions']}
Base this on the transcript, the user's own notes (if present — these reflect what the user personally found important), and any slide text.
<|im_end|>
<|im_start|>user
TRANSCRIPT:
{transcript_text[:12000]}
{notes_block}
{slides_summary}
<|im_end|>
<|im_start|>assistant
"""
    t0 = time.time()
    raw_output = traced_generate(model, tokenizer, prompt_content, max_tokens=600, model_id=liquid_model,
                                 name=f"summary_variant.{format_name}", prompt_template=fmt["instructions"])
    gen_seconds = time.time() - t0
    print(f"[Local LLM] {fmt['label']} generated in {gen_seconds:.1f}s", flush=True)

    try:
        output_tokens = len(tokenizer.encode(raw_output))
    except Exception:
        output_tokens = None
    _last_llm_stats.clear()
    _last_llm_stats.update({
        "model": liquid_model,
        "generation_seconds": round(gen_seconds, 2),
        "output_tokens": output_tokens,
        "tokens_per_second": round(output_tokens / gen_seconds, 1) if output_tokens and gen_seconds > 0 else None,
    })

    cleaned_text = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL)
    cleaned_text = re.sub(r"<\|im_end\|>", "", cleaned_text).strip()

    result = {
        "format": format_name,
        "label": fmt["label"],
        "text": cleaned_text,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": liquid_model,
    }
    _release_mlx_model(model, tokenizer)
    return result


def _markdown_bullets(text: str) -> list[str]:
    """Bullet lines ("- item") from a Markdown section, empty for the
    "- None noted." sentinel."""
    items = [line.strip("- ").strip() for line in text.splitlines() if line.strip().startswith("-")]
    return [i for i in items if i and i.lower() not in {"none noted.", "none noted"}]


def _clean_keyword(bullet: str) -> str:
    """Reduce one Key Entities bullet down to just the term. The model is
    told "just the name, nothing else" but doesn't reliably comply — it
    routinely appends a fabricated description after an em/en-dash or
    colon anyway (e.g. "Research App – Core product for data collection
    and analysis"), which would otherwise end up verbatim in the
    keywords list feeding both the key-phrases chips and the vocabulary
    prompt — neither wants a full sentence where a short term belongs."""
    term = re.sub(r"\*\*(.+?)\*\*", r"\1", bullet)  # strip markdown bold
    term = re.split(r"\s+[–—-]\s+|:\s+", term, maxsplit=1)[0]
    return term.strip()


# Generic (English + Hinglish) linguistic markers of a spoken commitment —
# not tied to any specific meeting's content, unlike a deterministic
# post-filter keyed on that meeting's own topic words would be (see
# _reconcile_decisions below for why that distinction matters). Used to
# pre-filter which turns actually get sent to the Action Items call, so a
# small model sees a denser, more relevant slice instead of hunting for a
# handful of real commitments buried in an hour of discussion.
_COMMITMENT_PATTERN = re.compile(
    r"\b(i will|i'll|let me|i can|i need to|i have to|make sure (you|i)|can you|"
    r"please (send|share|demo|forward)|i want you to|share the|follow up|connect with|sync with|"
    r"by (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|eod|end of day)|"
    r"bhej dungi|bhej dunga|kar dungi|kar dunga|dekh leta|dekh lungi|dekh lunga|bhej de|"
    r"forward kar|mangwa le|karungi|karunga|karenge|kar denge)\b",
    re.IGNORECASE,
)


def _mine_commitment_turns(aligned_segments: list[dict[str, Any]], min_turns: int = 3) -> str:
    """Pre-filter transcript turns down to the ones that sound like an
    actual commitment ("I'll send...", "bhej dungi...") before the Action
    Items LLM call ever runs — a deterministic, zero-cost narrowing pass
    rather than asking the model to find a few real commitments inside a
    much longer transcript. Falls back to an empty string (caller uses the
    full transcript instead) when fewer than min_turns turns match, since a
    handful of matches isn't a reliable enough signal to trust alone —
    better to give the model full context than an unreliably tiny slice.
    """
    matched = [
        f"{seg.get('speaker_name', 'Speaker')}: {seg['text']}"
        for seg in aligned_segments
        if _COMMITMENT_PATTERN.search(seg.get("text", ""))
    ]
    return "\n".join(matched) if len(matched) >= min_turns else ""


def _significant_words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text) if w.lower() not in _COMMON_WORDS}


def _reconcile_decisions(decisions_md: str, reversals_md: str, overlap_threshold: float = 0.5) -> str:
    """Drop any "decision" bullet that's actually been overruled/postponed
    elsewhere in the meeting — reusing the same word-overlap heuristic
    estimate_topic_timestamp() already uses to anchor topics to segments,
    rather than a deterministic keyword list hardcoded to one specific
    meeting's own facts (the version this was adapted from did exactly
    that — matched literal strings like "60%" and "1.5 year" from one test
    transcript, which only works for meetings that happen to share those
    exact numbers). A decision is dropped when it shares at least half its
    significant words with some reversal, which generalizes to any
    meeting's content instead of being tied to this one's."""
    reversal_word_sets = [_significant_words(r) for r in _markdown_bullets(reversals_md)]
    if not reversal_word_sets:
        return decisions_md
    kept = []
    for bullet in _markdown_bullets(decisions_md):
        words = _significant_words(bullet)
        overruled = any(
            words and len(words & rev_words) / len(words) >= overlap_threshold
            for rev_words in reversal_word_sets
        )
        if not overruled:
            kept.append(f"- {bullet}")
    return "\n".join(kept) if kept else "- None noted."


def generate_enhanced_notes(transcript_text: str, slides_data: list[dict[str, Any]], aligned_segments: list[dict[str, Any]], folder: Optional[Path] = None) -> dict[str, Any]:
    """Six narrow, single-purpose local LLM calls (see _llm_extract) instead
    of one big structured-JSON ask — model choice honors an onboarding
    selection (db setting) over the default. Long transcripts are chunked
    with overlap (_chunk_transcript) and each section's per-chunk results
    merged with one more light dedupe pass, so a long meeting still gets
    full coverage instead of being silently truncated.

    Returns Markdown for each section (for direct display — see
    process_recording_local, which assembles these into enhanced_notes.md)
    plus a flat keywords list (parsed from Key Entities) that feeds both
    the key-phrases UI and the cross-meeting vocabulary memory, same as
    before."""
    if not transcript_text.strip() and not slides_data:
        print("[Local LLM] No speech or slides detected — returning empty notes.", flush=True)
        return {
            "overview": "No speech was detected in this recording.",
            "action_items_md": "- None noted.",
            "decisions_md": "- None noted.",
            "timeline_md": "- None noted.",
            "open_questions_md": "- None noted.",
            "key_entities_md": "- None noted.",
            "keywords": [],
        }

    import mlx_lm

    liquid_model = db.get_setting("liquid_model", LOCAL_LLM_MODEL_DEFAULT)
    print(f"[Local LLM] Loading {liquid_model} for enhanced notes...", flush=True)
    if folder:
        _write_progress(folder, "loading_notes_model", "Preparing notes analysis engine...", percent=52)
    model, tokenizer = mlx_lm.load(liquid_model)

    slides_summary = ""
    if slides_data:
        slides_summary = "\n--- SLIDES & SCREENSHOTS OCR DATA ---\n"
        for s in slides_data[:6]:
            slides_summary += f"[{s.get('timestamp')}] {s.get('text', '')[:300]}\n"

    chunks = _chunk_transcript(transcript_text)
    t0 = time.time()
    total_output_tokens = 0

    SECTION_PROGRESS = {
        "Overview": ("Generating Executive Overview", 60),
        "Action Items": ("Extracting Action Items & Tasks", 68),
        "Key Discussion & Decisions": ("Extracting Decisions & Key Points", 76),
        "Timeline": ("Building Chronological Timeline", 84),
        "Open Questions": ("Identifying Open Questions", 90),
        "Key Entities": ("Extracting Key Entities & Keywords", 95),
    }

    def run(instruction: str, max_tokens: int = 1600, grounded: bool = True, section: str = "", source_text: Optional[str] = None) -> str:
        nonlocal total_output_tokens
        results = []
        run_chunks = _chunk_transcript(source_text) if source_text is not None else chunks
        label, pct = SECTION_PROGRESS.get(section, (f"Generating {section}", 70))
        for i, chunk in enumerate(run_chunks):
            if folder:
                detail = f"{label} (chunk {i + 1}/{len(run_chunks)})" if len(run_chunks) > 1 else label
                _write_progress(folder, "generating_notes", detail, percent=pct)
            text = chunk + (slides_summary if i == 0 else "")
            out = _llm_extract(model, tokenizer, instruction, text, max_tokens, grounded=grounded,
                               model_id=liquid_model, name=f"enhanced_notes.{_slug(section)}")
            results.append(out)
            try:
                total_output_tokens += len(tokenizer.encode(out))
            except Exception:
                pass
            _clear_mlx_cache()
        if len(results) == 1:
            return results[0]
        # Long recording, multiple chunks: merge with one more narrow pass
        # (still single-purpose — "tidy this list" — so it stays fast and
        # think-free in practice, same as every other call here) rather
        # than a heavier hierarchical reduce.
        if folder:
            _write_progress(folder, "generating_notes", f"Merging {section}...", percent=pct + 2)
        merged_raw = "\n".join(results)
        merge_instruction = f"Merge and deduplicate this list into one clean Markdown bullet list, keeping only distinct items. Context: {instruction}"
        out = _llm_extract(model, tokenizer, merge_instruction, merged_raw, max_tokens, grounded=grounded,
                           model_id=liquid_model, name=f"enhanced_notes.{_slug(section)}.merge")
        try:
            total_output_tokens += len(tokenizer.encode(out))
        except Exception:
            pass
        _clear_mlx_cache()
        return out

    overview = run("Write a 1-2 sentence executive overview of what this meeting covered, as plain prose (not a list).", 1200, grounded=False, section="Overview")

    # Deterministic pre-filter (see _mine_commitment_turns): a small model
    # extracting action items from a dense slice of turns that actually
    # sound like commitments does better than hunting for a handful of
    # real ones across a whole chunked transcript. Falls back to the full
    # transcript when mining finds too little to trust.
    commitment_text = _mine_commitment_turns(aligned_segments)
    action_items_md = run(
        "Extract ONLY the concrete action items/tasks from this meeting, as a Markdown bullet list — include an owner and due date only if actually mentioned.",
        section="Action Items",
        source_text=commitment_text or None,
    )

    # A separate "reversals" extraction pass (dropping decisions later
    # overruled/postponed — see _reconcile_decisions) was tried and reverted:
    # it added a 7th per-chunk LLM section on top of an already
    # memory-heavy run and contributed to a real crash on this machine.
    # Priority right now is accuracy + low memory footprint, not more calls.
    decisions_md = run("Extract the key discussion points and any decisions made in this meeting, as a Markdown bullet list. Do not repeat action items or restate the overview here — only genuine discussion points or decisions.", section="Key Discussion & Decisions")
    topics_md = run("List the distinct topics this meeting moved through, in the order discussed, as a Markdown bullet list — format each line as '- <short topic name>: <one sentence summary>'.", section="Timeline")
    questions_md = run("Extract any unresolved questions or open items left from this meeting, as a Markdown bullet list.", section="Open Questions")
    entities_md = run("List AT MOST 8 of the most important products, projects, systems, or people actually named in this meeting, as a Markdown bullet list. Each line must be JUST the name and nothing else — no description, no explanation, no dash or colon after the name. Fewer than 8 is fine; do not pad the list with generic terms that weren't actually said.", 1200, section="Key Entities")
    title_raw = run("Write a concise 3 to 6 word executive title for this meeting (no quotes, no punctuation at end).", 30, grounded=True, section="Title")
    meeting_title = re.sub(r'^["\'\s]+|["\'\s.]+$', '', title_raw).strip().split("\n")[0].strip()

    gen_seconds = time.time() - t0
    _last_llm_stats.clear()
    _last_llm_stats.update({
        "model": liquid_model,
        "generation_seconds": round(gen_seconds, 2),
        "output_tokens": total_output_tokens or None,
        "tokens_per_second": round(total_output_tokens / gen_seconds, 1) if total_output_tokens and gen_seconds > 0 else None,
    })
    print(f"[Local LLM] Enhanced notes generated in {gen_seconds:.1f}s across {len(chunks)} chunk(s), {len(_markdown_bullets(action_items_md))} action item(s)", flush=True)

    # Anchor each Timeline topic to a real transcript timestamp — the model
    # names topics but was never asked for (and can't reliably invent)
    # exact times; estimate_topic_timestamp matches word-overlap against
    # the actual segments instead.
    timeline_lines = []
    for bullet in _markdown_bullets(topics_md):
        title, _, summary = bullet.partition(":")
        anchor = estimate_topic_timestamp(bullet, aligned_segments)
        prefix = f"**{format_ts(anchor)}** — " if anchor is not None else ""
        timeline_lines.append(f"- {prefix}{title.strip()}{': ' + summary.strip() if summary.strip() else ''}")
    timeline_md = "\n".join(timeline_lines) if timeline_lines else "- None noted."

    result = {
        "title": meeting_title,
        "overview": overview,
        "action_items_md": action_items_md,
        "decisions_md": decisions_md,
        "timeline_md": timeline_md,
        "open_questions_md": questions_md,
        "key_entities_md": entities_md,
        # Hard cap regardless of what the model actually returns — a real
        # meeting rarely surfaces more than a handful of genuine key
        # entities, so a much longer list is itself a strong hallucination
        # signal (measured directly: one run free-associated 55 generic
        # buzzwords never mentioned in the transcript, e.g. "A/B testing",
        # "Sprint planning" — none of which were said). The instruction
        # above asks for at most 8; this is the structural backstop for
        # when it doesn't listen.
        "keywords": [k for k in (_clean_keyword(b) for b in _markdown_bullets(entities_md)) if k][:8],
    }
    _release_mlx_model(model, tokenizer)
    return result


def generate_enhanced_notes_frontier(
    transcript_text: str,
    slides_data: list[dict[str, Any]],
    aligned_segments: list[dict[str, Any]],
    user_notes: str = "",
    provider: str = "anthropic",
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Generate executive structured meeting notes using user-configured frontier LLMs (Claude 3.7, GPT-4o, Gemini 3.8)."""
    import credentials

    if not transcript_text.strip() and not slides_data:
        return {
            "overview": "No speech was detected in this recording.",
            "action_items_md": "- None noted.",
            "decisions_md": "- None noted.",
            "timeline_md": "- None noted.",
            "open_questions_md": "- None noted.",
            "key_entities_md": "- None noted.",
            "keywords": [],
            "raw_text": "",
        }

    slides_summary = ""
    if slides_data:
        slides_summary = "\n--- SLIDES & SCREENSHOTS OCR DATA ---\n"
        for s in slides_data[:8]:
            slides_summary += f"[{s.get('timestamp')}] {s.get('text', '')[:300]}\n"

    notes_block = f"\n--- USER'S OWN NOTES ---\n{user_notes}\n" if user_notes.strip() else ""

    system_prompt = (
        "You are an executive chief of staff and expert meeting intelligence analyst. "
        "Analyze the meeting transcript, slide OCR data, and user notes. "
        "Generate a complete, high-fidelity executive document with exactly the following Markdown sections:\n\n"
        "## Title\n"
        "Concise, punchy 3-6 word executive meeting title (no quotes, no period).\n\n"
        "## Overview\n"
        "1-2 sentence crisp executive summary as clean prose (not a bullet list).\n\n"
        "## Action Items\n"
        "Markdown bullet list of concrete tasks and commitments. Format as '- <Action> (Owner: <Name>, Due: <Date>)'. If none, '- None noted.'\n\n"
        "## Key Discussion & Decisions\n"
        "Markdown bullet list of confirmed decisions and critical strategic discussion points. Be precise with metrics, numbers, and technical terms.\n\n"
        "## Timeline\n"
        "Markdown bullet list of distinct chronological topics: '- <Topic Name>: <One sentence summary>'\n\n"
        "## Open Questions\n"
        "Markdown bullet list of unresolved questions, open blockers, or pending questions.\n\n"
        "## Key Entities\n"
        "Markdown bullet list of at most 8 core products, systems, companies, or named people."
    )

    prompt = (
        f"MEETING TRANSCRIPT:\n\"\"\"\n{transcript_text[:45000]}\n\"\"\"\n"
        f"{slides_summary}\n"
        f"{notes_block}\n"
    )

    raw_response = credentials.call_configured_llm(
        trace_name="enhanced_notes.frontier",
        prompt=prompt,
        system_prompt=system_prompt,
        provider=provider,
        model=model,
        max_tokens=4096,
    )

    sections = {}
    curr_sec = None
    curr_lines = []
    for line in raw_response.splitlines():
        if line.startswith("## "):
            if curr_sec:
                sections[curr_sec] = "\n".join(curr_lines).strip()
            curr_sec = line[3:].strip()
            curr_lines = []
        else:
            curr_lines.append(line)
    if curr_sec:
        sections[curr_sec] = "\n".join(curr_lines).strip()

    overview = sections.get("Overview", "Meeting discussion.")
    raw_title = sections.get("Title", "").strip().split("\n")[0]
    meeting_title = re.sub(r'^["\'\s]+|["\'\s.]+$', '', raw_title).strip()
    action_items_md = sections.get("Action Items", "- None noted.")
    decisions_md = sections.get("Key Discussion & Decisions", "- None noted.")
    topics_md = sections.get("Timeline", "- None noted.")
    questions_md = sections.get("Open Questions", "- None noted.")
    entities_md = sections.get("Key Entities", "- None noted.")

    timeline_lines = []
    for bullet in _markdown_bullets(topics_md):
        title, _, summary = bullet.partition(":")
        anchor = estimate_topic_timestamp(bullet, aligned_segments)
        prefix = f"**{format_ts(anchor)}** — " if anchor is not None else ""
        timeline_lines.append(f"- {prefix}{title.strip()}{': ' + summary.strip() if summary.strip() else ''}")
    timeline_md = "\n".join(timeline_lines) if timeline_lines else "- None noted."

    keywords = [k for k in (_clean_keyword(b) for b in _markdown_bullets(entities_md)) if k][:8]

    return {
        "title": meeting_title,
        "overview": overview,
        "action_items_md": action_items_md,
        "decisions_md": decisions_md,
        "timeline_md": timeline_md,
        "open_questions_md": questions_md,
        "key_entities_md": entities_md,
        "keywords": keywords,
        "raw_text": raw_response,
    }


def estimate_topic_timestamp(topic_text: str, aligned_segments: list[dict[str, Any]]) -> Optional[float]:
    """Anchor an LLM-generated topic to a real point in the meeting: the
    1.2B model names topics but isn't reliable at inventing exact
    timestamps, so instead find whichever transcript segment shares the
    most significant (non-common) words with the topic's title+summary and
    use its start time. None if no segment shares any word at all, rather
    than guessing."""
    topic_words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", topic_text) if w.lower() not in _COMMON_WORDS}
    if not topic_words or not aligned_segments:
        return None
    best_start: Optional[float] = None
    best_overlap = 0
    for seg in aligned_segments:
        seg_words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", seg.get("text", "")) if w.lower() not in _COMMON_WORDS}
        overlap = len(topic_words & seg_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_start = seg.get("start")
    return best_start
