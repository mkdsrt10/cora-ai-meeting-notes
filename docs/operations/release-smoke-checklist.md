# Release smoke checklist

Manual checks run on real hardware before a release. Each section names what it covers and the
build it needs (`make build-native` for the native helpers, `make dev` or an installed build for
the app).

## Microphone

Covers the Microphone selector (docs/specs/microphone-selector.md) and the in-helper reconnect
(docs/adr/0001-mic-reconnect-in-helper.md). Needs a Mac with at least the desk mic, a webcam mic
and AirPods (or any two removable inputs). Inspect recorded files with
`ffprobe -show_streams <file>.mov` (track 0 = mic, track 1 = system audio) and listen to the mic
track in an editor that shows both tracks.

Helper alone (`./capture/dual-capture`):

- [ ] `--list-devices` prints one JSON line, exits 0, lists every input with its macOS name, and
      exactly one entry has `"isDefault": true`, matching System Settings > Sound > Input.
- [ ] Change the macOS default input and rerun `--list-devices`: the `isDefault` flag moves.
- [ ] `./capture/dual-capture /tmp/t.mov` (no `--device`) prints `STATUS: MIC_DEVICE <name>` with
      the macOS default input's name, not the webcam's. Ctrl-C finalizes the file.
- [ ] `--device <uniqueID>` for each listed device: the status line names that device and the mic
      track carries audio from it (tap or speak into each).
- [ ] `--device bogus-id`: recording starts, stderr says the device is unavailable, the status
      line names the system default.
- [ ] Mid-recording, unplug the device in use (or let AirPods disconnect): the helper keeps
      running, prints `Microphone lost (...)`, a new `STATUS: MIC_DEVICE <default name>` and
      `Microphone gap padded with N.NNs of silence.`; it does not exit.
- [ ] In that file, both tracks have the same duration (within ~0.1 s), and a clap recorded after
      the switch lines up on the mic and system tracks.
- [ ] Unplug every input mid-recording: the helper keeps running and prints
      `Microphone: no input device available yet; still retrying.`; plugging one back in resumes
      the mic track with a status line.
- [ ] While a long gap is being padded (unplug every input for ~30 s, then plug one in), the
      system track has no dropouts: play continuous audio through the speakers throughout.
- [ ] A session runtime error with the device still connected (e.g. change its sample rate in
      Audio MIDI Setup mid-recording): the helper reattaches the same device (status line names
      it, no switch to the default).
- [ ] With the macOS default input unavailable to AVFoundation (if reproducible), the helper
      prints `CAPTURE_WARNING: Using <name> because the system default microphone could not be
      opened` alongside the status line.

App:

- [ ] Fresh install, onboarding permissions step: after granting mic access the picker shows,
      preselected to System default; finishing the step without touching it works.
- [ ] Settings > Recording lists System default first, the macOS default annotated, the chosen
      one checked; a newly plugged mic appears after Refresh or reopening the section.
- [ ] Choose a device, unplug it, reopen Settings > Recording: it shows as "<name> (not
      connected)", selected and greyed out, not as System default.
- [ ] Choose each device in turn and record ~20 s: the floater mic meter tooltip and the recording
      panel name that device; no notification.
- [ ] System default chosen: recording uses the macOS default input, no notification.
- [ ] Choose a device, quit, unplug it, relaunch and record: recording starts on the default and
      one notification names the device actually used.
- [ ] Mid-call disconnect: recording continues, one notification, floater toast, labels update,
      recording is not stopped or paused, transcript speaker turns stay aligned after the switch.
- [ ] Pause/resume and "Continue this meeting" record on the same chosen device.
- [ ] Move the chosen USB mic to a different port (unique ID changes): it is still selected by
      name.
- [ ] Meeting detection still fires when a call starts, whichever Microphone is chosen.

## Call detection

Covers Call detection (docs/specs/call-detection.md). Needs an installed build on two Macs, Brave
with Allow JavaScript from Apple Events on (View > Developer), a Slack workspace in a Brave tab and a
Zoom meeting link. Check each prompt is the usual "<App> call detected. Start recording?" with a
Start Recording button, and that nothing records until it is clicked. Each check logs one
`[call-detect]` line in the main log.

- [ ] Meet in Brave at a `meet.google.com/meet/xxx-xxxx-xxx` address: no prompt in the green room
      (mic preview on); "Google Meet call detected" within a few seconds of clicking Join.
- [ ] The Meet landing page, `/new` and `/landing` never prompt.
- [ ] Leaving the Meet ends the Call; with a Recording running, it stops.
- [ ] Slack huddle in a Brave tab, expanded: "Slack Huddle call detected".
- [ ] Same huddle collapsed to the bottom mini-bar (rejoin, or restart Cora mid-huddle): still
      detected. A Slack DM or channel tab with no huddle never prompts.
- [ ] Zoom web client (`zoom.us/wc/...`, "Join from your browser"): "Zoom call detected".
- [ ] Turn Allow JavaScript from Apple Events off in Brave and restart Cora, open a Meet: one
      "Cora can't see inside Brave" notification for the app run (not repeated on the next
      check), listed under Settings > Notifications & logs; Meet still prompts from the address
      alone; a browser huddle does not prompt. Turn the setting back on afterwards.
- [ ] The receiver (or "Show what Cora shares") has one `call_detected` event per prompt, with
      `signal` `mic` or `poll` and no URL or title.

## Call detection: desktop liveness and Zoom web

Covers the `speaker-watch --probe` one-shot and the Zoom web snapshot. Needs `make build-native`,
real Zoom and Slack, Accessibility granted to Cora (and to the terminal for `make dev`).

- [ ] `./capture/speaker-watch --probe` prints one JSON line and exits in well under 1.5 s.
- [ ] Zoom desktop open on the home window (no meeting): `"zoomMeeting":false`, and no Call prompt
      from the 20 s poll or a mic-on.
- [ ] Join a Zoom meeting: `"zoomMeeting":true`, Call prompt appears.
- [ ] Slack desktop idle: `"slackHuddle":false`. Start a huddle popped out, then docked to the main
      window: `"slackHuddle":true` both times.
- [ ] Zoom web (`/wc/`): pre-join screen is not a Call; after Join it is (Allow JavaScript from
      Apple Events on).
- [ ] Revoke Accessibility for Cora: probe prints `"ax":"untrusted"`, the log has
      `fallback=ax_untrusted`, a mic-on with Zoom or Slack open prompts, the 20 s poll never does.
