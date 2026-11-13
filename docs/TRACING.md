# Local AI tracing

Every AI call Cora makes is recorded on your Mac in `traces.db` inside the data directory
(owner-only, `0600`). Nothing is uploaded; Langfuse is a separate opt-in mirror. The one exception
is the internal beta's Captured Recording, which carries its own runs and spans as
`run_metadata.json` with the span `input` and `output` columns left out (`python/capture.py`).

## What is recorded

| Kind | Where | Captured |
|---|---|---|
| `transcription` | local pipeline Whisper, voice-memo Whisper | audio fingerprint (size, head/tail SHA-256, duration), initial prompt, decode params, raw output with per-segment `avg_logprob` / `no_speech_prob` / `compression_ratio` / temperature, real-time factor |
| `llm` (local) | enhanced notes (one span per section and merge), summary variants, speaker naming | prompt, instruction, output, prompt/generation tokens, prompt & generation tokens/s, peak Metal memory, finish reason |
| `llm` (cloud) | `call_configured_llm` (Anthropic/OpenAI/custom/Gemini) and every Gemini `generate_content` call | request, response text, provider-reported token usage, latency |
| `ocr` | screenshot OCR (Apple Vision) | image fingerprint, text |

Spans are grouped into **runs** (one pipeline execution over one recording). Each run stores the
app version, git commit (and whether the tree was dirty), `PIPELINE_VERSION`, hardware (chip, RAM,
macOS) and the model-affecting settings. Each span stores the model id plus the exact weights
revision (Hugging Face snapshot commit, or a fingerprint of a local checkpoint) and a hash of the
prompt template — so a change in quality or speed can be traced to the model, prompt, code or
machine that caused it.

Audio and image bytes are never stored — only fingerprints that point back at the recording's
own files.

**Human corrections** made in the transcript editor (who spoke a turn, fixed wording) are logged to
a `corrections` table with the turn's timestamps — the best retraining labels there are.

## Using it

```bash
python tools/traces.py stats --days 30          # benchmark table per model / weights / prompt version
python tools/traces.py runs                     # recent pipeline runs with versions
python tools/traces.py show <run-id-prefix>     # every call in one run
python tools/traces.py export llm.jsonl --kind llm --name 'enhanced_notes.%'
python tools/traces.py export fixes.jsonl --corrections
```

Exports contain meeting content: keep them as private as the recordings.

## Configuration (`config.json`)

```json
"local_tracing": {"enabled": true, "store_payloads": true, "retention_days": 180}
```

- `store_payloads: false` keeps only metrics and versions (no prompts, transcripts or outputs).
- Traces for a recording can be removed with `ai_trace.purge_recording(id)`.
- Bump `PIPELINE_VERSION` in `python/ai_trace.py` whenever pipeline structure changes.

## Usage events (beta)

Separate from the traces above: small, metadata-only records of what happened in an Install,
sent to the Cora team's receiver during the internal beta. What a teammate is told about them:
`docs/BETA_POLICY.md`. Spec: `docs/specs/beta-telemetry-and-updates.md`.

### Catalog

`python/usage_events.py` `CATALOG` is the whole list. `record()` (and `POST /api/events`, which
Electron main and the renderer use) refuses an unknown event or key, a value that is not a
string, number, boolean or null, and a string over 200 characters (500 for `feedback.comment`).
Keys may be missing; extra keys may not.

| Event | Keys | Emitted by |
|---|---|---|
| `app_started` | `macos`, `chip`, `ram_gb`, `processing_mode`, `microphone_kind` (`default`\|`named`), `lockdown` | Electron main, once per launch |
| `recording_started` | `recording_id`, `meeting_app`, `surface`, `microphone_kind` | Recording session |
| `recording_stopped` | `recording_id`, `meeting_app`, `surface`, `duration_s`, `chunks`, `pauses`, `mic_reconnects`, `ended_by` | Recording session |
| `participants_captured` | `recording_id`, `count`, `method`, `warnings`, `linked_people` | Recording session |
| `processing_finished` | `recording_id`, `status` (`ok`\|`error`), `error_code`, `transcriber_provider`, `transcriber_model`, `text_provider`, `text_model`, `transcription_s`, `summarization_s`, `total_s`, `tokens_in`, `tokens_out`, `window_fallbacks`, `speech_s`, `silence_s`, `retries`, `peak_rss_mb`, `duration_s` | `python/usage_emitters.py`, once per processing run; also where Captured Recording sampling happens |
| `notes_viewed` | `recording_id` | notes view |
| `notes_edited` | `recording_id`, `edit_ratio` (0..1) | notes view |
| `transcript_corrected` | `recording_id`, `corrections` | transcript editor |
| `action_items_counted` | `recording_id`, `count` | notes view |
| `notes_exported` | `recording_id`, `kind` (`copy`\|`export`); for `export` also `content` (`notes`\|`notes_transcript`), `notepad` (the file has a My notes section), `outcome` (`saved`\|`cancelled`\|`failed`) | notes view and transcript (`copy`); the Export button (`export`), once per export attempt; never a title, path or text |
| `manual_notes_written` | `recording_id`, `chars`, `phase` (`during`\|`after`) | Recording session, notes view |
| `screenshot_taken` | `recording_id`, `count`, `ocr` | Electron main |
| `person_added` | `source` (`people_page`\|`participants_tab`) | People page, Participants tab |
| `setting_changed` | `key`, `value` | renderer `saveSetting`: keys matching key/token/secret/password are never sent; Microphone is `default`\|`named`; booleans and numbers as strings; a few choice keys (`processing_mode`, model and engine choices) verbatim; any other text only `set`\|`cleared` |
| `people_snapshot` | `people`, `recordings`, `disk_mb` | server start, at most once per 24 h |
| `error` | `scope` (`main`\|`capture`\|`server`\|`pipeline`), `code` | Recording session (`capture`); API router, unhandled route exceptions (`server`, code = exception class name) |
| `feedback` | `recording_id`, `target` (`recording`\|`notes`\|`overall`), `rating` (`up`\|`down`), `reasons` (comma-joined), `comment` (≤ 500) | `POST /api/feedback` |
| `events_dropped` | `count` | queue limits (below) |
| `capture_dropped` | `recording_id`, `reason` (`feedback`\|`sample`) | a Captured Recording not uploaded within 7 days |
| `update_available` | `from_version`, `to_version` | `src/updater.js`, once per new version seen |
| `update_started` | `from_version`, `to_version` | Update clicked |
| `update_finished` | `from_version`, `to_version`, `status` (`ok`\|`error`), `error_code` | after the install step |
| `call_detected` | `app` (the Call's label, e.g. `Google Meet`, `Slack Huddle`), `trigger` (`mic`\|`poll`\|`followup`: what found the Call), `confirmed` (the page or app said the Call is live), `seconds_to_prompt` (whole seconds from the mic turning on to the prompt; null when the mic was not on first) | Electron main (`src/main/call-detection.js`), once per Call detected, before the prompt; no URL, title or names |
| `call_prompt_action` | `action` (`start`\|`dismiss`\|`expired`: Start recording clicked, Dismiss clicked, or the Call ended or a Recording started elsewhere) | Electron main, once per Call prompt, when it closes |
| `detect_fallback` | `reason` (`ax_untrusted`: Accessibility not granted, desktop apps fall back to the process alone; `js_events_off`: a browser refuses "Allow JavaScript from Apple Events") | Electron main, at most once per reason per app run; no app or browser names |

### Where they live on the Mac

- Table `usage_events` (`id`, `created_at`, `name`, `payload` JSON, `sent_at`) in `voicecoach.db`.
  Every event is written whatever the share toggle says; `sent_at` is set once the receiver took it.
- Retention: `usage_events.prune_local(days=30)` deletes rows older than 30 days, sent or not.
  In 0.4.0 nothing calls it yet, so rows stay until it is wired in.
- **Settings > Beta > Show what Cora shares** (`GET /api/events/export`) writes every row, sent and
  unsent, to `<data>/usage-events-export.jsonl` (`id`, `name`, `ts`, `payload`, `sent_at`) and
  reveals it in Finder.
- `GET /api/beta/status` → `sharing_enabled`, `unsent_events`, `pending_captures`,
  `last_flush_at`, `last_error`.

### The sender (`python/beta_sender.py`)

Nothing is sent unless `usage_events.sharing_enabled()`: the `share_usage` setting is on (default
on for `team` builds, off for `public`), enterprise lockdown is off, and the build carries
`CORA_BETA_RECEIVER_URL` and `CORA_BETA_TOKEN`. Events and Captured Recordings also need the remote
config's `telemetry_enabled`.

- At server start: fetch the remote config once (`GET /v1/config`, cached in
  `<data>/remote_config.json`; defaults `telemetry_enabled: true`, `capture_sample_rate: 0.25`,
  `capture_max_minutes: 60`, `min_app_version: null`), then flush.
- Then every `CORA_TELEMETRY_FLUSH_SECONDS` (600) while unsent rows exist, right after each
  Feedback (`flush_now()`), and once on shutdown (SIGTERM, bounded to 5 s, events only).
- A flush posts batches (`pending_batch()`, about 5 MB each, oldest first) to `POST /v1/events`
  until none are left, then uploads at most one pending Captured Recording to
  `POST /v1/recordings`.
- A failed batch leaves its rows unsent and applies the queue limits: unsent rows older than 7
  days, then the oldest unsent rows beyond 5 MB, are deleted and one `events_dropped {count}` is
  recorded. The limits are applied only after a failed flush.
- Captured Recordings waiting more than 7 days are dropped (one `capture_dropped` each) at the
  start of every flush, even when nothing can be sent.

### The batch envelope and the display name

Every `POST /v1/events` batch (`usage_events.pending_batch()`) wraps its events with the Install's
identity: `install_id`, `display_name`, `app_version`, `git_commit`, `build_variant`. Captured
Recording uploads carry the same name in the `X-Cora-Display-Name` header (percent-encoded). The
name is read when the batch is sent, so events queued earlier go out under the current name.

`display_name` is the `beta_display_name` setting (**Settings > Beta**), at most 100 characters,
`null` when empty. **It is personal data** (usually a real, often full, name) and is the only
field that names a person in usage telemetry. In `team` builds `usage_events.seed_display_name()`
fills it once from the user's own name (`api.core.current_self_name()`: the onboarding name, or
the self Person) when it is empty: from `POST /api/onboarding/name`, and at server start for
Installs that onboarded before 0.4.4. A `beta_display_name_seeded` flag makes it one-shot, so a
name the user clears stays cleared. Never in `public` builds, never under lockdown. On the
receiver it is stamped onto every event line in `<root>/events/YYYY-MM-DD.jsonl` and into each
Captured Recording's `meta.json`, kept for the beta (`docs/BETA_POLICY.md`).

### The receiver and the report

The Cora team's side is `receiver/receiver.py`: endpoints, disk layout, launchd, Tailscale Funnel,
token rotation and the remote config file are in `receiver/README.md`.
`python tools/usage_report.py <receiver-root> [--since DAYS]` prints the per-version Markdown
report from what the receiver stored.

### Audio pruning log

Each audio pruning pass (`python/audio_pruning.py`; see `docs/processing.md`) appends one line to
`<data>/logs/audio_pruning.jsonl`: `at`, `retention_days`, `cap_mb`, `removed`, `by_age`, `by_cap`,
`skipped`, `bytes_freed`, and `pruned` (`recording_id`, `reason` `retention`\|`cap`, `bytes`); a
pass that raised logs `at` and `error` instead. The log stays on the Mac.
