# Changelog

## 0.3.3 — 2026-11-10

- Slack huddles in a browser: a huddle collapsed to Slack's bottom mini-bar (or popped out to its own window) has no participant tiles in the tab. The other party of a DM huddle is now read from the mini-bar's "Huddle with <Name>" title, and that title is used as the meeting title; a channel huddle still names nobody there.

## 0.3.2 — 2026-11-10

- Slack huddles in a browser: participants are read from the huddle's own tiles and "Name's profile" labels (the previous selectors matched nothing in today's Slack), the huddle title comes from the huddle window, and a DM tab without a huddle is no longer treated as a live call.
- A meeting title is announced once per recording; two live tabs no longer make the title alternate every scan.
- Participants tab: "Add <name> to People…" in a row's link dropdown creates the Person and links the participant in one step.

## 0.3.1 — 2026-11-10

- Fix: participant names in browser meetings (Meet, Zoom web, Slack huddles) were empty since 0.2.3. The page-snapshot script is flattened onto one line before it reaches the browser, and `//` comments added in 0.2.3 commented out the rest of it. Comments are now block comments and a test parses the flattened script.
- The speaker watcher's full output is back in `logs/speaker-watch-*.log` (only level meters are left out), and an AppleScript failure is logged with its message, not just its number.
- A browser Slack huddle popup (window titled "Huddle…") now counts as a Slack window for the Accessibility fallback.

## 0.3.0 — 2026-11-10

- Microphone selector: Settings > Recording and the onboarding permissions step let you pick the microphone Cora records with. "System default" now follows the macOS default input (it previously followed AVFoundation's own idea of a default, which could be the webcam mic). The floating bar and recording panel name the microphone in use; a mic that is missing or disconnects mid-call falls back to the system default without stopping the recording, with a notification.
- Cloud transcription resilience: speech detection is relative to each recording's noise floor instead of fixed thresholds; a Window the cloud engine keeps rejecting or refuses is transcribed on this Mac (or kept as a marked gap on builds without a local model) instead of failing the meeting; affected lines are marked in the transcript and summarised in one notification.
- A Recording whose processing failed now shows "Processing failed" with the reason and a Retry button, instead of "Needs diarization".
- Architecture (v0.3): one Text model and one Transcriber behind every model call, a Plugin seam (Coaching and Todo as plugins), a Recording session and Processing queue in Electron, "Where models run" settings with OpenAI-compatible presets, typed processing errors.
- Research: `docs/RESEARCH.md` gains a week-long local vs Gemini comparison with judge-graded accuracy, and `tools/compare_engine_reruns.py`.

## 0.2.3 — 2026-10-31

- Team builds (`scripts/build-app.sh --team`): new installs default to Gemini for transcription and notes, skip local model downloads, and ask for the Gemini key after onboarding. `docs/TEAM_SETUP.md` walks a new member through it.
- Bundled ffmpeg/ffprobe (built from the official 7.1.1 source by `scripts/build-ffmpeg.sh`): no Homebrew needed.
- Releases are signed with one persistent self-signed identity (`scripts/signing-setup.sh`), so macOS permission grants survive updates.
- Participant names in browser meetings: one tab-less window or tab refusing JavaScript no longer aborts the whole scan; Zoom web client supported; clear fixes shown for "Allow JavaScript from Apple Events" and Automation errors.
- Fix: packaged app now ships `config.example.json`, so fresh installs get default settings.
- Installer URL now points at the `production` branch.
- Notifications & logs panel, pause/resume and "Continue this meeting" now show live progress on the original meeting (and let you listen before it merges), floating widget lost its Screen button.
- Optional hosted transcription: Settings > On-Device Models > Transcription engine can use Google Gemini instead of the local model (off by default, disabled under enterprise lockdown). It transcribes in ~4-minute windows (15-17 requests per meeting-hour instead of ~200 short clips), validates every window, snaps timestamps to the local speech detector, retries then splits a bad window, and fails loudly rather than silently switching engines. See docs/transcription.md.
- Fix: choosing "On this Mac" no longer uploads the recording; transcripts now record which engine really ran.
- One-line installer (`scripts/install.sh`) so the unsigned app opens without the macOS warning; INSTALL docs explain why the app isn't notarized.
- `tools/asr_bench.py` + `docs/ASR_BENCHMARK.md`: score candidate speech models on your own meeting.

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
