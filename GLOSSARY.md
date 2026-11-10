# Glossary

Domain terms for Cora. Code, docs and reviews use these names. Architecture vocabulary (module, interface, seam, adapter, depth) is separate and not repeated here.

**Recording**: one captured meeting: a DB row plus a folder under `recordings/` holding audio tracks, transcript, notes and artifacts. Identified by its recording id.

**Recording session**: the live capture of a Recording, from start to stop. Owns the capture state (idle, recording, paused), the capture helper processes, mute, notes typed during the call and slide snaps. Lives in the Electron main process. Stopping returns it to idle at once, so a new Recording can start straight away.

**Finishing**: what happens to a Recording between stop and the Processing queue: its capture helpers exit (or are killed), it is marked processing, and it is handed to the queue, in the order Recordings were stopped. Runs in the background, per Recording; it never blocks the next start, and quitting waits for it.

**Continuation**: a Recording that extends an earlier one ("Continue meeting"). Its segments merge into the root Recording after processing.

**Chunk**: one uninterrupted stretch of capture inside a Recording session, with its own recording id. Pausing ends a chunk; resuming starts a new chunk that is a Continuation of the session's first chunk. _Avoid_: segment (that is a stretch of transcript).

**Capture helper**: a native Swift process (`dual-capture`, `speaker-watch`, `mic-watch`) driven over stdin/stdout. Its stdout lines are a small grammar parsed in one place.

**Processing queue**: runs post-stop work for each Recording by id, one job at a time: archive, transcribe, name speakers, write notes, run plugin hooks. Recording is never blocked by it.

**Processing profile**: the resolved choice of transcription engine, text provider, model and notes template for one processing run. Passed explicitly, never read from a hidden global.

**Text model**: the module every text-generation call goes through (notes, speaker naming, romanization, summaries, coaching, plugins). Picks the adapter from the Processing profile and owns lockdown, tracing, JSON repair, retries and model defaults.

**Transcriber**: the module every speech-to-text call goes through. Adapters: local MLX Whisper, Gemini audio, OpenAI-compatible `/audio/transcriptions`.

**Provider**: who serves a Text model or Transcriber call: `local_mlx`, `openai_compatible`, `anthropic`, `gemini`. Not to be confused with **Gemini backend** (`vertex` vs `ai_studio`), which is how Gemini credentials are reached.

**OpenAI-compatible preset**: a named `openai_compatible` endpoint a Processing profile can choose: `openai`, `openrouter`, `groq`, `ollama`, `lmstudio`, or `custom` (any base URL, e.g. a LiteLLM proxy). One preset serves both the profile's text and, when its transcription is `openai_compatible`, its audio. _Avoid_: custom LLM (that is only one preset).

**Plugin**: a bundled extension that declares, in one place, its View, its data for a Recording, its Stages and its Hooks. Each is enabled or disabled on its own; a disabled Plugin is absent everywhere (no page, no data, no Hooks). Bundled plugins at v1: Coaching (off by default), Todo/Planner (on by default).

**View**: a page in the Cora window, registered by id with a title, a subtitle and what to render when shown. Core pages and Plugin pages register the same way; a Plugin adds a View without editing core files.

**Hook**: a point where the host calls plugins: `after_meeting` (once per processed Recording, after its notes and Action items are saved and while its audio still exists, whichever engine processed it; a merged Continuation reports its root Recording), `daily`. One Plugin failing in a Hook never stops the others.

**Stage**: where a Recording stands: recording, processing, paused, needs diarization, needs speaker confirmation, ready. A Plugin may refine "ready" into its own Stages (Coaching: ready to coach, coached). _Avoid_: status (that is only the capture/processing part).

**Action item**: a follow-up written into a Recording's notes. Todo/Planner keeps each as a To-do.

**To-do**: an Action item as Todo/Planner tracks it: done or not. It keeps its identity (and done mark) when its Recording is reprocessed and the same Action item comes back; one that no longer appears is superseded, not listed. _Avoid_: task.

**Window**: one clip of a Recording's audio sent to a cloud Transcriber call and validated as a unit; a Window that the cloud engine keeps rejecting is transcribed locally instead. _Avoid_: chunk (that is capture), segment (that is transcript).

**Speaker timeline**: who spoke when during a Recording, from the meeting app's accessibility tree and browser tabs. Not a transcript.
