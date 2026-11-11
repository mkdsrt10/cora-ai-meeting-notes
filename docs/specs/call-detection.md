# Call detection: Google Meet, Slack huddles in a browser, Zoom web

Status: ready-for-agent. Vocabulary: `GLOSSARY.md` (Call, Recording, Participant, Speaker timeline).

## Problem Statement

Cora is supposed to notice when I am in a Call and offer to record it. Since October it has not done so for anything I actually use: Google Meet in Brave never prompts, Slack huddles in a browser never prompt, and Zoom's web client never prompts. I start every Recording by hand from the tray or the floater, and when I forget, the meeting is lost. The last "call detected" notification on my Mac is from a Zoom desktop call on 29 October.

## Solution

When I join a Google Meet, a Slack huddle (in the Slack app or in a browser tab, expanded or collapsed to the mini-bar) or a Zoom web call, Cora notices within a few seconds of my microphone turning on and shows the usual "<App> call detected. Start recording?" notification with a Start Recording button. Nothing records until I click. For Meet, the prompt comes when I have actually joined, not while I am still in the green room. If my browser does not allow Cora to look at the page, Cora tells me once per start which setting to enable, and still prompts for Meet from the tab address alone.

## User Stories

1. As a Cora user on Google Meet in Chrome or Brave, I want the "call detected" prompt when I join a room at today's `meet.google.com/meet/xxx-xxxx-xxx` address, so that I do not have to remember to start recording.
2. As a Cora user, I want the Meet prompt only after I have clicked Join, so that a green room I am about to leave does not start a prompt.
3. As a Cora user, I want browsing to the Meet landing page, `/new` or `/landing` to never count as a Call, so that I am not prompted for nothing.
4. As a Cora user running Slack in a browser tab, I want a huddle I join to be detected, so that browser huddles get the same treatment as the desktop app.
5. As a Cora user, I want a huddle collapsed to Slack's bottom mini-bar to count as a live Call, so that the way I actually use huddles is covered.
6. As a Cora user, I want a Slack DM or channel tab with no huddle to never count as a Call, so that chatting does not prompt me.
7. As a Cora user on Zoom's web client (`zoom.us/wc/...`), I want to be prompted the way Zoom desktop users are, so that web Zoom is not a blind spot.
8. As a Cora user, I want the prompt to arrive within seconds of my microphone turning on, so that the Recording starts near the beginning of the Call.
9. As a Cora user whose mic watcher failed to start, I want the 20-second poll to find the same Calls, so that detection does not depend on one helper.
10. As a Cora user, I want nothing to record without my click, so that no customer call is captured unprompted.
11. As a Cora user who has not enabled "Allow JavaScript from Apple Events" in my browser, I want one notification per app start naming that setting, so that I know why browser huddles are not detected and why Meet prompts early.
12. As a Cora user without that setting, I still want Meet detected from the tab address alone, so that the old behaviour is a floor, not a regression.
13. As a Cora user, I want that hint shown once per app start and recorded under Settings > Notifications & logs like every other notification, so that it is not a nag and can be found later.
14. As a Cora user, I want a detected Call to end (and a running Recording to stop) when I leave the Call, by the same signals as today (mic released, tab or window gone), so that nothing changes in how Recordings end.
15. As a Cora user with several Meet or Slack tabs, I want the live one to win, so that an idle tab does not hide the Call I am in.
16. As a Cora user, I want the notification to name the app ("Google Meet", "Slack Huddle", "Zoom"), so that I can tell what Cora saw.
17. As a Cora user, I want the page check to touch only Meet and Slack tabs, so that my other tabs are never scripted.
18. As a Cora user, I want a failed page check (browser busy, script error, timeout) to count as "no answer" rather than "no Call", so that one hiccup does not drop a detection the URL already supports.
19. As a Cora user, I want each detection decision logged with what was seen (host, whether the page answered, the result), so that a missed Call can be diagnosed from the logs afterwards.
20. As a Cora developer, I want the detector testable without a browser, so that URL shapes and page answers are covered by unit tests that run in CI.
21. As a Cora developer, I want a Usage event when a Call is detected and which signal found it, so that the receiver shows whether detection works across the team.
22. As a Cora user on Safari, I want the same behaviour as Chrome once Safari's "Allow JavaScript from Apple Events" (Develop menu) is on, so that the hint applies to my browser too.

## Implementation Decisions

- **Terms.** The detector finds a Call (see glossary). A Call has a label (the app name shown in the notification), a source (`app`, `browser`) and, for browsers, the tab URL and whether the page confirmed it. "Meeting" is no longer used in new code or messages for the live thing.
- **URL rules become "candidate" rules.** A browser URL now yields a candidate, not a Call. Google Meet matches a room code `xxx-xxxx-xxx` after the host with any single path segment allowed before it (today's `/meet/`), still excluding the landing pages. Zoom matches `/j/` (join link) and `/wc/` (web client). Teams rules stay. Slack: any tab on `app.slack.com` or `*.slack.com` is a candidate.
- **Page snapshot decides for Meet and Slack.** For each candidate tab on `meet.google.com` or a Slack host, the detector asks the tab, through the browser's AppleScript "execute javascript", one question and receives `{live: true|false|null, label}`: Meet is live when a "Leave call" control is present; Slack is live when huddle tiles, a huddle dialog with a Leave huddle control, a Leave/End huddle control anywhere on the page, or the collapsed mini-bar title (`data-qa="huddle_details_title"`) is present. The selectors are the same ones the speaker watcher uses; they move to one shared place so the two stay identical. `null` means the page could not be asked (JavaScript from Apple Events off, timeout, script error).
- **Decision table.** Meet: live true → Call; live null → Call from the URL alone (the floor); live false → no Call. Slack: live true → Call "Slack Huddle"; null or false → no Call. Zoom and Teams web: URL alone, as today. Desktop apps and Slack desktop windows titled Huddle: unchanged. Among several candidates, a page-confirmed one wins over a URL-only one.
- **Both triggers use it.** The mic-on check and the 20-second poll call the same check; the snapshot is part of it, one AppleScript round per check (the tab enumeration script also runs the snapshot for the matching tabs, so there is no second process launch per tab).
- **Injectable runner.** The detector module exports a factory that takes the script runner (default: `osascript`) and returns `{ checkOnce, startWatcher }`; main.js keeps using the defaults. The pure decision (`parsed output → Call | null`) is also exported for tests.
- **Hint when the page cannot be asked.** When a Meet or Slack candidate returns `null` for the first time in an app run, main.js shows one notification: "Cora can't see inside <browser>. Turn on View > Developer > Allow JavaScript from Apple Events so huddles and Meet are detected." (Safari: Develop menu.) It is recorded in the notifications table like any other and not shown again until the next app start.
- **Logging.** Every check logs one line: candidates seen (host and whether the page answered), and the decision. Logs stay local, as all logs do.
- **Usage event.** `call_detected {app, signal: mic|poll, confirmed: true|false}` is added to the catalog and `docs/TRACING.md`; no URL, title or names.
- **No settings.** No auto-start, no toggle; the prompt is the behaviour.

## Testing Decisions

- A good test feeds the detector canned script output and asserts the Call (or none), the label and whether it was page-confirmed; it never inspects the AppleScript text or internal state.
- One seam: the injectable script runner. Tests build a fake runner that returns a fixed AppleScript result (process list, tab URLs, Slack window titles, and per-tab snapshot answers) and call `checkOnce`. Cases: Meet old and new URL shapes; Meet landing pages; Meet green room (live false) versus joined; Meet with no page answer (floor); Slack chat tab (false), expanded huddle, collapsed mini-bar, no page answer; Zoom `/j/` and `/wc/`; two tabs where the confirmed one wins; a runner error → null; the watcher firing detected then ended on transitions.
- The hint logic is tested through the same seam by asserting that one `null` candidate per run produces exactly one hint callback.
- Prior art: `test/js/capture-helper.test.js` (fake binaries through an injected spawn target) and `test/js/updater.test.js` (injected fetch and store).
- Manual check before release: a real Meet join in Brave and a real browser huddle (expanded and collapsed) on two Macs, recorded in the release smoke checklist.

## Out of Scope

- Starting a Recording without a click, or any auto-record setting.
- The collapsed-huddle roster nudge and re-snapshot on huddle change (separate todo).
- Browsers other than Chrome, Edge, Brave and Safari (Arc and others are a later ticket).
- Teams web beyond the existing URL rule.
- Enabling the browser setting on the user's behalf.

## Further Notes

- The failing Meet shape and the missing Slack-in-browser rule were diagnosed on 2026-11-11 (`docs/TODO.md`); those two entries close with this spec.
- Participant capture already depends on the same browser setting, so no new permission is asked of the user.
