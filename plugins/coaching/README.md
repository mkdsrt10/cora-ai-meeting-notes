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

## Enabling / disabling it

Off by default. Set `plugins.coaching.enabled` to `true` in `config.json` to
turn it on; `false` (or deleting this directory) turns it off. The flag is
read on every call, so no restart is needed.

Disabled, the plugin host (`python/plugin_host.py`) leaves it out entirely:
- no `plugins.coaching` payload on a Recording, and the stage after speaker
  confirmation is plain `ready` instead of `ready_for_coaching` / `coached`;
- the `after_meeting` Hook never runs, so no audio goes to Gemini;
- archetype tagging (`api.core.archetypes()`) becomes a no-op.

Enabled, the `after_meeting` Hook scores the owner's turns only for a
Recording diarized by Gemini (whose audio already went to Google in that
run) with a confirmed owner speaker. Locally processed Recordings are never
uploaded by this plugin.

## Files

- `__init__.py` — the Plugin declaration (payload, stages, Hooks).
- `plugin.py` — its view model, stages and `after_meeting` Hook; light to
  import (the engine loads only when a report is generated).
- `engine.py` — archetype rubrics, coaching prompts/schemas, delivery-metrics
  signal processing (pace/pause/filler/pitch — this math itself is local, only
  the coaching prompt + archetype classification call the cloud).
- `coach_engine.py` — an older, fully local, non-LLM heuristic scorer (WPM,
  filler rate, pause detection via `ffmpeg silencedetect`). Currently unused
  by `server.py`; kept as a reference implementation for a no-cloud-at-all
  coaching mode, and as a starting point if you want to port scoring to a
  local model instead of Gemini.
