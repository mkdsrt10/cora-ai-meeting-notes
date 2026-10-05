# Changelog

## 0.2.2 — 2026-10-05

- Added higher-end model options for people with more RAM to spare: `mlx-community/whisper-large-v3-mlx`
  (full, non-fine-tuned 32-layer Whisper for general-purpose accuracy) and `mlx-community/Qwen3-8B-4bit` /
  `mlx-community/Qwen3-14B-4bit` (better reasoning and notes quality than the 4B default, for 32GB+/64GB+
  Macs).

## 0.2.1 — 2026-10-05

- Added `mayank-dubey-ai/tara-mlx` — a public MLX conversion of Trelis Tara (Apache 2.0, full
  32-layer decoder) — as a one-click downloadable Whisper model, offered as the recommended
  high-accuracy option alongside the existing turbo fine-tune.
- The model-download prompt now also fires immediately after first-run onboarding finishes,
  instead of only on the next app launch — so a freshly chosen model that isn't downloaded yet
  gets a visible download-with-progress prompt right away, rather than silently downloading on
  the first recording with no UI feedback.

## 0.2.0 — 2026-09-29

- Model setup from the UI: a startup check prompts to download or pick a model when the configured
  one isn't ready, with live download progress; the same flow is wired into Settings.
- Added `mayank-dubey-ai/whisper-large-v3-turbo-hinglish-mlx` as a one-click public Hinglish
  fine-tune, no personal checkpoint or local conversion required.
- Fixed a bug where the transcription model choice was cached at process startup, so switching
  models (or fixing a broken local checkpoint) silently had no effect until a full app restart.
- Fixed local Whisper model selection only checking that a directory existed, not that it actually
  had weight files — a checkpoint that lost its weights (e.g. to disk pressure) would keep being
  picked over a working fallback, failing every transcription with an opaque `load_npz` error.
- `docs/RESEARCH.md`: why local meeting intelligence breaks, and what fixes it.

## 0.1.0 — 2026-09-26 — first public release

- Local-first meeting capture, transcription (MLX Whisper), speaker attribution and notes on Apple Silicon.
- Security: token-protected loopback API, sandboxed renderers with strict CSP, enterprise lockdown,
  owner-only data files, secrets kept off the command line.
- Local AI tracing of every model call for benchmarking and retraining (`tools/traces.py`).
- Transcript editor (speakers and text) with corrections recorded as training data; LLM naming of
  remote participants; pause-bounded chunked transcription; two-track audio archive.
- Reproducible setup (`make setup`), CI, tests.
- Context-aware Whisper prompts per chunk (attendees, screenshots, notes, past meetings, vocabulary).
- Romanized Hinglish transcripts (Devanagari converted by a validated local-LLM pass; original kept).
- Self-contained macOS app (.dmg) with a bundled Python runtime (`make app`).
