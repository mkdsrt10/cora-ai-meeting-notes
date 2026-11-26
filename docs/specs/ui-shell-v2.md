---
title: UI shell v2 and the Surface contract
status: ready-for-agent
created: 2026-11-22
glossary: Surface, Plugin, Proposal, Action item, Link, Account, Recording, Notes, Live transcript, Speaker timeline, Folder, Person, Connection
design: docs/planning/plugins-connectors-and-context.md §13.10 (Q32–Q41, Q63–Q66)
adr: docs/adr/0005-surface-contract-cora-draws-plugins-supply-data.md (and 0002, 0004)
reference: branch prototype/plugins-ux (fab55e9), src/ui/web/prototype-plugins-ux.html
---

# UI shell v2 and the Surface contract

## Problem Statement

Cora now has Notion and Slack plugins, live captions and Action items as records, but they sit on
the old screens: a blue-grey dashboard with a fixed nav, meeting pages laid out as panels, and
plugin bits squeezed under the notes. It doesn't feel like a modern notes app, and every new
plugin needs hand-built UI in a different place. I want the app to look and work like the
prototype: a calm document-style meeting page, a sidebar with my recent meetings, one place for
suggestions, ⌘K for everything, and plugins that show up only where they belong.

## Solution

A new shell, built beside the current one and switched on with Settings › "Try the new look". It
uses the prototype's look (neutral greys, one purple accent, dark mode that follows macOS) and
layout: a sidebar (search/⌘K, Home, Suggested, People, plugin pages, Recent meetings, Folders,
Settings) and meetings as document pages (breadcrumb, When/People rows, Notes / Transcript /
Notepad tabs plus plugin tabs, the Action-item checklist with chips inside the Notes, and the
confirm panel sliding in from the right).

Plugins fill **Surfaces** that Cora draws: a fixed catalog of places attached to Cora objects.
A plugin supplies data only; an empty Surface isn't shown. To-dos moves onto this contract. When
every current feature works in the new shell, it becomes the default; the old shell is deleted a
release later.

## User Stories

**Switching**
1. As a person, I want to turn on "Try the new look" in Settings, so that I can use the new shell without losing the old one.
2. As a person, I want to switch back at any time from Settings in the new shell, so that a missing feature never blocks me.
3. As a person, I want both shells to show the same data live, so that switching never loses an edit, done mark or suggestion.
4. As a person, I want the app to remember which shell I chose across restarts, so that I don't switch every launch.

**Look**
5. As a person, I want a calm neutral look with one accent colour, so that the content stands out, not the chrome.
6. As a person, I want dark mode to follow macOS, with a manual Light / Dark / System override, so that it fits how I work.
7. As a person, I want readable type sizes and spacing like a document editor, so that long notes are comfortable to read.
8. As a person using the keyboard, I want visible focus rings and every control reachable by Tab, so that I can work without a mouse.

**Sidebar and navigation**
9. As a person, I want a sidebar with Home, People, plugin pages and Settings, so that I always know where I am.
10. As a person, I want my recent meetings listed in the sidebar, so that I can jump between today's calls in one click.
11. As a person, I want my Folders in the sidebar, so that I can open a project's meetings directly.
12. As a person, I want a Suggested item with a count that appears only when something is pending, so that I see suggestions without an empty inbox nagging me.
13. As a person, I want plugin pages (To-dos, later Coaching) in the sidebar only while the plugin is on, so that turning a plugin off removes it everywhere.
14. As a person, I want a search box in the sidebar that searches meetings, so that I can find a call by what was said.
15. As a person, I want to collapse the sidebar, so that I can read a meeting full width.

**⌘K**
16. As a person, I want ⌘K to open a command menu, so that I can reach any meeting, page or action by typing.
17. As a person, I want ⌘K to list plugin actions (Send to Slack…, Suggest again) alongside Cora's own, so that I don't hunt for them.
18. As a person, I want ⌘K actions to apply to the meeting or selection I'm on, so that the command does what I expect.
19. As a person, I want Cora's shortcuts to stay the same whatever plugins are on, so that a plugin never steals a key.

**Home**
20. As a person, I want Home to list my meetings with date, duration, people and status, so that I can scan my week.
21. As a person, I want Home's filters (date, Folder, status, search) to keep working, so that I lose nothing from today.
22. As a person, I want the recording controls (start, stop, pause, the active call) on Home and in the sidebar while recording, so that I can control a call from anywhere.
23. As a person, I want processing progress and failures shown on the meeting row, so that I know what's ready.

**Meeting page**
24. As a person, I want a meeting to open as a document with a breadcrumb, a large title and When / People rows, so that it reads like a page, not a dashboard.
25. As a person, I want to rename a meeting by editing its title in place, so that naming is quick.
26. As a person, I want Notes, Transcript and Notepad tabs, so that the three views of a call are one click apart.
27. As a person, I want plugin tabs (Coaching later) only when that plugin has something for this meeting, so that empty tabs never show.
28. As a person, I want the Action items as a checklist inside the Notes, so that follow-ups live where I read the call.
29. As a person, I want to tick, edit, add and delete Action items in the checklist, so that I manage follow-ups in place.
30. As a person, I want each Action item to show at most one chip, with the rest behind "+N", so that rows stay readable.
31. As a person, I want a pending suggestion to be the chip I see first, then the Link, so that what needs me comes first.
32. As a person, I want to select several Action items and see a selection bar (Send to Slack, Mark done, Copy), so that bulk actions are one click.
33. As a person, I want a meeting-level suggestion row at the end of the Notes with "Review all", so that I can handle a whole call's suggestions at once.
34. As a person, I want the confirm panel to slide in from the right with what will be sent, so that I review before anything leaves my Mac.
35. As a person, I want Participants, the Speaker timeline, Processing history, Export, Reprocess and Feedback reachable from the meeting page (property rows, ⋯ menu, tabs), so that nothing I use today disappears.
36. As a person recording, I want live captions in the Transcript tab and draft notes marked "Draft", so that the live features work in the new shell.
37. As a person, I want a property row to show plugin facts like "Call Log ✓ Notion" only when a plugin has one, so that the header stays clean.

**Suggested**
38. As a person, I want a Suggested page listing pending suggestions across meetings, grouped by meeting, so that I can clear them in one place.
39. As a person, I want to confirm, edit or dismiss each suggestion from Suggested using the same confirm panel, so that it works the same everywhere.
40. As a person, I want the To-dos › Suggested tab gone once Suggested is in the sidebar, so that there is one place for it.

**People, Memory, Settings**
41. As a person, I want the People list and Person pages in the new look, with Accounts rows from plugins, so that people work as today.
42. As a person, I want Memory reachable in the new shell, so that I lose nothing.
43. As a person, I want every Settings panel available in the new shell (Processing profile with Live captions, Connections, plugin settings, Profile with "About my work", Microphone, updates, beta), so that I never need the old shell to change a setting.
44. As a person, I want plugin settings shown as Settings sections Cora draws, so that every plugin's settings look alike.

**To-dos on the contract**
45. As a person, I want To-dos to look and behave as before (lists, done, filters), so that moving it onto the contract changes nothing for me.
46. As a person who turns To-dos off, I want its page, nav item and actions gone, so that off means off.

**Other**
47. As a person, I want the onboarding tour to work in the new shell, so that a new install isn't left without guidance.
48. As a person, I want the floater, Call prompt and menu bar unchanged, so that recording works the same.
49. As a person with lockdown on, I want plugin contributions dropped everywhere in the new shell, so that policy holds.
50. As a plugin author, I want to declare which Surfaces my plugin fills with plain data, so that my plugin looks like Cora without writing UI.
51. As a plugin author, I want a new Proposal of an existing type to reuse Cora's panel, so that a Linear plugin needs no UI work.
52. As the owner, I want a written parity checklist that is all ticked before the new shell becomes the default, so that the switch is safe.

## Implementation Decisions

**Two shells, one server.** The new shell is a second page served by the same local server,
reading the same APIs. The Electron main process loads one page or the other from a stored
setting (`ui_shell: classic | v2`, default classic). Main-process, floater, Call prompt, menu bar
and recording session code are untouched. No server change is needed for the shell itself
beyond the Surface endpoint and the setting.

**Tech.** Plain JS and CSS, no build step, as today. The prototype's design tokens (light and dark
sets) become the CSS base for the new shell. Shared logic (API client, formatting, outbox,
live-transcript rendering) is reused, not copied, where it doesn't assume the old DOM. Shell
JS lives in its own folder so the old shell can be deleted cleanly later. The Notes editor stays
a separate spec; the Notes tab renders today's notes and leaves room for it.

**Surface contract (ADR 0005).** One read endpoint returns, for a given context (app, a
Recording, a Person, a Folder), the contributions every enabled plugin makes, already filtered for
lockdown, plugin-excluded Recordings and disabled plugins:

```
contribution = {
  plugin_id, surface,            // e.g. "action_item.chip", "recording.tab", "app.nav"
  kind: "annotation" | "action" | "panel",
  target?,                       // action_item id, recording id, person id …
  label, icon?, url?, badge?,    // annotation / nav
  action?: { id, applies_to: "recording" | "selection" | "action_item" },
  panel?: { title, blocks: [ { type: "text"|"list"|"kv"|"link", … } ] },
  proposal_key?                  // chip that opens a Proposal
}
```

Catalog v1: `app.nav`, `app.nav_badge`, `app.page`, `app.settings_section`, `app.command`,
`recording.property`, `recording.notes_block`, `recording.tab`, `recording.footer`,
`recording.menu`, `action_item.chip`, `action_item.hover`, `action_item.menu`,
`action_item.on_done`, `selection.action`, `person.accounts`, `folder.defaults`. Plugins
declare contributions in Python (on the Plugin, next to `proposer` and `context_sources`);
Cora's renderer draws each kind with its own components. Rules: one chip per Action item (pending
Proposal, then Link, then plugin order, rest behind "+N"); plugins never define keys; actions run
through one Cora endpoint that calls the plugin's handler; plugins never call each other.

**Proposals by type.** The confirm panel already renders by `kind`; it moves into the new shell
unchanged in behaviour and gains `task.comment` and `page.create` layouts (rendered, not yet used
by a plugin).

**Suggested.** A core page and nav item (with count) shown only when Proposals are pending,
grouped by meeting, using the same panel. The To-dos › Suggested tab is removed in the new shell.

**To-dos on the contract.** To-dos contributes `app.nav` + `app.page` (a Panel of lists Cora
draws) and `selection.action` (Mark done). Its old JS page stays for the classic shell only.
Coaching keeps its JS page in classic and is not shown in v2 until its own follow-up ticket moves
it (Notes block + tab).

**⌘K.** A command menu built by Cora from: navigation (pages, recent meetings, search), Cora
actions for the current context (record, reprocess, export, rename), and `app.command` /
`selection.action` / `recording.menu` contributions. Fixed Cora shortcuts; no plugin keys.

**Parity checklist.** A checklist file listing every classic-shell feature with where it lives
in v2 and its status. The default flips to v2 only when every row is done (Q40), by a separate
one-line change after the owner reviews it.

## Testing Decisions

- Good tests check what a person or plugin observes: which Surfaces appear for a given plugin
  state, what the renderer draws, what a click calls. Not CSS details.
- **Seam 1: the Surface endpoint (new, the one new seam).** Python HTTP tests: contributions per
  context; empty when the plugin is off, under lockdown and for excluded Recordings; chip order
  and the one-chip budget; To-dos contributions match its lists. Prior art: `tests/test_outbox.py`,
  `tests/test_plugin_host.py`.
- **Seam 2: renderer JS on a fake DOM (existing).** Load the shell's JS into Node `vm` with a
  fake document and canned API replies, as `tests/test_outbox_ui.py` does. Assert: sidebar items
  (Suggested only when count > 0; plugin nav only when enabled), meeting page tabs and property rows,
  checklist chips and "+N", selection bar actions, ⌘K results, confirm panel by kind, shell switch.
- **Boundary test (existing pattern).** Extend `test/js/core-plugin-boundary.test.js`: the v2
  shell never names a specific plugin (Notion, Slack, To-dos, Coaching) outside data it receives.
- **Visual check (manual, owner).** Open both shells in the app on real meetings, light and dark,
  and walk the parity checklist. Screenshots go in the PR, without meeting content.

## Out of Scope

- The Notes editor (ProseMirror/TipTap, in-place editing); separate spec.
- Moving Coaching onto the contract (next ticket after this spec).
- Making v2 the default and deleting the classic shell (after the parity review).
- Review mode, 5 s undo, Task comments, Call Log page, Recipe rung, gallery, MCP rung.
- Changes to the floater, Call prompt, menu bar or recording behaviour.
- Windows, mobile, a web build.

## Further Notes

- The prototype is the visual reference, not code to copy: it was throwaway and has no tests.
- Data handling is unchanged: the shell reads the same local APIs; no new network calls. Plugin
  contributions are filtered server-side, so lockdown holds in both shells.
- Keep screenshots and fixtures free of real meeting content (repo is public).
