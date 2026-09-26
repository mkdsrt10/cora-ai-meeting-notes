"""Local LLM calls (traced) and transcript chunking for the notes stage."""
from __future__ import annotations

import re
from typing import Any, Optional

import ai_trace


_last_llm_stats: dict[str, Any] = {}


def traced_generate(model, tokenizer, prompt: str, *, max_tokens: int, model_id: str, name: str,
                    prompt_template: Optional[str] = None, input_payload: Any = None) -> str:
    """mlx_lm.generate, recorded in the local AI trace.

    Uses stream_generate (exactly what mlx_lm.generate does internally) so
    the final response's prompt/generation token counts, per-phase
    throughput and peak Metal memory can be captured for benchmarking.
    """
    import mlx_lm

    with ai_trace.span("llm", name, provider="mlx", model=model_id, input=input_payload or {"prompt": prompt},
                       params={"max_tokens": max_tokens}, prompt_template=prompt_template) as trace:
        text, last = "", None
        for last in mlx_lm.stream_generate(model, tokenizer, prompt, max_tokens=max_tokens):
            text += last.text
        if last is not None:
            trace.set(input_tokens=last.prompt_tokens, output_tokens=last.generation_tokens,
                      prompt_tps=round(last.prompt_tps, 2), generation_tps=round(last.generation_tps, 2),
                      peak_memory_mb=round(last.peak_memory * 1000, 1), finish_reason=last.finish_reason)
        trace.set_output(text)
    return text


def _llm_extract(model, tokenizer, instruction: str, transcript_chunk: str, max_tokens: int = 1200, grounded: bool = True,
                 model_id: str = "", name: str = "llm_extract") -> str:
    """Invokes local MLX LLM using native ChatML template to prevent instruction regurgitation."""
    if not transcript_chunk or not transcript_chunk.strip():
        return "- None noted."

    grounding = (
        " Only include information explicitly stated in the transcript — "
        "do not invent, infer, or add plausible-sounding details that aren't "
        "actually there."
        if grounded else ""
    )
    user_message = f"{instruction}{grounding}\n\nCONTENT TO ANALYZE:\n\"\"\"\n{transcript_chunk}\n\"\"\""

    # Format with native tokenizer chat template if available
    try:
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": user_message}],
            tokenize=False,
            add_generation_prompt=True,
        )
    except Exception:
        prompt = f"<|im_start|>user\n{user_message}<|im_end|>\n<|im_start|>assistant\n"

    raw = traced_generate(model, tokenizer, prompt, max_tokens=max_tokens, model_id=model_id, name=name,
                          prompt_template=instruction + grounding,
                          input_payload={"instruction": instruction, "grounded": grounded,
                                         "content": transcript_chunk, "prompt": prompt})

    # Clean any closing ChatML tags or thinking blocks
    clean = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    clean = re.sub(r"<\|im_end\|>", "", clean).strip()
    return clean or "- None noted."


def _chunk_transcript(text: str, max_chars: int = 32000, overlap: int = 1000) -> list[str]:
    """Split a long transcript into overlapping windows so a long recording
    still gets every section covered instead of the old behavior (a flat
    transcript_text[:12000] slice that silently dropped everything past
    the cutoff). The overlap keeps a topic that straddles a chunk boundary
    from getting cut mid-thought in both halves."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks
