---
title: Cloud transcription Window resilience and failed-processing Stage
status: ready-for-agent
created: 2026-11-10
glossary: Window, Recording, Transcriber, Processing queue, Stage, Chunk
related: docs/specs/microphone-selector.md (a noisy mic is what exposed this)
---

# Cloud transcription Window resilience and failed-processing Stage

## Problem Statement

I recorded a two-minute test meeting and Cora never produced a transcript. The dashboard showed
the card as "Needs diarization", which told me nothing, and the only hint of what went wrong was
a hidden file in the recording folder. Underneath, cloud transcription had rejected one stretch of
the audio twenty-one times and then given up on the whole meeting. The stretch was mostly quiet
with a noisy mic: Cora's speech detector, tuned to fixed loudness thresholds, decided the whole
stretch was speech, and then faulted the cloud engine for not transcribing speech that was not
there. Last week a one-hour meeting died the same way when the cloud engine refused one stretch
on content grounds. Either way, one bad Window costs me the entire meeting, and the app shows it
as something it is not.

## Solution

Cora measures each recording's own noise floor and detects speech relative to it, so quiet
stretches on a noisy mic read as quiet. When the cloud engine still rejects a Window after
retries and splits, or refuses it, Cora transcribes that Window on the Mac and marks it, so the
meeting always completes with a full transcript. If no local model is installed, the Window is
kept as a marked gap and the meeting still completes. One notification tells me how many minutes
were affected and why, and the transcript shows which lines they are. When processing truly fails,
the card says "Processing failed", shows the reason, and offers Retry.

## User Stories

1. As a user with a noisy microphone, I want quiet stretches of my recording to be detected as quiet, so that transcription is judged against what was actually said.
2. As a user, I want speech detection to adapt to each recording's own noise floor, so that it works on my desk mic, my webcam mic and my AirPods without me tuning anything.
3. As an administrator, I want my existing silence-threshold override to keep working, so that a deployment I tuned by hand is not changed under me.
4. As a user, I want the same speech detection for local Whisper and for cloud Windows, so that switching engines does not change what counts as speech.
5. As a user, I want a cloud transcription Window that keeps failing validation to be transcribed on my Mac instead, so that one stretch never costs me the meeting.
6. As a user, I want a Window the cloud engine refuses on content grounds to be transcribed on my Mac instead, so that a refusal never costs me the meeting.
7. As a user on a team build without local models, I want a rejected Window kept as a marked gap, so that the rest of the meeting is still transcribed and summarised.
8. As a user, I want one notification saying how many minutes of a meeting were transcribed locally or left as a gap, and why, so that I know how much to trust that transcript.
9. As a user reading a transcript, I want locally transcribed stretches and gaps marked inline, so that I know which lines may read differently or be missing.
10. As a user on a meeting's detail page, I want one banner summarising the affected minutes, so that I see the caveat before I read the notes.
11. As a user, I want the notes and action items for a meeting with a fallback stretch to be generated as normal, so that a partial cloud problem does not block my notes.
12. As a user, I want Cora to stop treating "the detector saw no silence at all" as proof of continuous speech, so that a noisy stretch is not held against the transcript.
13. As a user, I want a cloud Window that spans a long silent gap to be split at that gap before it is sent, so that timestamps do not drift past the end of the clip.
14. As a user, I want a Recording whose processing failed to show "Processing failed" on the dashboard and detail page, so that I never confuse it with one that has not been processed yet.
15. As a user, I want the failure message to be the plain-language reason, so that I know whether to fix something or just retry.
16. As a user, I want a Retry action on a failed Recording, so that I can rerun processing myself after fixing the cause or changing engines.
17. As a user, I want Cora to stop automatically retrying a Window rejection, so that the same audio is not sent to the cloud again and again with the same result.
18. As a user, I want automatic retries to continue for genuinely transient errors such as network or provider outages, so that a blip still heals itself.
19. As a user, I want the silence-removed figure in the resource log to reflect real silence, so that the local tier's cost numbers are honest.
20. As a developer, I want the validator to be unit-testable with synthetic turns and speech lists, so that every rule can be exercised without audio or network.
21. As a developer, I want the windowed transcriber testable with an injected cloud call and an injected local transcriber, so that fallback offsets and marking are checked without Gemini.
22. As a developer, I want the speech detector tested on short synthetic audio, so that threshold behaviour is pinned at known noise floors.
23. As a developer, I want the windowed failure to be a typed processing error with its own code, so that the Processing queue and the UI can act on it without reading messages.
24. As a release owner, I want today's failed two-minute recording and last week's refused one-hour recording to process end to end with this change, so that the fix is verified on the cases that exposed it.

## Implementation Decisions

Vocabulary: a **Window** is one clip of a Recording's audio sent to a cloud Transcriber call and
validated as a unit. A Window the cloud engine keeps rejecting is transcribed locally instead.

**Speech detector (shared by local Whisper chunking and cloud Windows)**
- Thresholds become relative to each recording's measured noise floor: the floor is the quietest tenth of short frames of the mic-only audio the pipeline already produces. Main detector threshold is floor plus 10 dB; the strict detector used for coverage is floor plus 18 dB. Both are capped so they never exceed minus 20 dB. The existing configuration override, when set, replaces the computed threshold.
- Because Windows are cut from detected speech stretches, a long quiet gap inside what used to be one Window now splits it, which removes the timestamp drift seen when one clip spanned a 50 second gap. No separate drift handling is added.

**Window validation**
- When the strict detector finds no silence at all in a Window longer than 20 seconds, the detector is treated as saturated for that Window: the coverage check is skipped. An empty transcript for a saturated Window is still rejected ("no transcript for a saturated window"), so the retry ladder and the local fallback run. The remaining checks (timestamps inside the clip, monotonic, not collapsed, word-rate limits) still run.

**Windowed transcription fallback**
- The retry-then-split ladder is unchanged. When a Window is still rejected at the bottom of the ladder, or the provider refuses it (content block, empty candidates), the windowed transcriber hands that Window to the local Whisper adapter with the Window's offset so segments land at the right times, and marks each resulting segment with the engine that produced it. The run continues; the Recording completes.
- If no local Whisper model is available, the Window becomes a gap marker in the transcript with its time range and reason; the Recording still completes.
- This applies to every hosted Transcriber adapter that uses the windowed path (Gemini and OpenAI-compatible).
- Each segment carries its producing engine. The Recording records a per-engine summary (seconds transcribed locally, seconds left as gaps, reasons) for the UI and the notification.
- One notification per Recording, through the existing notify path and tied to the recording id, states the minutes transcribed on the Mac or left as gaps and the reason. None when every Window succeeded.

**Error classification**
- The windowed transcription failure becomes a typed processing error, not retryable, with its own code, with a user-facing message. It surfaces only when the fallback also fails (no local model and gap marking impossible, or the local adapter raising).
- Transient provider errors keep their retryable classification.

**Stage and UI**
- A new core Stage, "Processing failed", for a Recording whose last processing run ended in an error. It is distinct from "Needs diarization" and from the pending Stages. The dashboard card and the detail page show the Stage label and the user-facing message, with a Retry action that reruns processing with the current Processing profile. Retry is always offered to the user; automatic retries by the Processing queue remain limited to retryable errors.
- The failure message and code are stored on the Recording when a run fails, so the Stage survives a restart and is not read from a hidden progress file.
- Transcript view: segments produced by the local fallback, and gap markers, get a small inline note. Detail page: one banner summarising affected minutes, shown only when the per-engine summary says anything was affected.

**Resource log**
- Silence-removed seconds now reflect the relative detector, so the local-tier metrics in the research notes become meaningful.

## Testing Decisions

A good test drives a seam from outside and asserts only observable results: the segments and
their times, the error raised, the notification posted, the Stage shown. No test asserts on
thresholds as private constants or on internal call order.

Seams, all pre-existing, highest first:

1. **Validator** (prior art: the Gemini and cloud ASR tests that build turn lists by hand): synthetic turns and strict speech lists for every rule, including the saturated case where strict finds no silence in a long Window and coverage is skipped, and the non-saturated case where coverage still fails.
2. **Windowed transcriber** with an injected cloud call and an injected local transcriber (prior art: the transcriber tests that use the fake transcriber): a call that keeps rejecting one Window at every depth leads to local segments for exactly that Window at the correct absolute offsets, marked by engine; a provider refusal takes the same path; with no local model the Window becomes a gap marker; the per-engine summary counts seconds correctly; a run with no failures produces no summary and no notification.
3. **Speech detector** on synthetic audio generated with ffmpeg (prior art: the audio tests that already shell out to ffmpeg): a noise bed at minus 40 dB with tone bursts yields gaps at the bursts' edges; the same signal at minus 30 dB still yields them; the configuration override wins when set.
4. **Error classification and Stage** (prior art: the processing-errors tests and the stage/view tests): the windowed error classifies as non-retryable with its code; a Recording with a stored failure shows the "Processing failed" Stage with its message and is not shown as "Needs diarization"; Retry reruns processing.
5. **Verification on real recordings**: the 2026-11-10 15:50 recording and the 2026-11-05 one-hour recording process end to end; the first should need no fallback once the detector is relative, the second should complete with one locally transcribed Window.

## Out of Scope

- A neural voice activity detector or any new heavy dependency in the app.
- Changing Window length, worker count, retry counts or split depth.
- Fixing Gemini timestamp drift by post-processing; it is addressed only by better Window cuts.
- Changing how speaker diarization or the empty Accessibility speaker timeline work.
- The Microphone selector itself (separate spec, in progress).
- Any change to local Whisper's own chunk validation beyond the shared detector.

## Further Notes

- Evidence: on the exposing recording the quiet second half measured about minus 42 dB mean with peaks at minus 28 dB on the mic track and minus 91 dB on the system track; the fixed strict threshold of minus 35 dB therefore found no silence and demanded 60 percent coverage of 65 seconds that held about 30 seconds of speech. Across 84 recordings on the reporting Mac the main detector at minus 50 dB has never removed a second of silence.
- The gap-marker path matters for team builds, which default to Gemini and download no local model.
- Design agreed in a grill session on 2026-11-10; all fourteen decisions are reflected above.
