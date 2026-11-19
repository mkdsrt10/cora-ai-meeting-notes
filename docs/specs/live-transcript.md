---
title: Live transcript during calls (on this Mac, or Google Chirp on Vertex)
status: ready-for-agent
created: 2026-11-20
glossary: Live transcript, Recording, Recording session, Chunk, Capture helper, Transcriber, Processing profile, Speaker timeline, Notes, Call prompt, Usage event, Captured Recording, Export, Team build
design: docs/planning/plugins-connectors-and-context.md §13.8 (decisions Q42–Q52)
related: docs/specs/plugin-harness-local-proof.md (independent track) · Pace repo (cora-mac-jarvis) streaming ASR research · cora-launch/competitor-architecture.md (Minutes live JSONL)
---

# Live transcript during calls

## Problem Statement

Cora only gives me words after I stop recording and processing finishes. During the call I see a
"Transcribing…" feed that is really just who is speaking, which is misleading. Other tools show
text as people talk, and I'd like to glance at what was just said, let my own AI agent read the
call while it is happening, and have draft notes the moment I stop instead of minutes later. I
want this on my Mac by default, with a cloud option when I choose it, and without risking the
recording or the transcript I already rely on.

## Solution

While a Recording session runs, Cora writes a **Live transcript** beside the recording: text from
each track (me on the mic, them on system audio) a second or two behind speech. It is shown as
captions in the floater and in the meeting's Transcript tab. My agent can read it over MCP, only
the lines since its last read. When I stop, draft notes appear within seconds, marked "Draft",
and are replaced by the full notes when processing finishes.

The engine is my choice in the Processing profile: Off, On this Mac (on-device, Neural Engine),
or Cloud (Google Chirp streaming on my Vertex project). The recording and the full transcript are
untouched: the Live transcript runs on its own path, and if it fails only the captions stop.

Both transcripts are kept on disk. The UI always shows the better one: live while recording, the
full transcript once ready, and the Live transcript as "Draft transcript" with Retry if
processing failed.

## User Stories

1. As a person in a call, I want to see what was just said as captions, so that I can catch something I missed without asking.
2. As a person in a call, I want captions labelled "You" and "Them" by track, so that I know whose words they are.
3. As a person in a call, I want a remote speaker's name on captions when Cora knows who is talking, so that I can follow a multi-person call.
4. As a person, I want captions in the floater and in the meeting's Transcript tab while recording, so that I can use whichever is open.
5. As a person, I want captions nowhere else (not on Home, notifications or the menu bar), so that live text doesn't spill into places others can see.
6. As a person, I want the misleading "Transcribing…" feed replaced, so that what is labelled a transcript is one.
7. As a person, I want live transcription off by default for now, so that nothing changes until I turn it on.
8. As a person, I want to pick Off, On this Mac, or Cloud (Vertex) as my live engine, so that I control where my audio goes.
9. As a person, I want to keep a cloud engine for the full transcript while using on-device live captions, so that live text never needs to leave my Mac.
10. As a person on the AI Studio key path, I want the Cloud live option hidden, so that I'm not offered something my setup can't do.
11. As a person, I want captions on my Mac to lag no more than about 2 seconds, so that they are useful in conversation.
12. As a person using Cloud live, I want captions within about 1 second, so that the cloud option is worth choosing.
13. As a person whose meetings mix Hindi and English, I want the engine choice to make clear how well it handles that, so that I pick the right one.
14. As a person, I want the recording and full transcript never affected by a live failure, so that live captions are a bonus, not a risk.
15. As a person, I want to see "Live captions paused" if the live engine fails or falls behind, so that I know the captions stopped.
16. As a person, I want Cora never to switch between on-device and cloud live by itself, so that my audio never goes somewhere I didn't choose.
17. As a person using Cloud live, I want a "Live: Cloud" badge on the floater and the Call prompt while audio streams, so that I always know it is happening.
18. As a person under enterprise lockdown, I want Cloud live blocked, so that policy holds; on-device live should still work.
19. As a Team build user, I want Cloud live not offered by default, so that the team's default stays local for live.
20. As a person who pauses and resumes, I want the Live transcript to continue across Chunks, so that one call has one live record.
21. As a person, I want draft notes within seconds of stopping, marked "Draft", so that I can start acting right away.
22. As a person, I want the full notes to replace the draft automatically, so that I don't manage two versions.
23. As a person whose processing failed, I want to read the Live transcript as "Draft transcript" with Retry, so that a failed run doesn't leave me with nothing.
24. As a person, I want the UI to show the better transcript without a toggle, so that I never choose between versions.
25. As a person, I want the Live transcript kept on disk beside the full transcript, so that it can be compared and analysed later.
26. As a person, I want the Live transcript deleted when I delete the Recording and covered by the Recording's retention, so that no copy outlives the meeting.
27. As a person, I want Exports never to include the Live transcript, so that what I share is the final version.
28. As the Cora team, I want the Live transcript included in a Captured Recording, so that we can review live-versus-full accuracy.
29. As a person using Claude or another MCP client, I want to read the Live transcript during the call, only lines since my last read, so that my agent can help mid-meeting.
30. As a person, I want Usage events about live transcription to carry counts only (delay buckets, engine, dropped seconds), so that no live text or names leave my Mac through telemetry.
31. As a person on a 16 GB Mac, I want live captions not to cause memory swap while my call app runs, so that the call stays smooth.
32. As a person, I want on-device live transcription to leave the GPU free for the notes model, so that live captions and notes don't fight.
33. As a developer, I want to run the capture helper's live engine on a WAV file, so that it can be tested without a real call.
34. As a developer, I want live text stabilised so captions don't flicker or retract stable words, so that captions are readable.
35. As the owner, I want measured caption delay, live-versus-full word overlap, CPU/RAM and egress on the same meetings, so that I can decide whether on-device live becomes the default on 16 GB+ Macs.

## Implementation Decisions

**Shape.** The live path runs beside capture; the recording file and the batch Transcriber are unchanged.

```
Capture helper ──► recording file (unchanged, canonical)
     └─ per-track PCM tap (16 kHz mono) ──► live engine ──► LIVE_PARTIAL / LIVE_FINAL lines
                                                               │
                                       Electron main: Live transcript writer (JSONL per Recording)
                                               ├─► captions (floater, Transcript tab)
                                               ├─► MCP cora_get_live_transcript (delta cursor)
                                               └─► draft notes at stop → replaced by full notes
```

**Capture helper (Swift).**
- Adds a per-track PCM tap and an on-device live engine, ported from the Pace prototype (`cora-mac-jarvis`), which already proved these pieces:
  - Silero CoreML voice-activity detection cuts speech chunks;
  - WhisperKit transcribes them on the Neural Engine;
  - a LocalAgreement-style stabilizer emits only word prefixes that agree across hypotheses and never retracts stable text;
  - Apple Speech is the fallback (restarted every ~1 minute, its per-request cap); Apple's newer on-device transcriber is tried on macOS 26+ behind an availability check.
- Model: measure English-only base vs a multilingual CoreML model (small or large-v3-turbo) for Hinglish; pick by the L4 eval.
- New stdout lines in the existing helper grammar: `LIVE_PARTIAL` and `LIVE_FINAL` carrying track, start, end, text. `SPEAKER_ACTIVE` stays as is and supplies the remote speaker hint.
- A file-input mode runs the live engine on a WAV fixture and emits the same lines (the test seam).

**Cloud live (Google Cloud Speech-to-Text v2, Chirp streaming).**
- Offered only when the Processing profile uses the Vertex backend; reuses its credentials.
- Goes through the outbound policy check; refused under lockdown; not offered by default in the Team build.
- Reconnects with overlap if the API limits stream length. Data logging off. To verify while building: regional availability, stream limits, code-switching support, whether the user's Google Cloud agreement covers Speech-to-Text.
- Never falls back to on-device automatically, and on-device never upgrades to cloud.

**Processing profile.** Gains a `live` field (`off` | `on_device` | `cloud_vertex`), independent of `transcription`. Default `off` for this spec.

**Live transcript record.** One JSONL file per Recording session in the Recording folder. Each line: track, speaker hint, start, end, text, final flag, Chunk recording id, engine. Lines continue across Chunks. Kept after processing; follows the Recording's retention; deleted with the Recording; never in Export; included in Captured Recordings.

**Which transcript is shown (one rule, server side).** The recording API reports which transcript to show and its label:
- recording in progress → Live transcript (captions);
- full transcript ready → full transcript;
- processing failed → Live transcript as "Draft transcript", with Retry.
No user toggle.

**Draft notes.** At stop, if a Live transcript exists, Cora generates draft notes from it with the configured Text model and a small budget, marked "Draft"; the full notes replace them when processing finishes.

**UI.**
- Floater: captions with You/Them (and speaker name when known); "Live captions paused" notice; "Live: Cloud" badge while streaming. The fake "Transcribing…" feed is removed; the Speaker timeline keeps its own place.
- Recording page: the Transcript tab shows captions while recording.
- Call prompt: "Live: Cloud" badge when cloud live will run.
- Settings: live engine choice in the Processing profile.

**MCP.** New read-only tool `cora_get_live_transcript(recording_id?, since_cursor?)` returning lines and a new cursor; defaults to the active Recording. Respects the same gates as other MCP reads.

**Usage events.** Counts only: engine, caption delay buckets (p50/p95), dropped seconds, failures by code. No text, no names.

**Gates.**

| Gate | Target |
|---|---|
| Caption delay | p50 ≤ 2 s on this Mac; ≤ 1 s cloud |
| Resources | no swap on 16 GB with a call app running; on-device live uses the Neural Engine, not the GPU |
| Isolation | recording and batch pipeline unchanged; a live failure never affects the recording file |
| Egress | no outbound traffic in on-device live mode; cloud live blocked under lockdown |
| Accuracy (reported) | live vs full word overlap per track, Hinglish separately |

## Testing Decisions

- Good tests check behaviour a user or caller observes (lines written, captions shown, the transcript the API says to show, what MCP returns), not engine internals.
- **Seam 1: capture helper stdout lines (existing).** Feed scripted `LIVE_PARTIAL` / `LIVE_FINAL` / `SPEAKER_ACTIVE` lines into the helper parser and Recording session. Assert: the JSONL is written in order with Chunk ids; captions update; "Live captions paused" appears on engine failure or lag; the recording path is unaffected when live lines stop or are malformed. Prior art: `test/js/capture-helper.test.js`, `test/js/recording-session.test.js`.
- **Seam 2: helper file-input mode (new, the only new seam).** Run the helper's live engine on short fixture WAVs (one per track, fictional speech). Assert: well-formed lines per track, monotonic times, stable text never retracted, a fallback engine used when the primary model is missing.
- **Seam 3: recording API + MCP (existing).** Assert the transcript-to-show rule for recording / ready / failed; `cora_get_live_transcript` returns only lines after the cursor; cloud live is refused under lockdown and on the AI Studio backend, using a fake stream. Prior art: HTTP tests in `tests/test_plugin_host.py`, existing MCP tool tests.
- The L4 eval (delay, overlap, CPU/RAM, egress capture) is a measured run on the team's own meetings, not a unit test; it prints counts only.

## Out of Scope

- Live plugin hints or any live write to Notion or Slack (ADR 0002 holds; later, read-only).
- Live diarization beyond track (You/Them) plus Accessibility speaker hints.
- Making on-device live the default on 16 GB+ Macs (decided after the gates).
- Cloud live vendors other than Google Chirp; cloud live on the AI Studio path.
- Live captions on Home, notifications, the menu bar, or a separate captions window.
- The plugin harness, Notion and Slack (separate spec: `docs/specs/plugin-harness-local-proof.md`).
- UI shell v2.

## Further Notes

- Compliance flag: cloud live streams everyone's voices to Google for the whole call. It is opt-in, badged, blocked under lockdown and off in the Team build by default. For regulated data, use it only where the user's Google Cloud agreement covers Speech-to-Text. Keeping both transcripts means two copies at rest, tied to one Recording and deleted together.
- The Pace repo's WhisperKit streaming re-transcribed the whole buffer every ~1.2 s and was built for push-to-talk under 60 s; meetings need the VAD-chunked pattern instead.
- Independent of the plugin harness track; can be built in its own worktree now.
