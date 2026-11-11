# Cora beta: what is shared

Last updated: 2026-11-11. This policy applies to the **internal beta only** (team builds of Cora
0.4.0 and later). It will be rewritten before anyone outside the team gets a build.

During the beta Cora sends usage data and some full recordings to the Cora team to check accuracy.
This page says exactly what, where it goes, who sees it, and how to stop it.

## What is sent

**Usage events.** Small, fixed-shape facts about how Cora is used: a Recording started or
stopped, processing finished, notes viewed or edited, a setting changed, an update installed.
They carry counts, durations, versions, model names, error codes and on/off values. They never
carry meeting titles, people's names, transcripts or note text. A changed setting that looks
like a key, token or password is not reported at all; any other free-text setting is reported
only as "set" or "cleared". The full list of events and fields is in `docs/TRACING.md`
("Usage events (beta)"); Cora refuses to store an event or field that is not on that list.

Each batch is labelled with this Install's random id (made once on this Mac, never your email or
machine name), the app version and commit, the build variant, and the optional name you type in
**Settings > Beta > Your name for the Cora team**.

**Feedback.** When you rate a Recording (thumbs up or down, on the Recording, its Notes or
Overall) or send a message from **Settings > Beta > Send feedback**, the rating, the reasons you
ticked and your comment are sent. The comment (up to 500 characters) is the one free-text field
that is sent. Please don't put customer names in it.

**Recordings in full ("Captured Recordings").** Two kinds of Recording are copied to the Cora
team:

- every Recording you rate, thumbs up or down, whatever its length;
- one in four Recordings under an hour, picked at random when processing finishes (the same
  Recording always gets the same draw, so reprocessing it does not pick it again).

A Captured Recording is the whole meeting. It contains these files from the Recording's folder
and nothing else:

| File | What it is |
|---|---|
| `audio.<ext>` | the original recording: your microphone and the other side's audio |
| `transcript_diarized.md`, `diarization.json`, `gemini_diarization.json` | the transcript, with who said what |
| `speakers_timeline.json` | the speaker timeline |
| `participants.json` | the Participants: names of the people in the meeting |
| `enhanced_notes.md`, `call_summary.json` | the generated notes, summary and action items |
| `metadata.json` | the Recording's details, such as its title, when it was recorded and the meeting app |
| `run_metadata.json` | how it was processed: versions, models, timings, token counts (no prompts and no model output) |

Not included: the playback copy of the audio, screenshots and their text, notes you typed
yourself, and earlier versions of the transcript or notes.

A Recording made while sharing is off, or under enterprise lockdown, is never queued. A queued
Recording that has not been sent within 7 days is dropped, and only that fact is reported.

## Where it goes and who sees it

Everything goes to one machine run by the Cora team (a Mac Studio), reachable from the internet
only over HTTPS through Tailscale Funnel and only with the team build's access token. It is
stored there in a folder only the Cora team can open. No analytics service or other third party
receives it. Only the Cora team sees it.

The Cora team deletes each Captured Recording once it has been reviewed. Usage events and
Feedback stay on that machine for the beta.

## Audio on your Mac

Cora removes a Recording's audio from your Mac once it is older than 30 days, or, oldest first,
when all audio together is over 500 MB. The transcript, notes, speaker timeline, Participants and
screenshots stay. The meeting then says "Audio removed after 30 days" (or "to stay under the
500 MB cap") where the player was, and Retranscribe is no longer offered. Audio is never removed
from a Recording that is being recorded, processed, has failed processing, or is waiting to be
sent as a Captured Recording. Both limits can be changed in **Settings > Beta > Audio on this
Mac**. This applies whether or not sharing is on.

## Turning sharing off

**Settings > Beta**, switch off **Share usage and sample recordings with the Cora team**. From
then on nothing is sent: no usage events, no Feedback, no Recordings, and no new Recording is
queued. Cora keeps recording usage events on your Mac while sharing is off, so if you turn sharing
back on, the events from the time it was off are sent too, along with any Recording queued before
you turned it off and less than 7 days old.

Sharing is on by default in team builds and off in every other build. **Enterprise lockdown**
turns all of it off whatever the toggle says, and also stops Cora checking for updates.

## Seeing what was sent

**Settings > Beta > Show what Cora shares** writes every usage event stored on this Mac, sent or
not, to `usage-events-export.jsonl` in Cora's data folder and shows it in Finder. Each line is one
event; `sent_at` says when it was sent (empty if it has not been).

Questions or a request to delete what was sent from your Mac: ask Mayank.
