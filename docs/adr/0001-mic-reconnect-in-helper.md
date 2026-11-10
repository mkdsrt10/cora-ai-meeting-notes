---
status: accepted
date: 2026-11-10
spec: docs/specs/microphone-selector.md
---

# Mic reconnect inside the capture helper, with silence padding

## Context

A Recording's mic track comes from the capture helper (`capture/dual-capture`), which writes the
mic and system-audio tracks into one file per Chunk. Microphones disappear mid-call: a Bluetooth
headset's battery dies, a USB cable is pulled, a webcam is unplugged. Before this decision the
helper kept a dead `AVCaptureSession` input, so the mic track simply stopped while the system
track carried on. Transcription and speaker attribution rely on both tracks sharing one timeline,
so anything that drops or shortens the mic track shifts "who said what" for the rest of the
meeting.

## Decision

The helper handles the disconnect itself. On `AVCaptureDevice.wasDisconnectedNotification` for
the device in use, or `AVCaptureSession.runtimeErrorNotification`, it reopens the CoreAudio
default input (retrying every 0.5 s while CoreAudio moves its default; after about 3 s it accepts
any connected input) into the same `AVCaptureSession`, and keeps appending to the same mic
`AVAssetWriterInput` in the same file. The first mic buffer after the reconnect is preceded by
zero PCM covering the gap since the last mic buffer, so the mic track stays time-aligned with the
system track. The mic output is pinned to one PCM format (48 kHz, stereo, Float32 interleaved)
so any device, and the padding, feed the writer identically. The helper then prints
`STATUS: MIC_DEVICE <name>` again. It never exits, never ends the Chunk, and never emits a
mic-off style event that could auto-stop the Recording.

## Consequences

- One Chunk can contain audio from two microphones. Its mic track has a stretch of digital
  silence for the gap (typically under a second; longer if no input exists at all).
- Electron learns about the switch only from the repeated status line; it notifies the user but
  does not change recording state.
- A chosen device that comes back later is not reattached mid-Chunk; the next Recording (or
  pause/resume, or Continuation) resolves the Microphone setting again.
- Behaviour depends on hardware events and cannot be unit tested; it is covered by the
  Microphone section of `docs/operations/release-smoke-checklist.md`.

## Alternatives considered

- **End the Chunk and start a Continuation on disconnect.** Rejected: it turns a cable pull into
  a new Chunk boundary, loses audio during helper teardown and restart, and relies on the
  existing auto-stop paths behaving perfectly at the worst moment. Hard to undo once transcripts
  and meeting assembly assume a Chunk boundary means a user action.
- **Reconnect without padding.** Rejected: AVAssetWriter packs audio samples contiguously, so the
  gap would vanish from the mic track and every later mic word would be timestamped early
  relative to the system track.
- **Let the mic track go silent until the user notices.** Rejected: the user loses their own
  side of the meeting silently.
