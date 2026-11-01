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

**OpenAI-compatible preset**: a named `openai_compatible` endpoint a Processing profile can choose: `openai`, `openrouter`, `groq`, `ollama`, `lmstudio`, or `custom` (any base URL, e.g. a LiteLLM proxy). One preset serves both the profile's text and, when its transcription is `openai_compatible`, its audio. _Avoid_: custom LLM (that is only one preset).

**Plugin**: a bundled extension that declares a View, data for a Recording, and Hooks. Bundled plugins at v1: Coaching, Todo/Planner.

**View**: a page in the Cora window, registered by id with a title and a render function. Plugins add Views without editing core files.

**Hook**: a point where the host calls plugins: `after_meeting` (once a Recording's notes are ready), `daily`.

**Speaker timeline**: who spoke when during a Recording, from the meeting app's accessibility tree and browser tabs. Not a transcript.
