# Diagnostics at release scale

What we need so a failure on a teammate's or a customer's Mac can be read from the Studio without a screen share. Written after the first team install (2026-11-11): the capture helper died with "code null" and nothing on our side said why. Status of each item is in `docs/TODO.md`.

## Principles

- **The app explains itself before it asks for help.** Every failure the app can detect maps to a message that names the fix ("Screen Recording is off"), never a code.
- **Metadata by default, content on request.** Usage events (already shipped) carry codes, signals, permission states and versions. Logs and audio leave the Mac only through an explicit Send diagnostics or a Feedback rating (see `docs/BETA_POLICY.md`).
- **One place to look.** Everything lands in the receiver root on the Studio; `tools/usage_report.py` is the daily view.

## Layer 1: make failures self-describing (ship first)

1. **Signal and stderr for every helper death.** Capture stderr of `dual-capture` into the per-recording log; put the signal into the warning and into the `error {scope: capture}` event (`helper_killed_SIGABRT`, `helper_killed_SIGKILL`). SIGABRT means a Swift or TCC abort, SIGKILL means code signing or the OS.
2. **Permission snapshot in events.** `recording_started` and `app_started` carry `{mic, screen, accessibility, automation}` from the existing `get-permission-status` IPC. Most first-day failures are grants.
3. **Preflight before recording.** `dual-capture --preflight` opens the mic and ScreenCaptureKit for one second and exits with a specific code. The session runs it first and shows the matching message; the real helper only starts when preflight passes.
4. **Crash reports of our binaries.** On app start, look in `~/Library/Logs/DiagnosticReports` for `dual-capture-*`, `speaker-watch-*`, `mic-watch-*` and `Cora*` reports newer than the last check; emit one `crash_report` event per report with exception type, signal, termination reason and the top five frames (no paths beyond the bundle, no user data). Electron main and renderer crashes: `crashReporter.start({ submitURL: <receiver>/v1/crashes })` is a two-line add; the receiver stores the minidump beside the install's events.

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
