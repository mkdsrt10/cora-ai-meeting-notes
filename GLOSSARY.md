# Glossary

Domain terms for Cora. Code, docs and reviews use these names. Architecture vocabulary (module, interface, seam, adapter, depth) is separate and not repeated here.

**Recording**: one captured meeting: a DB row plus a folder under `recordings/` holding audio tracks, transcript, notes and artifacts. Identified by its recording id.

**Recording session**: the live capture of a Recording, from start to stop. Owns the capture state (idle, recording, paused), the capture helper processes, mute, notes typed during the call and slide snaps. Lives in the Electron main process. Stopping returns it to idle at once, so a new Recording can start straight away.

**Finishing**: what happens to a Recording between stop and the Processing queue: its capture helpers exit (or are killed), it is marked processing, and it is handed to the queue, in the order Recordings were stopped. Runs in the background, per Recording; it never blocks the next start, and quitting waits for it.

**Continuation**: a Recording that extends an earlier one ("Continue meeting"). Its segments merge into the root Recording after processing.

**Chunk**: one uninterrupted stretch of capture inside a Recording session, with its own recording id. Pausing ends a chunk; resuming starts a new chunk that is a Continuation of the session's first chunk. _Avoid_: segment (that is a stretch of transcript).

**Capture helper**: a native Swift process (`dual-capture`, `speaker-watch`, `mic-watch`) driven over stdin/stdout. Its stdout lines are a small grammar parsed in one place.

**Processing queue**: runs post-stop work for each Recording by id, one job at a time: archive, transcribe, name speakers, write notes, run plugin hooks. Recording is never blocked by it.

**Processing profile**: the resolved choice of transcription engine, text provider, model and notes template for one processing run. Passed explicitly, never read from a hidden global.

**Text model**: the module every text-generation call goes through (notes, speaker naming, romanization, summaries, coaching, plugins). Picks the adapter from the Processing profile and owns lockdown, tracing, JSON repair, retries and model defaults.

**Transcriber**: the module every speech-to-text call goes through. Adapters: local MLX Whisper, Gemini audio, OpenAI-compatible `/audio/transcriptions`.

**Provider**: who serves a Text model or Transcriber call: `local_mlx`, `openai_compatible`, `anthropic`, `gemini`. Not to be confused with **Gemini backend** (`vertex` vs `ai_studio`), which is how Gemini credentials are reached.

**OpenAI-compatible preset**: a named `openai_compatible` endpoint a Processing profile can choose: `openai`, `openrouter`, `groq`, `ollama`, `lmstudio`, or `custom` (any base URL, e.g. a LiteLLM proxy). One preset serves both the profile's text and, when its transcription is `openai_compatible`, its audio. _Avoid_: custom LLM (that is only one preset).

**Plugin**: a bundled extension that declares, in one place, its View, its data for a Recording, its Stages and its Hooks. Each is enabled or disabled on its own; a disabled Plugin is absent everywhere (no page, no data, no Hooks). Bundled plugins at v1: Coaching (off by default), Todo/Planner (on by default).

**View**: a page in the Cora window, registered by id with a title, a subtitle and what to render when shown. Core pages and Plugin pages register the same way; a Plugin adds a View without editing core files.

**Hook**: a point where the host calls plugins: `after_meeting` (once per processed Recording, after its notes and Action items are saved and while its audio still exists, whichever engine processed it; a merged Continuation reports its root Recording), `daily`. One Plugin failing in a Hook never stops the others.

**Stage**: where a Recording stands: recording, processing, paused, needs diarization, needs speaker confirmation, ready. A Plugin may refine "ready" into its own Stages (Coaching: ready to coach, coached). _Avoid_: status (that is only the capture/processing part).

**Notes**: the document Cora writes for a Recording after processing (overview, Action items, decisions, open questions), which the user can then edit in place. Its Action items are records shown inside it, not text. Regenerating makes a new **Notes version**; a version the user edited is kept, never overwritten. _Avoid_: summary (that is one short variant of it), enhanced notes.

**Notepad**: what you type yourself for a Recording, during the call or after it. Never generated or overwritten by Cora. _Avoid_: my notes, manual notes.

**Export**: a file you save from one Recording, holding its Notes, its Notepad when it has text, and its transcript only when you ask for it. Under enterprise lockdown only the Notes and Notepad can be exported. _Avoid_: share (that sends to someone), download.

**Action item**: a follow-up written into a Recording's notes: what is to be done, its owner (a Participant or Person, or unassigned) and a due date when one was said. It keeps its identity when reprocessing brings it back reworded but close enough. One the user added or edited is theirs: reprocessing never supersedes it, and an AI one the user deleted stays deleted. Todo/Planner keeps each as a To-do.

**To-do**: an Action item as Todo/Planner tracks it: done or not. It keeps its identity (and done mark) when its Recording is reprocessed and the same Action item comes back; one that no longer appears is superseded, not listed. _Avoid_: task.

**Microphone**: the input device that feeds a Recording's mic track: "System default" (whatever macOS has as default input when recording starts) or one named device. The system-audio track is not a Microphone. _Avoid_: input device, audio source.

**Window**: one clip of a Recording's audio sent to a cloud Transcriber call and validated as a unit; a Window that the cloud engine keeps rejecting is transcribed locally instead. _Avoid_: chunk (that is capture), segment (that is transcript).

**Person**: someone Cora knows across Recordings: a People entry with a name, role, organization and optional voice reference, matched to speakers. _Avoid_: contact, user.

**Account**: who a Person is in one Connection (their Slack user, their Notion user). Suggested by name, confirmed once by the user, then reused. _Avoid_: identity, handle.

**Connection**: the user's own authorised link from their Install to one external workspace (their Slack, their Notion). It acts as the user and belongs to one person; it is never shared. _Avoid_: integration, connector.

**Task**: an item in an external tracker, such as a Notion task. A To-do may be Linked to a Task; many Action items may share one Task when the user's Usage instructions say so. _Avoid_: ticket, card.

**Proposal**: one external write a Plugin suggests for a Recording (create, link, update or comment on a Task; post or update a message), waiting for the user's click. Nothing reaches an external tool without that click. Shown in the app as "Suggested". _Avoid_: action, draft, suggestion.

**Surface**: a place in the app a Plugin can fill, attached to a Cora object (the app, a Recording, an Action item, a selection, a Person, a Folder). Cora draws it; the Plugin supplies only what goes in it. An empty Surface isn't shown. _Avoid_: slot, extension point, widget.

**Outbox**: every pending Proposal, across Recordings. A Proposal leaves it by being confirmed, dismissed, or retired (no longer valid, or 14 days without a decision).

**Task comment**: what one Recording concluded about one Task it discussed (decisions, progress, blockers, open questions), as one comment. Each point is backed by a transcript quote that stays on the Mac. _Avoid_: task update (that changes the Task's fields).

**Link**: the record that an Action item or Recording corresponds to an external Task or message, made when a Proposal is confirmed.

**Usage instructions**: what a user writes, per Plugin, about how they use that external tool (how big a Task is, what a message looks like). The Plugin's Proposals follow them.

**Work context**: what a user writes once about their work (role, team, projects, Areas, internal terms), in Settings › Profile as "About my work". Notes generation and every Plugin may read it. Not Usage instructions (those are per Plugin, about one tool). _Avoid_: Playbook.

**Call**: a live conversation in a meeting app or browser tab that Cora can notice, whether or not it is being recorded: Google Meet, Zoom, Microsoft Teams, a Slack huddle (expanded, collapsed to the mini-bar, or in the desktop app). "Call detected" is the moment Cora first notices one and offers to record; a Call exists only once you are in it (the page's own leave control or the app's meeting window is present), and ends when the app releases the microphone or its tab or window goes away. _Avoid_: meeting (that is the app, the Recording or the calendar event, depending on the sentence).

**Green room**: the pre-join screen of a meeting app (Meet's "Ready to join?"). The tab and often the microphone are already open, but it is not a Call.

**Call prompt**: what Cora shows when it detects a Call: an always-on-top panel offering Start recording and Dismiss, which stays until you act or the Call ends. Dismiss holds until that Call ends. The macOS banner is only the fallback when the panel cannot show. _Avoid_: notification (that is the banner).

**Manual start**: a Recording the user starts themselves (New note in the Cora window, or Start recording in the tray), rather than from a Call prompt. Captures the same Microphone and system audio as any other Recording, and works with no Call at all (an in-person conversation). Only one Recording session runs at a time. _Avoid_: blank note, quick note (that is the floater's note during a live Recording).

**Participant**: a name captured from the meeting app during one Recording (the roster). A Participant may be linked to a Person, renamed, hidden, or turned into a new Person from the Participants tab. _Avoid_: attendee (that is the calendar list).

**Speaker timeline**: who spoke when during a Recording, from the meeting app's accessibility tree and browser tabs. Not a transcript, live or otherwise.

**Live transcript**: the draft text Cora writes while a Recording session runs, from each track as it is captured, on this Mac or through a cloud engine the user chose. Once processing finishes, the Recording's transcript is the one shown; the Live transcript is kept beside it as data (for comparison and analysis) and deleted with the Recording. **Captions** are how it is shown, not a separate thing. _Avoid_: realtime transcript, streaming transcript.

**Menu bar**: where Cora lives when its window is not open: the menu bar icon, from which you start or stop a Recording, open Cora or quit it. Closing the window, ⌘Q and Dock > Quit leave Cora in the menu bar, still watching for Calls, with no Dock icon; only the icon's "Quit Cora" (or a macOS shutdown or logout) ends it. Cora opens at login straight into the menu bar unless you turn that off in Settings. _Avoid_: tray (that is the Electron API), background mode.

**Install**: one copy of Cora on one Mac, identified by a random id generated once. It may carry a display name for the Cora team: in the beta build it starts as the owner's own name, copied once, and the owner can change or clear it. The id never carries an email or machine name. _Avoid_: user, device.

**Usage event**: one metadata-only record of one thing that happened in an Install (a Recording stopped, processing finished, a setting changed, a rating given). Carries counts, durations, versions, models and error codes, never titles, names, transcripts or note text. Sent to the Cora team during the beta.

**Team build**: the build of Cora given to the Sutra team during the beta, published as a GitHub release and installed with the setup command or the in-app update. It carries the Beta receiver, so its Installs share by default. A copy built from source is not a Team build, whatever it says about itself. _Avoid_: beta build, internal build.

**Beta receiver**: the Cora team's server that Usage events, Feedback and Captured Recordings are sent to during the beta. A Team build carries its address and access token; without them an Install records Usage events but can never send them. _Avoid_: telemetry server, backend.

**Feedback**: an explicit rating a user gives one Recording, aimed at the Recording (capture and transcript), the Notes, or Overall: thumbs up or down, fixed reasons, and an optional comment. The comment is the only free text that leaves the Mac. A general message not tied to a Recording is also Feedback.

**Effort**: how much a person actually did in Cora on one day: the count of *doing* actions (starting, stopping or pausing a Recording, a Notepad save, a transcript correction, renaming a meeting or speaker, linking or adding a Person, a rating, an export or copy of the notes, ticking a To-do, filing into a folder, reprocess or retry, changing a setting). The action counts, not the input: a click, a shortcut and the tray count the same. Opening, switching, searching and filtering are *browsing*, counted apart and not Effort. _Avoid_: engagement, clicks.

**Active time**: the minutes of one day in which the Cora main window had focus and received input (key, pointer, wheel) in the previous 60 seconds. _Avoid_: session length, time in app.

**Captured Recording**: a Recording copied in full (audio tracks, transcript, speaker timeline, Participants, notes, run metadata) to the Cora team for accuracy review, either because it was rated or because it fell in the beta sample. Never a Recording made under enterprise lockdown.

