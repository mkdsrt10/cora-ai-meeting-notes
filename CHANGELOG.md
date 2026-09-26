# Changelog

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
