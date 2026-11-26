---
title: Plugin harness proven on the local tier (Context sources, Proposals, Notion, Slack)
status: ready-for-agent
created: 2026-11-20
glossary: Work context, Plugin, Hook, Recording, Notes, Action item, To-do, Person, Participant, Account, Connection, Task, Proposal, Outbox, Link, Usage instructions, Processing profile, Text model, Provider
design: docs/planning/plugins-connectors-and-context.md (§13 is the scope; §3–§6 the design)
adrs: 0002 external writes are confirmed Proposals · 0003 Connections are personal · 0004 Action items are records
related: docs/RESEARCH.md "Local vs. Gemini on a week of real calls" (baseline and judge method)
---

# Plugin harness proven on the local tier

## Problem Statement

When Cora runs fully on my Mac, its notes are much weaker than with Gemini. On the meetings we
judged, only about a quarter of local Action items were real, none had an owner, and most
"decisions" were topics. The local model doesn't know who the people in the call are, what we
already agreed last week, or how my team works, so it guesses. And once the notes exist, I still
copy Action items into Notion and Slack by hand. We have designed a plugin harness that should fix
both (context for the notes, and confirmed write-back to my tools), but nothing yet shows that it
works, or that it works on the local tier rather than only with a cloud model.

## Solution

Cora gains a small, general plugin harness and a few common plugins built on it, all usable on the
local tier:

- **Context for notes.** Before writing each section of the Notes, Cora gathers short, tagged
  context from Context sources: the People in the call (role, organization), open Action items and
  recent decisions from earlier meetings with the same People or folder, and my own Work context /
  Usage instructions. It packs them within a budget sized for the local model, marks them as data
  rather than instructions, and records what it used.
- **Action items become core records** that keep their identity, owner and done mark across edits
  and reprocessing; To-dos is a View over them.
- **Proposals, confirmed by a click.** A Plugin can suggest an external write: link an Action item
  to a Notion Task, create a Task, or send selected Action items to Slack. Nothing leaves the Mac
  until I click Confirm on that Proposal. Matching and drafting run on my configured Text model,
  local included.
- **Connections are mine.** I paste my own Notion and Slack tokens; they live in the Keychain and
  every write acts as me.

Then we measure, on the same meetings as the earlier research: local without context, local with
the harness, and Gemini. The harness is proven if local-with-context closes a meaningful part of
the gap, on numbers set in advance.

## User Stories

1. As a person who runs Cora fully local, I want my notes to name the owner of each Action item, so that I know who committed to what.
2. As a person who runs Cora fully local, I want fewer false Action items and decisions, so that I can trust the list without re-reading the transcript.
3. As a person with recurring meetings, I want an Action item that continues one from last week to be recognized as a follow-up, so that my list doesn't fill with near-duplicates.
4. As a person whose meetings include colleagues already in People, I want their role and organization used when writing notes, so that owners resolve to the right Person.
5. As a person, I want to describe my work once ("About my work": role, team, projects, internal terms), so that every meeting's notes follow it.
6. As a person, I want context gathering never to delay or break my notes, so that a slow or failed source only means less context, not no notes.
7. As a person reviewing a notes run, I want a record of which context was used, from which source, and what was dropped, so that I can see why the notes came out as they did.
8. As a person with a 16 GB Mac, I want the extra context to fit the local model's budget, so that notes don't get slower or swap memory.
9. As a person who edits an Action item, I want my edit to survive reprocessing, so that Cora never overwrites my correction.
10. As a person who deletes an AI Action item, I want it to stay deleted after reprocessing, so that junk doesn't come back.
11. As a To-dos user, I want my done marks to survive reprocessing and the move to core records, so that nothing I ticked reappears as open.
12. As a Notion user, I want to connect my own Notion by pasting a token, so that Cora acts as me in my workspace.
13. As a Notion user, I want to choose my Tasks database and map its properties once, so that Proposals fill the right fields.
14. As a Notion user, I want Cora to suggest linking an Action item to an existing Task when they match, so that I don't create duplicates.
15. As a Notion user, I want a low-confidence match shown as "create" with the nearest Tasks offered as "link instead", so that I decide the uncertain cases.
16. As a Notion user, I want a suggested new Task to follow my Notion Usage instructions (for example "chunky tasks, fold sub-steps into a checklist"), so that Tasks match how I work.
17. As a Notion user, I want to edit a Proposal's title and fields before confirming, so that what gets written is what I meant.
18. As a Notion user, I want reprocessing a meeting never to propose a Task I already created or linked, so that I never get duplicates.
19. As a Slack user, I want to select several Action items and send them as one Slack message, so that I can share follow-ups after a call in seconds.
20. As a Slack user, I want to see and edit the message and its destination before it sends, so that I control exactly what my team reads.
21. As a Slack user, I want the message to post as me, not a bot, so that it reads like I wrote it.
22. As a Slack user, I want the destination to default to the last one I used for that folder, so that repeat sends are one click.
23. As a person, I want every external write to require my click, with no auto-apply of any kind, so that a transcript can never cause a write on its own.
24. As a person, I want to dismiss a Proposal and not see it again for that Recording, so that my review list stays clean.
25. As a person, I want pending Proposals to expire after 14 days without a decision, so that stale suggestions don't pile up.
26. As a person, I want to see exactly what will leave my Mac before I confirm, so that I can decide with full knowledge.
27. As a person under enterprise lockdown, I want Connections and confirms to be refused, so that policy holds even if a plugin is enabled.
28. As a person, I want a plugin that fails to never stop my notes or other plugins, so that one broken integration costs only itself.
29. As a person, I want turning a plugin off to remove its suggestions and context entirely, so that a disabled plugin has no effect.
30. As a person, I want Proposal and link state kept on my Mac and visible the same way whether processing ran in the app or in the background runner, so that nothing depends on which process did the work.
31. As a security reviewer, I want each confirmed write recorded in an audit row holding a hash of the payload and not its content, so that writes are attributable without storing meeting text twice.
32. As a security reviewer, I want tokens only in the Keychain and never in config, logs or audit, so that a leaked file never leaks a credential.
33. As a Cora developer, I want to add a Context source or a Proposal kind by declaring it on a Plugin, with no edits to core modules, so that new plugins are cheap.
34. As a Cora developer, I want to test a plugin against a fake Connection and a fake Text model, so that tests never touch the network or a real model.
35. As the owner, I want a repeatable eval comparing local without context, local with the harness, and Gemini on the same meetings, so that I can decide on evidence.
36. As the owner, I want the eval to print counts and judge labels only, never meeting text, so that its output is safe to share.
37. As the owner, I want a checkpoint after the context work, so that if local-with-context doesn't beat local we stop before building writes.
38. As the owner, I want the Notion matcher measured on a fixture of fictional Tasks, so that link precision is known before real use.
39. As a person, I want one list of pending suggestions across all my meetings, so that nothing expires unseen.
40. As a Notion user, I want a Task marked done in Notion to mark my To-do done, so that I tick things once.
41. As a Notion user, I want ticking a linked To-do done in Cora to suggest marking the Task done in Notion, so that both stay in step without a silent write.
42. As a person, I want to confirm once which Notion and Slack user a Person is, so that assignees and mentions are right from then on.
43. As a person, I want an unconfirmed owner left unassigned in Notion rather than assigned to me, so that I don't collect other people's Tasks.
44. As a person, I want Notion suggestions ready when I open a processed meeting, so that reviewing them is the only step.
45. As a person, I want Slack to list only my channels, myself, and people whose Account I confirmed, so that I can't send to the wrong place by accident.
46. As a person, I want context for notes off until the eval shows it helps, so that my notes never get worse from an experiment.

## Implementation Decisions

**Plugin seam (extends the shipped plugin host).** `Plugin` gains optional fields; existing plugins keep working unchanged:

```python
@dataclass(frozen=True)
class Plugin:
    ...                                    # existing fields unchanged
    connection: str | None = None          # "notion" | "slack"
    proposer: Proposer | None = None       # propose() / apply()
    context_sources: tuple[ContextSource, ...] = ()
```

A plugin never calls another plugin. Plugins meet only through core records (Action items, Links, Accounts).

**Context sources and the assembler (deep module).**

```python
@dataclass(frozen=True)
class ContextBlock:
    source: str               # "people", "prior_meetings", "work_context", "notion.tasks"
    text: str
    priority: float
    sections: frozenset[str]  # {"action_items", "decisions", "entities", "overview", "*"}
    kind: str = "reference"   # "instructions" | "reference" | "terms"
    egress: bool = False

class ContextSource(Protocol):
    id: str
    def gather(self, req: ContextRequest) -> list[ContextBlock]: ...

assemble(recording, section) -> AssembledContext   # .instructions, .reference, .manifest
```

- Per-section token budgets; the local Provider gets smaller budgets than cloud ones.
- Blocks pack by priority, dedupe, and truncate with a marker.
- Reference blocks are wrapped in `<context source="…">` tags with the standing line that tagged content is data, not instructions. Instructions (Work context, Usage instructions) go into the existing per-section template guidance.
- Each source has a hard deadline (default 3 s) and falls back to its own cache. Processing never waits on the network.
- A per-Recording `notes_context.json` manifest lists blocks used, source, token counts and drops.
- First sources: People (core), Prior meetings (core), Work context (core), Notion tasks (Notion plugin, titles only, capped, from a local cache).
- The ASR vocabulary context becomes one consumer through `kind="terms"` blocks.

**Core Action items (ADR 0004).** The Action item store moves out of the To-dos plugin into core and keeps existing ids and done marks. Records: text, owner (Participant/Person or unassigned), optional due, done, provenance (AI or user). User-added or edited records are never superseded by reprocessing; AI records the user deleted stay deleted. The Notes rich editor is not part of this spec; only the record model is.

**Outbox (deep module, ADR 0002).**
- A Proposal is a typed payload: `task.create`, `task.link`, `task.update`, `message.post`. Keyed for dedupe so reprocessing never duplicates a pending, confirmed or dismissed Proposal.
- States: pending → confirmed (applied) | dismissed | retired (invalid, or 14 days without a decision).
- Confirm requires an explicit user action through the API; no code path confirms without it. "Confirm all" is still one click.
- On confirm, the host calls the plugin's `apply` through its Connection, records a Link, and writes an audit row with a payload hash, plugin, kind, outcome and timestamp, never content.
- Lockdown refuses confirm. Outbox state is in the database so work done by the background runner shows in the app.

**Connection (ADR 0003).** Paste-token per user, stored in the Keychain. Owns base URL, version headers, retry and backoff, error mapping, the outbound policy check, and logging without payloads. Slack uses a user token and posts as the user; Notion uses the user's own integration. OAuth is out of scope.

**Notion plugin.**
- Settings: Tasks database, property mapping (title, status and its done value, assignee, due, Area, Meeting relation), Usage instructions with a starter template. Settings › Notion states that task titles go to the notes model when that model is a cloud one (Q28).
- A local task cache, refreshed by the `daily` Hook and on demand. Automatic network calls carry no meeting content.
- Proposals are made automatically after processing on the configured Text model (local included); "Suggest again" reruns them. Only when connected and enabled (Q56).
- Matcher: lexical shortlist plus one call to the Text model per Recording; low confidence becomes `task.create` with the 3 nearest Tasks as "link instead". A Task with the same title created in the last day is flagged (Q31).
- `task.link` adds a comment "From ‹meeting›, ‹date›: ‹action item›" and sets the Meeting relation if mapped. No Cora deep link. Never edits a Task's title or body (Q61).
- `task.create` follows the Usage instructions (granularity, folding sub-steps into a checklist).
- Done both ways (Q54): the `daily` status pull marks a Linked To-do done when its Task is done in Notion; ticking done in Cora raises a `task.update` "Mark done in Notion" Proposal.
- Assignee comes from the owner's confirmed Notion Account; with none, Assignee is left empty (Q55).

**Slack plugin.**
- Started by the user from selected Action items (Recording page or To-dos), never suggested automatically. One `message.post` Proposal holding all selected items. No routing rules, no DMs to each owner (Q58).
- "To": channels the user is a member of, a DM to themself, or a DM to a Person with a confirmed Slack Account; fetched when the composer opens, names only (Q57). Defaults to the last destination used for that folder.
- Message: fixed template by default (title, Action items with owners and due dates, a "View notes" line), no model. Owners are mentions only with a confirmed Slack Account, otherwise plain names. With Slack Usage instructions, the Text model drafts within them (Q30). Always previewed and editable.
- Posts as the user. No message updates after posting; the user can send again (Q59).

**UI (current app, minimal).**
- One Proposal chip under each Action item on the Recording page.
- One right-side confirm panel, reused for create, link, mark done and the Slack message, with editable fields and a 🔒 line stating exactly what will be sent. No modal (Q62).
- "Send to Slack" on selected Action items.
- To-dos › **Suggested** tab listing pending Proposals across meetings, with a nav count (Q53).
- **Accounts** on the Person page: a Notion row and a Slack row, suggested by name, Confirm / Not them (Q55).
- Settings › Profile "About my work" (Work context). Settings › Connections for tokens, Notion database/mapping and Usage instructions. Context for notes behind a setting, off by default (Q27).
- The prototype on branch `prototype/plugins-ux` is the visual reference, not the target.

**Eval tool.** Reruns the notes stage from saved transcripts (local and Gemini transcripts), arms A (local, no context), B (local + harness), C (Gemini, no context), optional D (Gemini + harness). Grades with the RESEARCH.md judge rubric plus owner attribution and follow-up-vs-new. Prints counts only; JSONL logs stay local. Separately, a Notion matcher eval on a fictional task fixture with hand-labelled links.

**Gates (from §13.5).**

| Gate | Target |
|---|---|
| Harness | a test plugin adds a Context source and a Proposal kind with no core edits; a failing plugin never breaks notes |
| Local quality (B vs A) | Action items precision ≥ 50% (from 23%), owners on ≥ 60% of items (from 0), decisions precision ≥ 60% (from 31%), recall not lower than A |
| Gap to cloud (B vs C) | reported in RESEARCH.md, whatever it is |
| Local cost | no swap on 16 GB in a 1 h meeting; notes stage latency ≤ +10% vs A |
| Notion matcher (local) | link precision ≥ 0.8 on the fixture; 0 duplicate Tasks after reprocess |
| Slack | selected items → one message, posted once, as the user; reprocess posts nothing |
| Egress | no outbound traffic during local processing; only on a confirm click |
| Safety | lockdown refuses confirm; audit rows hold hashes, not content |

**Order.** (1) core Action items + Plugin fields; (2) assembler + three core sources (Work context, People, Prior meetings) + eval arms; (3) checkpoint: if B doesn't beat A, stop and write up; (4) Outbox + Connection + minimal UI; (5) Notion + matcher eval; (6) Slack + To-dos on core records; (7) gates + RESEARCH.md section.

## Testing Decisions

- Good tests exercise external behaviour through the highest seam: what a user or caller observes (Proposals listed, confirm refused, notes prompt contents, manifest written), never a plugin's internals.
- **Seam 1: plugin host + HTTP API.** Register a test Plugin with a Context source and a Proposal kind; drive list / confirm / dismiss / reprocess over HTTP. Assert: no write without confirm, dedupe across reprocessing, 14-day retirement, lockdown refusal, audit row holds a hash not content, Links recorded, disabled plugin has no effect, a raising plugin doesn't stop others. Notion and Slack run against a `FakeConnection` that records requests and returns scripted errors. Also: request bodies of automatic calls (task cache refresh, status pull, Slack destination list) contain no recording text; the cross-meeting Suggested list returns pending Proposals and drops retired ones; done in Notion marks the Linked To-do done, done in Cora creates exactly one `task.update` Proposal; an unconfirmed Account leaves Assignee empty and renders a plain name in Slack. Core Action items: ids and done marks survive reprocessing and the migration from the To-dos store; user edits and deletions win. Prior art: `tests/test_plugin_host.py`, `tests/test_todo_plugin.py`.
- **Seam 2: notes generation.** Run notes generation with `FakeText` and fake sources. Assert: each section's prompt carries the tagged blocks within budget; local budgets are smaller; a slow source is skipped at its deadline; an erroring source is skipped; the manifest lists used and dropped blocks. Prior art: `tests/test_text_model.py`, `FakeText`.
- No test reaches the network or a real model. The eval tool is a measured run, not a unit test.

## Out of Scope

- UI shell v2, the Surface contract (Q32–Q41), Review mode, the Suggested inbox, the 5-second undo window.
- Task comments (Q15–Q18), the Call Log page, `task.update` from status pull beyond what Notion linking needs.
- The Notes rich editor (separate spec; only the Action item record model is here).
- OAuth for Notion and Slack.
- Recipe-file plugins, a plugin gallery, MCP as a Connection adapter, third-party plugins.
- Coaching migration onto the harness.
- The Live transcript (separate spec: `docs/specs/live-transcript.md`).
- Slack message updates after posting; Slack routing rules; DMs to each owner.
- Two Macs recording the same meeting sharing state (each Mac acts alone).

## Further Notes

- Data handling: the eval runs on the team's own recordings on the owner's Mac. The earlier judge was a cloud model; for anything resembling customer data, use a local judge or skip that meeting. The Notion fixture uses fictional Tasks. No meeting content in logs, audit rows or the repo.
- Notion's API records the integration as the author; "as me" means my workspace, me as Assignee and an optional "via Cora" footer. Verify against current API behaviour early.
- The legacy regex areas and skip-people lists in the old Notion sync script move into Notion Usage instructions or the property mapping. The script keeps writing Call Log pages until Call Log ships in Cora (Q60).
