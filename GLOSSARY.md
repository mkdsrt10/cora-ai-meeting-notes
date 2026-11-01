# Glossary

Domain terms for Cora. Code, docs and reviews use these names. Architecture vocabulary (module, interface, seam, adapter, depth) is separate and not repeated here.

**Recording**: one captured meeting: a DB row plus a folder under `recordings/` holding audio tracks, transcript, notes and artifacts. Identified by its recording id.

**Recording session**: the live capture of a Recording, from start to stop. Owns the capture state (idle, recording, finishing), the capture helper processes, mute, notes typed during the call and slide snaps. Lives in the Electron main process.

**Continuation**: a Recording that extends an earlier one ("Continue meeting"). Its segments merge into the root Recording after processing.

**Capture helper**: a native Swift process (`dual-capture`, `speaker-watch`, `mic-watch`) driven over stdin/stdout. Its stdout lines are a small grammar parsed in one place.

**Processing queue**: runs post-stop work for each Recording by id, one job at a time: archive, transcribe, name speakers, write notes, run plugin hooks. Recording is never blocked by it.

**Processing profile**: the resolved choice of transcription engine, text provider, model and notes template for one processing run. Passed explicitly, never read from a hidden global.

**Text model**: the module every text-generation call goes through (notes, speaker naming, romanization, summaries, coaching, plugins). Picks the adapter from the Processing profile and owns lockdown, tracing, JSON repair, retries and model defaults.

**Transcriber**: the module every speech-to-text call goes through. Adapters: local MLX Whisper, Gemini audio, OpenAI-compatible `/audio/transcriptions`.

**Provider**: who serves a Text model or Transcriber call: `local_mlx`, `openai_compatible`, `anthropic`, `gemini`. Not to be confused with **Gemini backend** (`vertex` vs `ai_studio`), which is how Gemini credentials are reached.

**Plugin**: a bundled extension that declares, in one place, its View, its data for a Recording, its Stages and its Hooks. Each is enabled or disabled on its own; a disabled Plugin is absent everywhere (no page, no data, no Hooks). Bundled plugins at v1: Coaching (off by default), Todo/Planner (on by default).

**View**: a page in the Cora window, registered by id with a title, a subtitle and what to render when shown. Core pages and Plugin pages register the same way; a Plugin adds a View without editing core files.

**Hook**: a point where the host calls plugins: `after_meeting` (once a Recording's notes are ready, whichever engine processed it), `daily`. One Plugin failing in a Hook never stops the others.

**Stage**: where a Recording stands: recording, processing, paused, needs diarization, needs speaker confirmation, ready. A Plugin may refine "ready" into its own Stages (Coaching: ready to coach, coached). _Avoid_: status (that is only the capture/processing part).

**Action item**: a follow-up written into a Recording's notes. Todo/Planner lists them across Recordings and tracks which are done.

**Speaker timeline**: who spoke when during a Recording, from the meeting app's accessibility tree and browser tabs. Not a transcript.
