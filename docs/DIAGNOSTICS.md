# Diagnostics at release scale

What we need so a failure on a teammate's or a customer's Mac can be read from the Studio without a screen share. Written after the first team install (2026-11-11): the capture helper died with "code null" and nothing on our side said why. Status of each item is in `docs/TODO.md`.

## Principles

- **The app explains itself before it asks for help.** Every failure the app can detect maps to a message that names the fix ("Screen Recording is off"), never a code.
- **Metadata by default, content on request.** Usage events (already shipped) carry codes, signals, permission states, versions and performance numbers (CPU, memory, stage times). Logs and audio leave the Mac only through an explicit Send diagnostics or a Feedback rating (see `docs/BETA_POLICY.md`).
- **One place to look.** Everything lands in the receiver root on the Studio; `tools/usage_report.py` is the daily view.

## Layer 1: make failures self-describing (ship first)

1. **Signal and stderr for every helper death.** Capture stderr of `dual-capture` into the per-recording log; put the signal into the warning and into the `error {scope: capture}` event (`helper_killed_SIGABRT`, `helper_killed_SIGKILL`). SIGABRT means a Swift or TCC abort, SIGKILL means code signing or the OS.
2. **Permission snapshot in events.** Shipped in 0.4.5: `recording_started` and `app_started` carry `perm_mic`, `perm_screen`, `perm_accessibility`, `perm_automation` (granted/denied/unknown) from the same status as the `get-permission-status` IPC. Most first-day failures are grants. Still open: automation (Apple Events to the browsers) has no status API that does not prompt, so it reads `unknown`; a probe could report it from the detector's `-1743` errors.
3. **Preflight before recording.** `dual-capture --preflight` opens the mic and ScreenCaptureKit for one second and exits with a specific code. The session runs it first and shows the matching message; the real helper only starts when preflight passes.
4. **Crash reports of our binaries.** Shipped in 0.4.5 (`python/crash_reports.py`): at server start Cora reads `~/Library/Logs/DiagnosticReports` for `.ips` reports of `dual-capture`, `speaker-watch`, `mic-watch`, `mac-ocr`, the Cora app and its helpers (main, renderer and GPU crashes included, since macOS writes those too) and our bundled Python, newer than the last check, and emits one `crash_report` event per report: process, exception type, signal, termination reason and up to five symbol names from our own binaries. No paths, addresses or anything else from the report.

   **Decision: no Electron `crashReporter` / minidump upload.** A minidump holds a slice of process memory, which in Cora can contain transcript text, notes or people's names. Sending it would break the beta policy (metadata by default, content only on the user's click) and the controls under the ongoing SOC 2 audit. The `.ips` reduction above covers what we need to triage; a minidump is only ever looked at on the user's own Mac or sent through an explicit Send diagnostics.

## Layer 2: send diagnostics on request

- **Settings > Notifications & logs > Send diagnostics.** Packs `logs/`, the notifications table, `build-info.json`, the permission snapshot, the processing preferences (keys redacted) and the last 200 usage events into a tar.gz and POSTs it to `POST /v1/diagnostics` with the beta token. Shows the bundle id so the user can quote it.
- **Feedback already sends the Recording** (audio, transcript, run metadata); add the per-recording log and the pipeline log for that run to the Captured Recording archive, since a bad transcript is usually explained there.
- Receiver layout: `diagnostics/<install>/<bundle-id>.tar.gz` plus `meta.json`, same pruning rules as recordings.

## Layer 3: release gates (before a dmg goes out)

1. **Fresh-account smoke.** A second macOS user account on the Studio with no Cora data: run `scripts/install.sh` from the published release, grant the three permissions, record 30 s of a Meet tab, let it process, open the notes, rate it. Scripted in `docs/operations/release-smoke-checklist.md`; the manual steps are the grants.
2. **Oldest supported macOS.** We build on the newest macOS; the team is one major behind. Keep one machine or VM on the minimum we claim (`LSMinimumSystemVersion` 14.0) and run the smoke there too, since ScreenCaptureKit and TCC behave differently across majors.
3. **Automated.** `npm test`, `uv run pytest tests/ -q`, `uv run ruff check`, plus the helper test suite with a stub that dies by signal (asserts the signal reaches the event).
4. **Release note is the checklist.** `dist/RELEASE-NOTES-<version>.md` lists what the smoke covered and on which macOS.

## Layer 4: watch the fleet

- `tools/usage_report.py` gains an **Errors** section: per install, the last `error`, `crash_report` and `processing_finished {status: failed}` events, with version and macOS. A new install with no `recording_stopped` within a day of `app_started` is listed as "never recorded".
- A small launchd job on the Studio runs the report nightly and writes `reports/YYYY-MM-DD.md`; anything in the Errors section is the morning's first look.
- Remote config already reaches every app (`GET /v1/config`): use it to raise the flush interval or disable captures fleet-wide without a release.

## What stays out

- No third-party crash or analytics service while the SOC 2 audit runs and customer data is on these Macs; the receiver is ours and on the tailnet.
- No automatic log upload. Logs can contain meeting titles and names; they leave the Mac only on the user's click.
- No remote shell or screen access.
