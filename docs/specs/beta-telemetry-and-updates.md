---
title: Beta usage telemetry, feedback, captured recordings and in-app updates
status: ready-for-agent
created: 2026-11-11
plan_item: team beta (cora-launch), pre-release
glossary: Install, Usage event, Feedback, Captured Recording, Recording, Recording session, Processing queue, Stage, Participant, Person, Provider, Transcriber, Text model, Window
---

# Beta usage telemetry, feedback, captured recordings and in-app updates

## Problem Statement

Cora is about to go to the Sutra team as a beta. Today everything the app learns stays on each
teammate's Mac: `traces.db` has per-run timings, models and errors, the resource log has per-stage
seconds, and transcript corrections are logged. Nothing records what people do in the app (start,
cancel, open notes, edit, export), nothing records what they think of the output, and none of it
reaches the Cora team. Packaged builds also write an empty app version into runs, so even the local
data cannot be split by version.

Updating is manual: re-run the install command. The app never says a newer version exists, so
fixes shipped during the beta reach nobody until they are told on Slack.

Teammates' Macs will also fill up: audio is kept forever, and a week of calls is several gigabytes.

## Solution

During the beta each Install sends metadata-only Usage events to a receiver the Cora team runs on
the Mac Studio, reachable over a public Tailscale Funnel address. Events carry counts, durations,
versions, models and error codes; never titles, names, transcripts or note text. A Feedback widget
on every Recording lets a teammate rate the Recording, the Notes or the whole thing, with fixed
reasons and an optional comment; a rating always attaches the Recording in full as a Captured
Recording, and one in four Recordings under an hour is captured anyway, at a rate the team can
change remotely. Audio older than 30 days, or beyond 500 MB in total, is pruned on each Mac while
transcripts and notes stay. A beta policy document and the Settings toggle label say all of this in
one line each. The app checks GitHub Releases for a newer version and offers a one-click update
that never runs while a Recording session or the Processing queue is busy. Everything outbound is
vetoed by enterprise lockdown.

## User Stories

1. As the Cora team, I want every Install to send Usage events, so that I can see how the beta is used without asking.
2. As the Cora team, I want events batched and flushed every 10 minutes, on start, on quit and at once for Feedback, so that the data is fresh without chatter.
3. As the Cora team, I want each event stamped with app version and commit, so that I can compare versions.
4. As the Cora team, I want packaged builds to stamp the real version into runs and events, so that per-version reports are possible at all.
5. As the Cora team, I want a random Install id and an optional self-typed name, so that I can attribute data to a teammate without collecting emails or machine names.
6. As a teammate, I want a "Your name for the Cora team" field in Settings, so that my feedback is recognisable.
7. As a teammate, I want a Settings toggle "Share usage and sample recordings with the Cora team", on by default in team builds, so that I can switch it off.
8. As a teammate in a public build, I want that toggle off by default, so that nothing leaves my Mac unless I say so.
9. As an admin, I want enterprise lockdown to veto telemetry, Feedback upload, Captured Recordings and the update check, so that the one switch still means nothing leaves the Mac.
10. As the Cora team, I want an app_started event with version, commit, macOS, chip, RAM, processing mode, Microphone kind and lockdown state, so that I know the fleet.
11. As the Cora team, I want recording_started and recording_stopped events with meeting app, browser or native, duration, Chunk count, pause count, mic reconnects and how it ended, so that I can see capture reliability.
12. As the Cora team, I want a participants_captured event with count, capture method, warnings count and linked-to-Person count, so that I can see whether roster capture works for others.
13. As the Cora team, I want a processing_finished event with per-Stage seconds, Transcriber and Text model with Provider, tokens, Window fallback count, speech versus silence seconds, status, error code, retries and peak memory, so that I can see pipeline health and cost.
14. As the Cora team, I want notes_viewed and notes_edited (edit ratio against the generated text), transcript correction counts and action item counts, so that I can see whether notes are used and trusted.
15. As the Cora team, I want manual_notes_written (character count, during or after) and screenshot_taken (count, OCR ran) events, so that I know which capture features matter.
16. As the Cora team, I want person_added and setting_changed events, so that I can see People adoption and which settings people touch.
17. As the Cora team, I want setting_changed to omit secrets and to send the Microphone only as "default" or "named", so that no key or device name leaves the Mac.
18. As the Cora team, I want a daily people_snapshot with People count, Recordings count and disk used, so that I can size things.
19. As the Cora team, I want error events by code without message text, so that I can see failure classes without content.
20. As a teammate, I want a Feedback widget at the top of a Recording's notes view with targets Recording, Notes and Overall, so that I can say what was wrong.
21. As a teammate, I want thumbs up or down, fixed reasons (missed items, wrong items, wrong speakers, too long, other) and an optional comment up to 500 characters, so that feedback takes seconds.
22. As a teammate, I want a one-line reminder next to the comment not to include customer names, so that I do not leak client data.
23. As a teammate, I want a general "Send feedback" box in Settings not tied to a Recording, so that I can report anything.
24. As the Cora team, I want every rating to attach the Recording in full as a Captured Recording, so that I can check accuracy against the audio.
25. As the Cora team, I want one in four Recordings under 60 minutes captured without a rating, with the rate and the length cap set from the remote config, so that I get a sample without a release.
26. As the Cora team, I want a Captured Recording to hold mic and system audio tracks, transcript, speaker timeline, Participants roster, generated notes and run metadata, and nothing else, so that review is complete and bounded.
27. As a teammate, I want the beta policy document and the toggle label to say that ratings and a sample of recordings are sent to the Cora team, so that nothing is hidden.
28. As the Cora team, I want a remote config fetched at start with telemetry on or off, sample rate, length cap and minimum app version, so that I can steer the beta without shipping.
29. As the Cora team, I want events to wait up to 7 days or 5 MB and Captured Recordings up to 7 days when the receiver is unreachable, then be dropped with a dropped event, so that an offline Studio costs little and is visible.
30. As a teammate, I want a local copy of every event for 30 days and a "Show what Cora shares" link in Settings, so that I can see exactly what left my Mac.
31. As a teammate, I want audio older than 30 days pruned, and the oldest audio pruned first when total audio exceeds 500 MB, with transcript, notes and timeline kept, so that my disk does not fill.
32. As a teammate, I want pruning never to touch a Recording that is processing or in a failed Stage, and to tell me once when it ran, so that nothing in flight is lost.
33. As the Cora team, I want a receiver on the Mac Studio that checks a bearer token, writes events as daily JSONL files and Captured Recordings as folders, and serves the remote config from a hand-edited file, so that the backend is one process and a directory.
34. As the Cora team, I want the receiver run by launchd and exposed by Tailscale Funnel, so that teammates need no client setup.
35. As the Cora team, I want a report script over the receiver directory with active Installs, recordings per person, failure rate, time to notes, local versus cloud mix, thumbs ratio, corrections per transcript and the comment list, per version, so that a weekly review takes a minute.
36. As a teammate, I want a banner "Cora X.Y.Z is available" with an Update button, so that I get fixes without instructions.
37. As a teammate, I want Update to download the dmg from the GitHub Release, verify its sha256, replace the app and relaunch, so that updating is one click.
38. As a teammate, I want the Update button disabled with a reason while a Recording session is live or the Processing queue is busy, so that an update never cuts a meeting.
39. As a teammate, I want "Later" to snooze the banner for 24 hours, so that it does not nag.
40. As the Cora team, I want the banner undismissable below the minimum version, while the update still only runs on click, so that broken builds get retired.
41. As the Cora team, I want update_available, update_started and update_finished events, so that I can see rollout.
42. As a teammate under enterprise lockdown, I want no update check at all, so that the lockdown promise holds.

## Implementation Decisions

**Ownership.** The Python API server owns the Usage event store, the sender, the remote config,
Feedback, Captured Recording upload and audio pruning: it already owns the local DB, tracing and
the Processing queue, and the lockdown policy module lives there. The Electron main process owns
the update feature (it must replace its own bundle and relaunch) and reports its own events to the
server over the existing authenticated local API. The renderer reports UI events the same way.

**Install identity.** A new `install_id` setting, a random UUID created on first use by the server,
and a nullable `beta_display_name` setting shown in Settings as "Your name for the Cora team".
Both ride on every batch, never per event.

**Share toggle.** A `share_usage` setting. Its default comes from the build variant: team builds
(the `--team` flag, which already sets the default processing mode) default it on; public builds
default it off. Onboarding does not mention it. The server treats the toggle as off whenever
enterprise lockdown is on, using the policy module's existing outbound check, and never calls the
receiver in that state.

**Usage event store.** A `usage_events` table in the local DB: id, created_at, name, payload
(JSON), sent_at. Events are written locally regardless of the toggle; the toggle only governs
sending. Rows older than 30 days are deleted. "Show what Cora shares" reveals a JSONL export of
unsent and sent rows in the data directory.

**Event catalog.** Names and payload keys are fixed in one module and documented in the tracing
doc. Every payload is validated against an allow-list of keys with scalar values; a payload that
carries a string longer than 200 characters, except the Feedback comment, is rejected at the API.
`setting_changed` strips API keys and reduces the Microphone to `default` or `named`.
`recording_stopped` reports the meeting app as one of Meet, Zoom, Slack, Teams, unknown, with
`surface` browser or native. `processing_finished` is emitted by the Processing queue when a job
ends, from the run row that tracing already writes, so the two agree by construction.

**Version stamping.** The packaged app cannot read `package.json` from the app root, which is why
runs carry an empty version. The Electron main process passes the app version and commit to the
Python server in its environment at spawn; the tracing module and the event sender read those
first and fall back to the repo lookup when running from source. The commit is embedded at build
time by the build script.

**Sender.** A background thread in the server flushes unsent events as one batch: at server start,
on a graceful shutdown request from Electron, immediately after a Feedback row is written, and
every 10 minutes while unsent rows or pending captures exist. A batch is a JSON document with
install id, display name, app version, commit and the events. On any failure the rows stay unsent.
Before every flush, and on every tick while sharing is off, unsent rows older than 7 days, or
beyond 5 MB of unsent payload, are deleted oldest first and a single `events_dropped` event with
the running count is kept, so turning sharing back on sends at most 7 days / 5 MB of backlog.

**Remote config.** Fetched once at server start from the receiver, cached in the data directory,
used until the next start. Keys: `telemetry_enabled`, `capture_sample_rate` (default 0.25),
`capture_max_minutes` (default 60), `min_app_version`. A missing or failed fetch uses the cached
copy, then the defaults.

**Feedback.** A `feedback` table: id, recording_id (nullable for general messages), target
(`recording`, `notes`, `overall`), rating (`up`, `down`), reasons (JSON list from the fixed set),
comment (max 500 characters), created_at. Writing a row emits a `feedback` event (target, rating,
reasons, comment, recording id) and, when the row has a Recording, queues a Captured Recording for
it. The notes view shows one widget at the top with the three targets; Settings has a general
message box.

**Captured Recording.** A capture job builds a tar archive of the Recording folder limited to the
audio tracks, transcript, speaker timeline, Participants file, generated notes and the run's
metadata, and uploads it to the receiver with the install id, Recording id, reason (`feedback` or
`sample`) and app version. Sampling happens when `processing_finished` is emitted: a Recording is
sampled when its duration is under `capture_max_minutes` and a per-Recording random draw is under
`capture_sample_rate`; a Recording is captured at most once. Pending captures wait up to 7 days,
then are dropped with a `capture_dropped` event. Uploads run one at a time on the sender thread
after the event batch. Nothing is captured under enterprise lockdown or with the toggle off.

**Audio pruning.** Settings `audio_retention_days` (default 30) and `audio_cap_mb` (default 500),
both editable. A pruning pass runs at server start and after every Processing queue job: delete
the audio tracks of Recordings older than the retention, then, while total audio exceeds the cap,
delete the oldest remaining audio. Recordings in the processing or failed Stages, and any Recording
with a pending capture, are skipped. The Recording row records that its audio was pruned so the UI
can show "audio removed" instead of a broken player. One notification per pass that removed
anything, through the existing notifications table.

**Receiver.** A standalone Python program in the repo, run from source on the Mac Studio by a
launchd agent and exposed with `tailscale funnel`. Endpoints: `POST /v1/events` (batch), `POST
/v1/recordings` (tar upload with metadata headers), `GET /v1/config`. A static bearer token, set in
the receiver's environment and embedded in team builds by the build script, guards the two POST
routes. Events append to `events/YYYY-MM-DD.jsonl`; a Captured Recording lands under
`recordings/<install_id>/<recording_id>/` with a sidecar of its metadata; the config is read from
`config.json` on every request. The receiver never reads the archives it stores. A setup document
covers launchd, Funnel and rotating the token.

**Report.** A script over the receiver directory that prints, per app version: active Installs,
Recordings per display name, processing failure rate, median time from stop to notes, local versus
cloud share, thumbs up ratio by target, corrections per transcript, Captured Recording count, and
the comment list with install name and Recording id. Markdown output.

**Update feature.** An Electron main module checks the GitHub Releases latest tag at start and every
6 hours, skipped under enterprise lockdown. When the tag is newer than the running version it
emits `update_available` and tells the renderer, which shows a banner with Update and Later. Update
downloads the dmg and its sha256 from the release into a temporary directory, verifies the hash,
mounts the dmg, copies the bundle over the installed one with the same steps the install script
uses, unmounts, emits `update_started` and `update_finished`, then relaunches. The button is
disabled with a reason while the Recording session is not idle or the Processing queue has a
running or pending job. Later hides the banner for 24 hours. When the running version is below
the remote config's `min_app_version`, Later is absent and the banner stays until updated. A
failed update leaves the installed app untouched and shows the error in the banner.

**Documents.** A beta policy document, linked from the team setup document and from the Settings
toggle, states in plain language what is sent (Usage events, every rated Recording, one in four
Recordings under an hour), where it goes (a machine run by the Cora team), who sees it (the Cora
team), that audio on each Mac is kept 30 days or 500 MB, and how to turn sharing off. The team
setup document gains one line under install and replaces the Updating section with the in-app
update. The tracing document gains the event catalog.

## Testing Decisions

A good test drives the system from the outside, through the surfaces the app itself uses, and
asserts on what a teammate or the Cora team would observe: rows in the local DB, files under the
receiver directory, the text of a banner, a refused request. Tests never reach into the sender's
thread state or the updater's internals.

Seams, all existing:

- **The API server over HTTP**, started in-test against a throwaway data directory, with a stub
  receiver started by the test (prior art: the audio devices API tests). Covers: events accepted
  and stored, invalid payloads refused, flush rules (start, after Feedback, the 10-minute timer
  shortened by an environment override), batch shape, lockdown refusal, drop limits, remote config
  caching and defaults, Feedback rows and the capture job they queue, sampling under a fixed random
  seed, archive contents, pruning on a fixture of Recording folders with mixed ages and Stages, the
  version stamp when the Electron environment variables are present.
- **The receiver as its own process over HTTP** (same harness shape): token required, events land
  in the day file, an upload lands in the right folder with its sidecar, config served from file,
  oversized or malformed uploads refused.
- **Electron main modules under node:test** with stub HTTP servers and a stub installer command
  (prior art: the capture-helper tests): version comparison, 6-hour and start checks, the
  lockdown skip, the busy guard against a stubbed Recording session and Processing queue, snooze,
  the minimum-version rule, sha256 verification failure leaving the install untouched, and event
  reporting to a stub API.
- **Renderer scripts in a Node VM DOM** (prior art: the microphone UI tests): the Feedback widget
  posts the right body and attaches by default, the comment cap and reminder, the general message
  box, the Settings toggle and name field, the update banner states, "Show what Cora shares".
- **The report script** against a fixture receiver directory, asserting on the printed table.

## Out of Scope

- Any dashboard or hosted analytics product; the report script is the reading surface.
- Automatic, silent updates and any Squirrel or electron-updater path; those need an Apple
  Developer ID the project does not have.
- Capturing screenshots, manual notes or People entries inside a Captured Recording.
- Uploading anything under enterprise lockdown, or from public builds unless the toggle is on.
- Multi-user accounts, server-side authentication beyond the shared token, and the public launch
  telemetry policy, which is decided separately before launch.
- Deleting whole Recordings; pruning removes audio only.

## Further Notes

- The receiver and the sampled capture exist for the internal beta only. Before any external beta
  the sample rate goes to zero in the remote config and the policy document is rewritten; the
  per-rating attachment becomes an explicit checkbox at that point.
- The Captured Recording archive reuses the Recording folder layout as is, so the research tools
  that compare engines already read it.
- The shared token is a beta convenience, not a security boundary: anyone with a team build can
  post events. Rotation is a config edit on the receiver and a rebuild.
- Implement the version stamp first; every report depends on it.
