"""Langfuse Tracing and Dataset Curation Module for Cora.

Traces meeting intelligence pipelines (Gemini 3.8 Flash, Gemini 3.7 Flash, Local MLX, Apple Vision OCR)
into Langfuse for debugging, latency tracking, and fine-tuning dataset preparation.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# No built-in keys: tracing sends meeting content (titles, participant names,
# summaries) to a third party, so it is strictly opt-in — the user must
# supply their own Langfuse project keys AND enable tracing explicitly.
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")

_client = None


def tracing_opted_in() -> bool:
    import policy
    if policy.lockdown_enabled() or not (LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY):
        return False
    if os.environ.get("VOICECOACH_TRACING") == "1":
        return True
    try:
        import db
        return bool(db.get_setting("tracing_enabled", False))
    except Exception:
        return False


def get_langfuse() -> Any:
    """Lazy-load and return the Langfuse client."""
    global _client
    if _client is not None:
        return _client
    if not tracing_opted_in():
        return None
    try:
        from langfuse import Langfuse
        client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        if client.auth_check():
            _client = client
            return _client
    except Exception as e:
        print(f"[Tracing] Langfuse initialization warning: {e}")
    return None


def is_available() -> bool:
    return get_langfuse() is not None


def trace_pipeline_run(
    recording_id: str,
    pipeline_type: str,
    model: str,
    input_summary: Any,
    output_summary: Any,
    latency_seconds: float = 0.0,
    metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Log a complete meeting pipeline run to Langfuse."""
    lf = get_langfuse()
    if not lf:
        return None

    try:
        meta = {
            "recording_id": recording_id,
            "pipeline": pipeline_type,
            "latency_seconds": round(latency_seconds, 2),
            **(metadata or {}),
        }
        obs = lf.start_observation(
            name=f"cora-{pipeline_type}",
            as_type="generation",
            model=model,
            input=input_summary,
            output=output_summary,
            metadata=meta,
        )
        obs.end()
        lf.flush()
        return str(obs.id)
    except Exception as e:
        print(f"[Tracing] Failed to log trace: {e}")
        return None


def add_to_dataset(
    dataset_name: str,
    input_data: Any,
    expected_output: Any,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    """Save an audio-text or prompt-response pair to a Langfuse Dataset for future fine-tuning."""
    lf = get_langfuse()
    if not lf:
        return False

    try:
        try:
            lf.get_dataset(dataset_name)
        except Exception:
            try:
                lf.create_dataset(name=dataset_name)
            except Exception:
                pass

        lf.create_dataset_item(
            dataset_name=dataset_name,
            input=input_data,
            expected_output=expected_output,
            metadata=metadata or {},
        )
        lf.flush()
        return True
    except Exception as e:
        print(f"[Tracing] Failed to add dataset item: {e}")
        return False
