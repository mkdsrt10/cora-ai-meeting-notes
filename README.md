# Cora AI Meeting Notes

The AI memory of your work across meetings — a local-first macOS app that records, transcribes,
identifies speakers, and structures notes so what was said and decided is never lost between
calls, all on your own machine by default. No account, no API key required to get started, no
audio leaves your Mac unless you explicitly turn on an optional cloud feature.

## Why this exists

Camera phones didn't turn everyone into a professional photographer, but they did move "taking a
good photo" from something you needed a professional for into something a phone just does by
default. The next stretch should do the same thing to sitting in a meeting with someone smart
taking notes for you — and right now, that mostly means renting the intelligence, one recording at
a time, from whichever cloud vendor is behind the app.

Cora is a bet on the other direction: that people should own that intelligence rather than rent it
— their meetings, their transcripts, and the model reading them, running on hardware they already
have, under their control. Local models keep getting better, and the point of building this
in the open is to keep pushing until fully local isn't a compromise, just the obvious default —
while still leaving the door open to a cloud model for anyone who wants the extra accuracy.

Tools like [Granola](https://www.granola.ai) got this kind of AI meeting memory genuinely right as
a product, and that's real credit — it's what convinced me this was worth building on. But it's
closed: you can't see how it decided who said what, can't add a capability it doesn't have, can't
point it at your own fine-tuned model, can't take your data and build on top of it. Cora AI Meeting
Notes is meant to be the open, local-first, **customizable** version of that idea — a memory
system, a base for plugins, a thing you can actually own and extend rather than just subscribe to.
If you build something on it, I'd genuinely like to know — see [Contributing](#contributing) and
[License](#license).

## What it does

- **Records** meetings (system audio + mic) via a native Swift capture helper, with automatic
  meeting detection (Zoom, Google Meet, Teams, Slack Huddles) so you don't have to remember to
  hit record.
- **Transcribes locally** using a fine-tuned MLX Whisper model on Apple Silicon — no cloud call.
- **Identifies speakers** by correlating transcript timing with the macOS Accessibility API's view
  of who's speaking in your meeting app, plus a growing local "who's this voice" people directory.
- **Captures slides/screenshots** during a call and OCRs them locally with Apple's Vision
  framework, so on-screen text ends up searchable alongside the transcript.
- **Structures notes** (summary, decisions, action items) using a small local LLM
  (Qwen3 4B by default, via MLX) — again, no cloud call for this by default.

Behind the app layer in this repo, there's an ongoing effort on the model and data side —
fine-tuning the ASR model, curating training data from corrected transcripts, and evaluation
tooling. `tools/` holds what's public so far (`curate_training_data.py`,
`extract_whisper_dataset.py`, `convert_whisper_to_mlx.py`, `eval_asr.py`); the reasoning behind
several of the pipeline's design choices — and where a local model still falls short of a cloud
one — is written up in [docs/RESEARCH.md](docs/RESEARCH.md). More is coming as that work matures.

## Requirements

- macOS 14+ on Apple Silicon (M1 or later) — the local ML stack (`mlx`, `mlx-whisper`, `mlx-lm`)
  needs Metal and won't run on Intel Macs.
- Xcode Command Line Tools (`xcode-select --install`) — builds the Swift capture helpers.
- [Homebrew](https://brew.sh). The setup script installs `ffmpeg`, `node` and
  [`uv`](https://docs.astral.sh/uv/) if they're missing.

## Install

Download the `.dmg` from the [latest release](https://github.com/mkdsrt10/cora-ai-meeting-notes/releases/latest)
and follow [docs/INSTALL.md](docs/INSTALL.md) (the build is not notarized yet, so first launch needs one
extra step). Or build from source:

## Quickstart (from source)

```bash
git clone https://github.com/mkdsrt10/cora-ai-meeting-notes.git
cd cora-ai-meeting-notes
make setup   # checks the Mac, installs locked Python + Node deps, builds native helpers
make dev     # launches the app
```

The repo can live anywhere — nothing assumes a particular path. On first launch macOS asks for
**Microphone**, **Screen Recording** (required by ScreenCaptureKit to capture the other side of the
call — no video is recorded) and **Accessibility** (to read who is speaking in your meeting app).
See [docs/SETUP.md](docs/SETUP.md) for permissions, troubleshooting and running a second dev
instance.

Models are not bundled; the first run downloads public ones from Hugging Face
(`mlx-community/whisper-small-mlx` and `mlx-community/Qwen3-4B-Instruct-2507-4bit`). You can pick
others in onboarding or point `local_whisper_models` at your own fine-tuned checkpoints.

| Command | What it does |
|---|---|
| `make setup` | One-time machine setup (idempotent) |
| `make dev` | Build native helpers if needed, start the app |
| `make app` | Build a self-contained `.app` and `.dmg` in `dist/` |
| `make build-native` | Compile the Swift helpers in `capture/` and `bin/` |
| `make lint` / `make test` | ruff + ESLint (+ cross-file UI lint) / pytest — the same checks CI runs |

## Where your data lives

Code and data are separate. All recordings, transcripts, notes, voice clips, logs, the SQLite DB
and your `config.json` live in the **data directory**, which is created owner-only (`0700`, files
`0600`):

1. `$VOICECOACH_DATA_DIR` if set, otherwise
2. `~/voicecoach-desktop` if it already contains a database (installs predating this layout), otherwise
3. `~/Library/Application Support/Cora AI Meeting Notes`.

## Configuration

`config.json` in the data directory (created from [`config.example.json`](config.example.json) on
first run):

| Key | Purpose |
|---|---|
| `whisper_model` | Public MLX Whisper repo used when no local fine-tuned model is configured |
| `local_whisper_models` | Your own checkpoints, in priority order: `[{"path": "~/my-whisper-mlx", "label": "..."}]` |
| `transcription_vocabulary_hint` | A static base hint biasing Whisper's spelling, combined at runtime with a glossary from known people and past transcripts |
| `silence_min_gap_seconds` / `silence_threshold_db` | Tuning for the dead-air detection that runs before local transcription |
| `plugins.<name>.enabled` | Turn an installed plugin on/off without deleting it — see [Plugins](#plugins-experimental) |
| `enterprise_lockdown` | `true` disables every outbound feature — see [Security](#security) |
| `transcript_script` | `roman` (default): Romanized Hinglish — Devanagari from the ASR is converted (original kept as training data); `native`: leave as transcribed |
| `local_tracing` | Local AI-call trace store for retraining and benchmarks — see [docs/TRACING.md](docs/TRACING.md) |
| `participant_stopwords` | Extra words (e.g. your workspace/org name) that should never be treated as a participant name |

Cloud credentials (only needed for optional cloud features) are stored in the macOS Keychain, with a
fallback file at `~/.config/cora/credentials.json` (0600) — never in this repo and never in the
SQLite database.

## Architecture

```
src/main.js            Electron: tray, windows, IPC, capture/recording state machine
src/main/              paths.js (code vs data), api-client.js (token, server handshake), security.js
src/ui/web/js/         dashboard UI — ordered classic scripts, one feature per file (see index.html)
capture/, bin/         Swift helpers: dual-track capture, mic activity, active speaker, OCR
python/server.py       starts the local API
python/api/            router, auth (token/Host/Origin), http handler, views, routes/<area>.py
python/pipeline/       config · audio · vocabulary · transcribe · speakers · llm · notes · runner
python/                db, credentials, paths, policy (lockdown), ai_trace, transcript_edit, …
plugins/               optional, independently loadable plugins (see Plugins below)
tools/                 traces, audio repair, model conversion, dataset tools
tests/                 pytest suite (API security, pipeline pieces, tracing, editing)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture. Data flows: capture → `inbox/` → archive (two-track audio + playback mix) →
`pipeline.runner` (silence detection → chunked Whisper → speaker attribution → LLM speaker naming →
enhanced notes) → SQLite + files in the recording folder → UI / MCP. Every AI call is recorded in the
local trace store.

`python/paths.py` is the single source of truth for code vs. data locations, and
`python/policy.py` holds the enterprise-lockdown switch every outbound feature checks.

## Privacy

- Transcription, diarization, and note structuring run locally by default (`local_meeting_pipeline.py`).
- Voice reference clips used for local speaker recognition live in the data directory's `people/`
  folder — they never leave your machine.
- Langfuse tracing is **off** unless you supply your own project keys and enable it.
- An installed plugin can add its own network calls (see [Plugins](#plugins-experimental)) — none
  are enabled by default.

## Security

- The local API (`127.0.0.1:8765`) requires a per-launch token: the app window gets it as an
  HttpOnly `SameSite=Strict` cookie, local tools send `X-VC-Token` (read from `.api_token` in the
  data directory, `0600`). Requests with a foreign `Host` or `Origin` are rejected, and POST bodies
  must be JSON — so websites in your browser can't read recordings or start a capture.
- Renderers are sandboxed, run under a strict Content-Security-Policy with no remote code or fonts,
  can't navigate away or open windows, and only our own pages may use the privileged IPC bridge.
- **Enterprise lockdown** (`"enterprise_lockdown": true` in `config.json`, or
  `VOICECOACH_ENTERPRISE_LOCKDOWN=1` via MDM, which the app can't override) blocks tracing, cloud LLM
  and transcription providers, VM sync and data contribution; only localhost model endpoints remain.

## Plugins (experimental)

Cora's core (record → transcribe → diarize → summarize) is fully self-contained; `plugins/` is a
mechanism for bolting on optional functionality without touching it. Core code never imports a
plugin directly — it goes through `python/plugin_registry.py`, which returns `None` if the plugin
is disabled or its directory doesn't exist, so deleting a plugin's folder is always a safe way to
run without it.

There's currently one plugin, `plugins/coaching/` (meeting-archetype classification, per-speaker
scoring, delivery metrics, a goals/practice-queue habit loop). **It's an early, unfinished
prototype** — expect rough edges and breaking changes — and it still calls Google Gemini's cloud
API for scoring rather than running locally; see [plugins/coaching/README.md](plugins/coaching/README.md)
for exactly what it sends. It's off by default (`config.json`'s `plugins.coaching.enabled`). More
plugins, and a documented plugin interface, are planned.

## Known limitations / in progress

- Windows/Linux are not supported; this is a macOS-only project for now.
- Live/streaming transcription during an active recording is not yet implemented — transcription
  happens after you stop recording.
- The plugin system itself is early — see [Plugins](#plugins-experimental).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the code map and PR
checklist, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Please report vulnerabilities privately as
described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 [Mayank Dubey](https://github.com/mkdsrt10). You're free to use, modify,
fork and build commercial products on this code — the one condition MIT asks for in return is
keeping that copyright notice in copies or forks, so the origin stays attributed. Please don't
strip it or re-attribute the project to someone else.
