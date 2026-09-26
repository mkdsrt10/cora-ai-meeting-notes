# Coaching plugin

Optional. Cora's core (record → transcribe → diarize → summarize) works fully
without this. This plugin adds:

- Meeting-archetype classification (Technical Steering, Standup, 1:1, etc.)
- Per-speaker scoring rubrics tied to that archetype
- Delivery metrics: pace, pauses, filler words, pitch/volume variety
- The goals / reflections / practice-queue habit loop built on top of scores

## Privacy note

Unlike core diarization (which can run fully locally via `local_meeting_pipeline.py`
on Apple Silicon), **this plugin still calls Google Gemini's cloud audio API** to
generate coaching scores and archetype classification — it has not been ported to
a local model yet. Enabling it opts you into that additional cloud call for the
coaching layer only; your transcript and a re-encoded copy of the audio are sent
to Gemini and the remote copy is deleted after analysis (see the `privacy_note`
field on every coaching result).

## Disabling it

Two ways, either is enough on its own:

1. Set `plugins.coaching.enabled` to `false` in `config.json`.
2. Delete this directory (`plugins/coaching/`) entirely.

Either way, `python/diarization.py` and `python/server.py` degrade gracefully:
- Coaching endpoints (`/api/gemini-coach`, `/api/confirm-and-coach`) return a
  clear 404 instead of crashing.
- The auto-pilot hook inside `diarize()` still auto-confirms a recognized
  speaker's identity, but skips generating a coaching report.
- `ARCHETYPES` resolves to an empty dict, so archetype-selection endpoints
  become no-ops rather than errors.

## Files

- `engine.py` — archetype rubrics, coaching prompts/schemas, delivery-metrics
  signal processing (pace/pause/filler/pitch — this math itself is local, only
  the coaching prompt + archetype classification call the cloud).
- `coach_engine.py` — an older, fully local, non-LLM heuristic scorer (WPM,
  filler rate, pause detection via `ffmpeg silencedetect`). Currently unused
  by `server.py`; kept as a reference implementation for a no-cloud-at-all
  coaching mode, and as a starting point if you want to port scoring to a
  local model instead of Gemini.
- `backfill_delivery_metrics.py` — maintenance script to recompute delivery
  metrics for already-coached recordings after a scoring-logic change.
