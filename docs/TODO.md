# Known issues and todos

Diagnosed, not yet fixed. Each entry says what was observed, the cause found in the code or logs, and the fix we expect. Dated so the evidence can be re-checked.

## Participants not updated when switching huddles mid-recording (2026-11-11)

**Observed.** A recording began on a DM huddle (roster: one name, correct), the user left it and joined a second huddle with two more people while still recording; the roster stayed at one name.

**Cause.** Both huddles were collapsed to Slack's bottom mini-bar in Brave, where the page holds no participant tiles. The only name source there is the mini-bar title: "Huddle with <Name>" names the DM party, but the second huddle's title was just "Huddle", which names nobody (log `speaker-watch-meeting_2026-11-11T06-00-43-016Z.log`: two MEETING_TITLE lines, no SPEAKER_ACTIVE, no roster writes). The Accessibility fallback could not help: every scan logged `AXError -25211`, meaning the installed app is still not trusted under System Settings > Privacy & Security > Accessibility.

**Fix.** Two parts. (1) Product: when a Slack huddle is detected collapsed, nudge once in the floater: "Expand the huddle window so Cora can see who is in it", since Slack exposes names only in the expanded window. (2) Watcher: when the huddle title changes (a new huddle), re-run the roster snapshot immediately rather than waiting for the next scan, and keep both huddles' names in the roster. Independently, grant Accessibility to the installed app so the native fallback works for Zoom and the Slack desktop app.

## Capture helper death is undiagnosable remotely (2026-11-11)

**Observed.** On a teammate's first-day install (0.4.0, M3 Pro, one macOS major behind the build machine) every recording attempt ended within a second with "Recording stopped unexpectedly (capture helper exited with code null)", then "No audio was found". Eight `dual-capture` crash reports in four minutes, including from the `--list-devices` call Settings makes.

**Cause (found, fixed in 0.4.1).** Running the helper by hand on his Mac printed it: dyld "Symbol not found" in CoreMedia, "built for macOS 27.0 which is newer than running OS". The Makefile compiled the Swift helpers with no `-target`, so they were linked against the build Mac's macOS. Fixed by `-target arm64-apple-macos14.0` and a check in `scripts/build-app.sh` that each helper's `minos` equals `LSMinimumSystemVersion`.

**Still open: the app told us nothing.** Code null means a signal death without an `Error:`/`Failed:` line. `capture-helper.js` pipes only speaker-watch's stderr into the per-recording log, the helper's own stderr (where dyld printed the whole answer) is dropped, and `onHelperExit` puts the exit code but not the signal into the warning and the `error {scope: capture}` event. **Fix.** (1) Write the capture helper's stderr into the same per-recording log and the first stderr line into the warning, (2) include the signal name in the event (`helper_killed_SIGABRT`), (3) emit a `permissions` payload at recording start, (4) a `--preflight` mode that opens the mic and ScreenCaptureKit for one second so a dead helper is reported before a Recording starts. See `docs/DIAGNOSTICS.md`.

## Onboarding step 5 cannot be scrolled to its top (2026-11-11)

**Observed.** On a 14-inch screen the "Models & privacy" step is taller than the window; the user could scroll down but never back to the top of the card (seen live on a teammate's screen share).

**Cause.** `.onboarding-overlay` is `display:flex; align-items:center; overflow-y:auto`. A flex item centered in a container shorter than itself overflows equally above and below, and the part above the container's origin is unreachable by scrolling. Classic centered-overlay bug.

**Fix.** Keep the overlay scrollable but center safely: `align-items:flex-start` on the overlay and `margin:auto` on `.onboarding-card` (or `align-items: safe center`). One CSS line.

## Onboarding step 5 presents local models as a required choice (2026-11-11)

**Observed.** The last onboarding step shows the full processing-controls block (mode, template, model and engine overrides, a "Save processing defaults" button) plus two radio lists of Whisper and Liquid models with sizes. A new teammate on the cloud default read it as "pick and download a model to finish".

**Cause.** `loadOnboardingModels` always renders `#onboardingProcessing`, `#onboardingWhisperOptions` and `#onboardingLiquidOptions`, regardless of the processing mode, and the embedded controls carry their own Save button although Finish setup saves everything. The team build defaults to cloud, so the local lists are irrelevant on first run.

**Fix.** Render the step as: processing mode + notes template + the keep-audio toggle. Show the Whisper/Liquid lists only when mode is a local one (toggle on the mode select), and hide the embedded "Save processing defaults" button inside onboarding (`loadProcessingControls` gets an `embedded` flag). Rename the step "Processing & privacy". Keep the "models download on first use" line.

## Teams desktop still counts as a Call from the bare process (2026-11-11)

**Observed.** `MEETING_APP_PROCESSES` treats a running `Microsoft Teams` / `Teams` process as a Call, so the 20s backstop poll can prompt whenever Teams is merely open. Zoom and Slack desktop are being moved to window- and control-based liveness in the follow-up to #20 (`docs/planning/call-detection.draft.md`); Teams was left out on purpose.

**Fix.** Same rule as the others: Teams desktop (meeting window via the `speaker-watch` probe) and `teams.microsoft.com` tabs (page snapshot) count only when live. Until then Teams is the one exception to the **Call** definition in `GLOSSARY.md`.

## Arc is not enumerated by the meeting detector (2026-11-11)

**Observed.** The detector's AppleScript lists tabs for Chrome, Edge, Brave and Safari only. A Meet, Slack huddle or Zoom web call in Arc is never detected, although `SpeakerWatcher.swift` already knows Arc for participant capture.

**Fix.** Add an Arc tab-listing handler (literal `tell application "Arc"`, guarded by the running-process check) and include Arc in the page-snapshot path. Out of 0.4.2.

## Earlier todos

- ASR validator: a consistency rule (accept when two attempts agree) and a strict-speech >= 30 % gate for sparse-speech Windows; the coverage rule alone rejected correct Gemini output on a 38-second recording (2026-11-10).
- Notification title for a Window fallback uses the folder id instead of the meeting name.
- Log a line when a Window cannot be split further.
- Microphone hardware checks from `docs/operations/release-smoke-checklist.md` (fifine, Brio, AirPods, mid-call unplug).
- Call detection: Arc and other Chromium browsers are not scripted for detection (only Chrome, Brave, Edge and Safari); a Meet or huddle in Arc never prompts (2026-11-11).
