# Known issues and todos

Diagnosed, not yet fixed. Each entry says what was observed, the cause found in the code or logs, and the fix we expect. Dated so the evidence can be re-checked.

## Meeting auto-detect never fires for Google Meet (2026-11-11)

**Observed.** Three calls on 2026-11-11 (two Slack huddles, one Meet, all in Brave) were started by hand. The notifications table has no "call detected" entry since 2026-10-29 (a Zoom desktop call). With a Meet live in Brave, `detectActiveMeeting()` returned null.

**Cause.** Meet now opens rooms at `meet.google.com/meet/xxx-xxxx-xxx?authuser=0`. `GOOGLE_MEET_ROOM` in `src/meeting-detector.js` requires the room code right after the host (`meet.google.com/xxx-xxxx-xxx`), so the `/meet/` segment defeats it. Tab enumeration itself is fine: the detector's AppleScript listed all 15 Brave tabs including the Meet one.

**Fix.** Allow an optional `/meet` (and any other single path segment) before the room code, keep the landing-page exclusion, add a unit test with the new URL shape. One line plus a test.

## Meeting auto-detect does not know Slack huddles in a browser (2026-11-11)

**Observed.** Huddles run in Brave (`app.slack.com`) never produce a "call detected" notification.

**Cause.** `BROWSER_URL_PATTERNS` covers Meet, Zoom web and Teams only; the Slack check looks at windows of the Slack desktop app titled "Huddle". A browser tab on `app.slack.com` is never considered, and its URL does not change when a huddle starts, so a URL test alone cannot tell a huddle from a chat.

**Fix.** For `app.slack.com` tabs, run a tiny page snapshot (the speaker watcher already has the selectors: `huddle_bottom_bar_content`, `huddle_window_content_container`, a Leave huddle button) through the same AppleScript `execute javascript` path, and report `Slack Huddle` when it is live. Needs "Allow JavaScript from Apple Events" in Brave, which the participant capture already requires.

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

## Earlier todos

- ASR validator: a consistency rule (accept when two attempts agree) and a strict-speech >= 30 % gate for sparse-speech Windows; the coverage rule alone rejected correct Gemini output on a 38-second recording (2026-11-10).
- Notification title for a Window fallback uses the folder id instead of the meeting name.
- Log a line when a Window cannot be split further.
- Microphone hardware checks from `docs/operations/release-smoke-checklist.md` (fifine, Brio, AirPods, mid-call unplug).
