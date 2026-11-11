"""Usage events the Python side emits (see python/usage_events.py for the
catalog): `processing_finished` once per processing run, from the trace run
row and the resource-usage entry the run already writes, and the daily
`people_snapshot` taken at server start. Emitting never breaks the caller:
a failure is printed and dropped."""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any, Optional

import ai_trace
import db
import paths
import usage_events

SNAPSHOT_EVERY = dt.timedelta(hours=24)


def _warn(name: str, exc: BaseException) -> None:
    print(f"[usage] {name} not recorded: {type(exc).__name__}: {exc}", flush=True)


def _sum(values) -> Optional[int]:
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def processing_finished(recording_id: str, profile: dict[str, Any], *, run_id: Optional[str],
                        started: float, resource: Optional[dict[str, Any]] = None,
                        window_fallbacks: Optional[int] = None, error_code: Optional[str] = None,
                        transcriber_model: Optional[str] = None) -> None:
    """Record one processing_finished for a run that just ended.

    Providers are the Processing profile's choices (the preset names the
    report's local/cloud split groups by); models are the first traced
    transcription / llm span's, else the profile's. tokens_in/out sum the
    run's llm spans; retries counts its failed spans (calls retried or
    replaced by a fallback). Timings, speech/silence, peak RSS and audio
    duration come from the resource-usage entry (absent on a failed run,
    where peak RSS falls back to the run row's)."""
    try:
        run = ai_trace.run_summary(run_id) or {}
        spans = run.get("spans") or []
        llm = [s for s in spans if s["kind"] == "llm"]
        asr = [s for s in spans if s["kind"] == "transcription"]
        resource = resource or {}
        stages = resource.get("stage_seconds") or {}
        usage_events.record("processing_finished", {
            "recording_id": recording_id,
            "status": "error" if error_code else "ok",
            "error_code": error_code,
            "transcriber_provider": profile.get("transcription"),
            "transcriber_model": (asr[0]["model"] if asr and asr[0]["model"] else transcriber_model),
            "text_provider": profile.get("provider"),
            "text_model": (llm[0]["model"] if llm and llm[0]["model"] else profile.get("model") or None),
            "transcription_s": stages.get("transcription"),
            "summarization_s": stages.get("summarization"),
            "total_s": run.get("duration_s") if run.get("duration_s") is not None else round(time.time() - started, 1),
            "tokens_in": _sum(s["input_tokens"] for s in llm),
            "tokens_out": _sum(s["output_tokens"] for s in llm),
            "window_fallbacks": window_fallbacks,
            "speech_s": resource.get("speech_duration_seconds"),
            "silence_s": resource.get("silence_removed_seconds"),
            "retries": sum(1 for s in spans if s["status"] == "error"),
            "peak_rss_mb": resource.get("peak_memory_mb") or run.get("peak_rss_mb"),
            "duration_s": resource.get("audio_duration_seconds"),
        })
    except Exception as exc:  # never let telemetry break processing
        _warn("processing_finished", exc)


def _last_snapshot_at() -> Optional[dt.datetime]:
    with db.get_db() as conn:
        row = conn.execute("SELECT MAX(created_at) FROM usage_events WHERE name = 'people_snapshot'").fetchone()
    if not row or not row[0]:
        return None
    return dt.datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _disk_mb() -> int:
    """Size of the Recordings folder (audio, transcripts, notes)."""
    total = 0
    for root, _dirs, files in os.walk(paths.RECORDINGS_DIR):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return round(total / 2**20)


def people_snapshot_if_due() -> bool:
    """At server start: record a people_snapshot unless one was recorded in
    the last 24 hours. Returns whether one was recorded."""
    try:
        db.init_db()
        last = _last_snapshot_at()
        if last is not None and usage_events._now() - last < SNAPSHOT_EVERY:
            return False
        usage_events.record("people_snapshot", {"people": len(db.get_all_people()),
                                                "recordings": len(db.get_all_recordings()),
                                                "disk_mb": _disk_mb()})
        return True
    except Exception as exc:
        _warn("people_snapshot", exc)
        return False
