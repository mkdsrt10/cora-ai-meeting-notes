---
title: Microphone selector
status: ready-for-agent
created: 2026-11-10
plan_item: nov10-build item 11 (cora-launch)
glossary: Microphone, Recording session, Capture helper, Recording, Chunk, Continuation
---

# Microphone selector

## Problem Statement

I have two microphones on my Mac, a USB desk mic and the one built into my webcam. Cora records
whichever one it decides on, and today that is the webcam mic, which is noisy and not the one I
speak into. macOS already has the desk mic as its default input, and Cora ignores that. There is
no place in Cora to see which microphone a recording is using or to choose one, so my transcripts
pick up fan noise, the speech detector sees no silence, and cloud transcription of a two-minute
test recording failed outright because of it.

## Solution

Cora gets a Microphone choice. By default it records on the macOS default input, exactly as other
Mac apps do, which alone fixes the webcam problem on this Mac. A new "Recording" section in
Settings, and the permissions step of onboarding, let me pick one named microphone instead. The
floating bar and the recording panel tell me which microphone is actually in use. If my chosen
microphone is missing or disconnects, Cora records on the system default, keeps the recording
going, and tells me, rather than refusing to start or stopping mid-call.

## User Stories

1. As a user with more than one microphone, I want Cora to record on the macOS default input unless I say otherwise, so that the mic I already chose in macOS is the one Cora uses.
2. As a user, I want a Recording section in Settings with a Microphone picker, so that I can choose a specific mic without touching macOS settings.
3. As a new user, I want the same Microphone picker on the onboarding permissions step, so that I can set it at the moment I grant mic access.
4. As a new user, I want the onboarding picker preselected to System default and skippable, so that onboarding does not get longer for people with one mic.
5. As a user, I want the picker to list every input device with its macOS name, so that I recognise my devices.
6. As a user, I want the picker to mark which device is the current system default, so that I know what System default means right now.
7. As a user, I want the picker to show which device is currently chosen, so that I can confirm my setting at a glance.
8. As a user, I want the device list to refresh when I open the section and when I press a refresh control, so that a mic I just plugged in appears without restarting Cora.
9. As a user, I want my choice to survive restarts and updates, so that I set it once.
10. As a user, I want my choice to survive the mic moving to a different USB port, so that a port change does not silently send me back to the wrong mic.
11. As a user whose chosen mic is absent when a recording starts, I want Cora to record on the system default and start anyway, so that I never miss a meeting because a mic is unplugged.
12. As a user whose chosen mic was absent, I want a notification naming the microphone Cora actually used, so that I know why the audio sounds different.
13. As a user whose mic disconnects during a recording, I want the recording to continue on the system default, so that a dead battery or pulled cable does not end my meeting capture.
14. As a user whose mic disconnected mid-call, I want a notification about the switch, so that I can plug it back in or carry on knowingly.
15. As a user, I want a device change to never stop, pause or auto-stop a recording, so that recording is predictable.
16. As a user, I want the transcript timestamps to stay aligned with the system-audio track after a mid-call switch, so that who-said-what is not shifted for the rest of the meeting.
17. As a user, I want the floating bar to tell me which microphone is in use when I hover its mic level meter, so that I can check without opening the main window.
18. As a user, I want the floating bar's toast to announce a mid-call microphone switch, so that I notice it while in the call.
19. As a user, I want the recording panel in the main window to name the microphone in use next to its level meter, so that the level meter confirms my pick.
20. As a user, I want the system-audio track to be unaffected by the Microphone choice, so that remote participants are captured as before.
21. As a user, I want meeting detection to keep watching the macOS default input, so that Cora still notices calls starting whichever mic I record on.
22. As a user, I want a paused-and-resumed recording and a "Continue this meeting" Continuation to use the same Microphone choice, so that one meeting is not recorded on two mics.
23. As a user, I want my Microphone choice applied to recordings started from meeting detection prompts as well as manual starts, so that there is one behaviour.
24. As a user with a webcam, I want its microphone to appear in the list rather than be hidden, so that I can choose it deliberately if I ever want to.
25. As a user under enterprise lockdown, I want the Microphone choice to work the same, so that this local-only setting is never blocked.
26. As a developer, I want the capture helper to report which device it opened on its stdout, so that every surface shows the truth rather than the setting.
27. As a developer, I want device listing to come from the same native code that captures, so that device identities match what capture will open.
28. As a developer, I want the recording session's behaviour around devices covered by unit tests through the existing fake helper, so that fallback and notifications cannot regress silently.
29. As a release owner, I want a hardware checklist for microphones in the smoke checklist, so that the parts no unit test can reach are still checked before a release.

## Implementation Decisions

Vocabulary: **Microphone** is the input device that feeds a Recording's mic track, either System
default or one named device. The system-audio track is not a Microphone.

**Capture helper (native, dual-capture)**
- Gains a `--list-devices` mode that prints one JSON array of input devices, each with the macOS display name, the AVFoundation unique ID, and whether it is the current system default, then exits.
- Gains a `--device <uniqueID>` argument. With it, the helper opens that device. Without it, or when the device is absent or fails to open, it opens the system default input, resolved from CoreAudio's default-input property at start and mapped to the AVFoundation device by unique ID. It no longer relies on AVFoundation's own notion of a default audio device, which disagrees with the macOS default on the reporting Mac.
- On opening the mic, and on every later reopen, it prints one status line, `STATUS: MIC_DEVICE <name>`, naming the device actually opened. This line is the single source of truth for every surface.
- Handles disconnection of the device in use itself: it reopens the current system default into the same capture session and keeps writing the same mic track in the same file, inserting silence for the gap so the mic and system tracks stay time-aligned. It then prints the status line again. It never exits, never ends the Chunk, and never signals the kind of mic-off event that could auto-stop a recording. This decision is recorded as an ADR (see Further Notes).

**Electron main process**
- The Microphone setting is stored as a pair, unique ID and display name, with an absent value meaning System default. It is stored with the app's other settings, so it survives restarts and updates and lives on this Mac only.
- On start the session resolves the setting: match by unique ID, else by display name among the listed devices (covers unique IDs that change with the USB port), else System default. The resolved unique ID, if any, is passed to the helper at spawn. Pause/resume and Continuations reuse the same resolution for the session.
- The capture-helper line parser learns the new status line and emits a device event carrying the name. The Recording session exposes the current device name on its state and emits a device-changed event; it does not change recording state on it.
- One notification, through the existing notify path and tied to the recording id, is posted when the device opened differs from the chosen one at start, and on each mid-call switch. No notification when System default was chosen and used.
- One IPC lists audio devices by running the helper's list mode; Settings and onboarding both use it.
- The mic-watch helper used for meeting detection is unchanged and keeps watching the macOS default input.

**Python API**
- A route returns the device list produced by the helper, for the web UI. The Microphone setting is readable and writable through the existing settings routes.
- Lockdown policy does not gate any of this; it is local-only.

**UI**
- Settings gets a "Recording" section containing only the Microphone picker for now. First option "System default"; then every input device by macOS name, the current system default annotated as such, the chosen one checked. A refresh control re-lists devices; the list also re-lists each time the section is shown.
- The onboarding permissions step shows the same picker once mic permission is granted, preselected to System default; the step completes without interacting with it.
- The floating bar shows the device name as the tooltip of its mic level meter and in its existing toast when the device changes. No permanent label is added to the floater.
- The recording panel in the main window shows the device name as text beside its mic level meter.

**Documentation**
- Glossary entry for Microphone (already added). The release smoke checklist gains a microphone section. The Nov 10 build plan item 11 is marked against this spec.

## Testing Decisions

A good test here drives the system from outside a seam and asserts only what a user or a
neighbouring module can observe: what the helper is spawned with, which events and notifications
come out, what the API returns. No test asserts on internal state names or private functions.

Seams, highest first, all pre-existing:

1. **Recording session driven through the fake capture helper** (prior art: the recording-session tests and the capture-helper adapter tests). Cases: a chosen device appears in the spawn arguments; a status line naming the chosen device yields a state carrying that name and no notification; a status line naming a different device at start yields exactly one notification naming it; a second status line mid-recording yields a notification and leaves the recording state unchanged; a session with no choice spawns without a device argument; pause/resume and a Continuation reuse the resolved device; the stored choice matched by name when the unique ID is gone.
2. **Capture-helper line grammar** (prior art: the line-parser tests). The new status line parses to a device event with the name intact, including names with spaces and punctuation; unrelated lines remain ignored.
3. **API routes** (prior art: the providers-UI and BYOM settings tests, which drive routes with a fake helper runner). The device-list route returns the helper's JSON with the default marked and an empty list when the helper fails; the Microphone setting round-trips as ID plus name and clears to System default.
4. **Hardware checklist** (no automated seam; prior art: the release smoke checklist). On a Mac with the desk mic, the webcam and AirPods: each can be chosen and is the device on the recorded mic track; System default follows the macOS default; a mid-call disconnect continues the recording on the default with aligned tracks, a notification, and a new status line; a chosen device absent at start falls back with a notification.

## Out of Scope

- A live test meter in Settings. The existing level meters on the recording surfaces are the confirmation.
- Hot-plug listening in the UI; refresh is on show and on demand.
- Moving other capture settings, such as retain-audio, into the Recording section.
- Changing which device meeting detection watches.
- Any change to the system-audio track, speaker diarization, or the cloud transcription validator (the speech-detector threshold problem found alongside this bug is a separate spec).
- Per-meeting or per-app microphone choices.
- Input gain, noise suppression or echo cancellation.

## Further Notes

- Why the setting matters beyond preference: the webcam mic's noise floor on the reporting Mac sits above the thresholds of both speech detectors, which made a two-minute recording fail cloud transcription after 21 attempts. Picking the desk mic is expected to remove that trigger; fixing the detectors is tracked separately.
- ADR to write with the implementation: mic reconnect inside the capture helper with silence padding, rather than ending the Chunk and starting a Continuation on disconnect. It is hard to undo once transcripts rely on aligned tracks, a future reader will ask why a cable pull is not a new Chunk, and the alternative was real.
- Design agreed in a grill session on 2026-11-10; the eight first-round and nine second-round decisions are reflected above without exception.
