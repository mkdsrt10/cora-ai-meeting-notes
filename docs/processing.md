# Processing profiles (minimal implementation)

Setup and **Settings → Processing & models** save one `processing_preferences` object. Stopping a desktop recording already calls `/api/process-recording`; that route now resolves the saved profile once for the whole run. Existing installations preserve their previous ASR choice until a profile is saved. Saving credentials alone never selects cloud processing.

| Mode | Transcription | Notes |
|---|---|---|
| `local_light` | Existing MLX Whisper configuration | Existing targeted extraction, with template guidance |
| `local_thorough` | Existing MLX Whisper configuration | Selected MLX model, whole-input JSON generation or hierarchical passes |
| `cloud` | Existing windowed Gemini ASR | Configured cloud provider; Gemini by default |

Cloud is a preset: local audio preparation, OCR and Accessibility speaker alignment still happen on the Mac. Model inference for ASR, speaker-name/romanization helpers, template selection and notes uses the cloud in this preset. Google credentials are required for ASR even if another provider generates notes. No new provider SDK or extension runtime was introduced.

## Templates and overrides

Six built-in prompt templates: general, 1:1, standup, customer call, technical review and voice memo. They share the existing six-section artifact format for compatibility; each changes what the model extracts and emphasizes. This deliberately does not implement the larger custom-template/plugin plans.

`auto` makes one classification call using meeting metadata, user notes and samples from the beginning, middle and end of the transcript. Invalid classifications fall back to general and record `ai_fallback`. Note generation itself covers the full input using the selected strategy. The selected template and its selection source are saved in `call_summary.processing` and shown above the notes.

**Re-summarize with LLM** or **Change template / regenerate** opens the same controls with independent transcription and notes providers, local Light/Thorough strategy, model ID and template. Check **Also retranscribe** to use retained audio; otherwise notes regenerate from canonical transcript segments. Per-run choices do not change defaults. Prior outputs are archived through the existing versions mechanism.

## Resource and privacy behavior

- Recommendations use physical RAM and architecture; CPU count is also reported. This is not a performance benchmark. Apple Silicon with at least 24 GB RAM gets a Thorough recommendation; otherwise Light is recommended. No model is silently upgraded or downloaded by profile selection.
- Thorough reserves a conservative context window up to 8,192 tokens (including output allowance), bounded by the model's advertised limit when available. It raises the MLX memory cap to 40% of physical RAM, bounded to 6–16 GiB, and restores the normal cap afterward. Larger models may still exceed this budget.
- Cloud notes use a conservative portable input budget and hierarchical passes for longer inputs. A generation has at most 64 model calls, four merge levels and one retry for invalid output. Provider context errors remain visible; there is no silent truncation or provider fallback.
- Automatic processing waits for the cross-process processing lock. Manual runs report a busy error so the user can retry. Options live in a `ContextVar`, not shared mutable configuration.
- Lockdown forces automatic processing local and rejects explicit cloud overrides. Saving a cloud profile explicitly authorizes automatic egress, described beside the Save control. API keys remain in the existing credential store.
- Privacy text identifies the actual audio and notes paths. Notes-only regeneration explicitly states that it did not upload audio.
- Light retains existing heuristic extraction and timestamp matching. Generated content and timestamps are not verified citations. Thorough output is schema checked and safely coerces arrays of strings to bullets; factual accuracy remains model dependent.

## API

- `GET /api/processing`: saved preferences, hardware recommendation and template catalog.
- `POST /api/processing`: save validated preferences.
- `POST /api/process-recording`: optional `processing` object for one run; omit it to use defaults.
- `POST /api/recording/re-summarize`: the same optional object for notes only.

Example override:

```json
{"id":"recording-id","processing":{"mode":"local_thorough","transcription":"local","provider":"local_mlx","model":"mlx-community/Qwen3-4B-Instruct-2507-4bit","template":"technical_review"}}
```

## Validation

Run `make test` and `make lint`; then `make dev`. Tests use temporary data directories. For offline model smoke tests, set `VOICECOACH_DATA_DIR` to a temporary directory and `HF_HUB_OFFLINE=1`, and generate notes from synthetic meeting text. Cloud calls are mocked in automated tests to avoid sending recordings or incurring charges.

## Meeting processing history

The **Processing** detail tab reads `/api/recording/processing?id=...`. It groups trace events by run and shows start time/offset, duration, provider/model/revision, token counts, throughput, audio real-time factor, recorded Metal peak memory and available API cost. Expand older runs to compare regenerations. Active runs refresh every three seconds while this tab is visible; unfinished calls appear when their trace completes.

New local model loads have separate events. Manual notes regeneration and summary variants now have recording-scoped runs. Capture-time OCR traces follow the archived meeting's live ID, and continuation traces move to their parent meeting. Existing ungrouped calls remain visible. Histories are bounded to 50 runs and 2,000 events per response, with a truncation notice.

The endpoint exposes an allowlist of metrics and redacted errors, excluding prompts, responses, settings, arbitrary trace payloads and credentials. Token and cloud ASR usage is recorded when the provider supplies it. Costs show reported `cost_usd` if present; otherwise local execution has zero API charges and cloud/custom costs are “Not reported”. No current provider pricing is guessed. Process peak RSS is explicitly a lifetime high-water mark, distinct from the recorded Metal allocation peak. Historical gaps cannot be reconstructed; disabled or expired tracing is called out in the UI.

## Google Meet capture diagnostics

Meet capture combines macOS Accessibility with a browser JavaScript fallback in Chromium browsers. Accessibility may expose only the toolbar when the meeting tab is in the background. The fallback requires macOS Automation access and the browser's **View → Developer → Allow JavaScript from Apple Events** setting. Cora does not enable these settings automatically. Failures are now recorded in `capture_status.json` and shown in Participants instead of silently producing an empty roster.

The browser snapshot uses correctly escaped JavaScript and named speaking labels associated with participant tiles. Generic “Speaking” labels without an identifiable tile, or multiple simultaneous speakers, are not assigned to a guessed person. Names with initials and non-ASCII letters survive cleaning, and toolbar controls such as Video settings are excluded. Cloud speaker-name inference now receives its effective model ID and remains labelled as a guess.

Past meetings can display names already saved in `participants.json`, including initials that were previously filtered out. Missing capture-time speaker events cannot be recreated by this fix. Retranscribing may improve heuristic speaker naming using an existing roster, but does not reconstruct verified live turns. A live Meet call is needed to verify browser permission and speaking signals on the user's setup.

## People creation and Slack huddles

A participant can also be added to People straight from a meeting's Participants tab: the link dropdown on each row offers "Add <name> to People…", which creates the Person from the row's current (possibly edited) name, links that participant to it, and re-renders the rows so the new Person is selectable everywhere. Slack huddles in a browser are read from the huddle window's own participant tiles and title (0.3.2).

The People page now has an Add person form. Creation validates names and assigns a unique ID, so namesakes cannot overwrite an existing person's identity or metadata. Generic labels such as Participant and You are not attendee names; audio/video controls are rejected by both roster cleaning and the native watcher.

Slack in a Chromium browser is no longer skipped by the Meet-only window filter. Browser snapshots consider `app.slack.com` tabs as well as Meet tabs, scan all matching tabs, and accept only active calls. Slack roster extraction is limited to a huddle dialog/container with a Leave/End huddle control. The AX fallback likewise searches huddle containers in both native Slack and Slack browser windows. A DM title or chat-message author is not used as proof of call attendance. Names and speaking states still depend on semantic labels exposed by Slack, so live huddle validation remains necessary. The native helper includes pure parser self-tests (`capture/speaker-watch --self-test`).

The meeting detail page probes its own progress endpoint even when notes already exist. This detects reprocessing started elsewhere and keeps the reprocess button and progress panel in sync. Finished jobs reset the button; background callbacks from a different meeting cannot repaint it.
