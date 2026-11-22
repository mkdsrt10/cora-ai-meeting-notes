---
title: UI shell v2 parity checklist
spec: docs/specs/ui-shell-v2.md
status: open (gaps listed below; the default stays classic)
updated: 2026-11-22
---

# UI shell v2 parity checklist

Every feature of the classic shell, where it lives in v2, and its status. The
default flips to v2 only when every row is ✅ (Q40), by a separate one-line
change after the owner walks this list in the built app, light and dark.

✅ works in v2 (tested) · ⚠️ works, with a difference noted · ❌ not in v2 yet (use the classic look)

Not touched by either shell, so unchanged: the floater, the Call prompt, the
menu bar, the Recording session, processing, MCP server.

## Window and navigation

| Classic feature | Where in v2 | Status |
|---|---|---|
| Sidebar: Home, People, Memory, Settings | Sidebar: Home, Suggested (only when pending), People, plugin pages, Recent, Folders, Settings; Memory via ⌘K and Settings › Data & privacy | ⚠️ Memory is not a sidebar item (spec Q66 layout) |
| New note button, ⌘N; "Go to live note" while recording | Sidebar "New note" / live card (Open, Pause/Resume, Stop); ⌘N; Home header | ✅ |
| Recording status banner with timer, Stop, Resume | Sidebar live card and Home header; meeting page live bar | ✅ |
| Folders: All notes, filter by folder, add, delete | Sidebar Folders (open, + add, × delete); Home folder filter | ✅ |
| Local usage stats (memory, last run, speed, tokens) | Settings › Data & privacy | ⚠️ moved out of the sidebar; "last run" not shown |
| Update banner (Update / Later) | Top of the content area, same js/update-banner.js | ✅ |
| Switch shells | Classic Settings › Preferences "Try the new look"; v2 Settings › Appearance "Back to the classic look"; remembered (ui_shell) | ✅ |
| Theme | Follows macOS; Settings › Appearance Light / Dark / System (ui_theme) | ✅ new |
| Keyboard: rows open with Enter/Space | All rows are buttons or role=button with Enter/Space; focus rings; ⌘K ⌘N ⌘\ ⌘, ; Escape closes the newest overlay | ✅ |
| Onboarding (first run) | v2 sends a new install to setup in the classic look | ⚠️ onboarding itself not moved |
| Tour (once, replay from Preferences) | Same js/tour.js in v2; Settings › Preferences "Take the tour" | ⚠️ slide images still show the classic look |
| Detection hint in Notifications & logs | — | ❌ minor |

## Home

| Classic feature | Where in v2 | Status |
|---|---|---|
| Meeting list: title, date, stage, duration | Rows: title, date + folder, people avatars, length, status | ✅ |
| Search (title, overview) | Search box (title, overview, people) and ⌘K "Search meetings for …" | ✅ |
| Filters: folder, stage, meeting type, person, date range | Same, on Home | ✅ |
| Pending rows poll; continuation "recording/processing more audio" | Store polls every 3 s while pending; note on the row | ✅ |
| Processing failed: reason + Retry | On the row and on the meeting page | ✅ |
| Processing progress | Progress bar on the row (new) and banner on the meeting | ✅ |

## Meeting page

| Classic feature | Where in v2 | Status |
|---|---|---|
| Breadcrumb, rename (✏️) | Breadcrumb (Home / Folder / title); title edited in place; ⋯ › Rename; ⌘K | ✅ |
| Copy recording ID | ⋯ › Copy meeting ID | ✅ |
| Export notes (.md), notes + transcript (.md) | ⋯ menu and ⌘K | ✅ |
| Folder select | Folder property row | ✅ |
| Open folder in Finder | ⋯ menu | ✅ |
| Retranscribe & re-summarize; Re-summarize with LLM (modal with processing controls) | ⋯ › Re-summarize… (side panel with the same js/processing.js controls, "Also retranscribe") | ✅ |
| Add to this meeting (continue) | ⋯ menu | ✅ |
| Earlier notes versions | Version property row; read-only view of that version's notes | ⚠️ notes only (classic also swaps the transcript) |
| Live: timer, Pause, Stop, Snap slide | Live bar on the meeting page | ✅ |
| Live: audio level meters, Microphone name | — | ❌ |
| Notices: which speaker is you, Accessibility, process in the cloud, audio removed | Above the notes, same buttons | ✅ |
| Engines banner (minutes transcribed locally / gaps) | Transcript shows local/gap turns (js/transcript.js) | ⚠️ no summary banner |
| Key phrases (add/remove) | Key phrases property row | ✅ |
| Find in transcript/notes (⌘F) | — | ❌ |
| Enhanced notes / Raw notes toggle | Notes tab / Notepad tab | ✅ |
| Draft notes (from live captions), labelled Draft | Notes tab, "Draft" | ✅ |
| Notepad, autosaved | Notepad tab | ✅ |
| Action items with one chip each, Links | Checklist inside the Notes: tick, edit, add, delete; one chip + "+N" (Surface contract) | ✅ |
| Select items → Send to Slack | Selection bar: Mark done, Copy (Cora) + plugin selection actions | ✅ |
| Suggest again | ⋯ menu / ⌘K (plugin recording.menu) | ✅ |
| Confirm panel (fields, 🔒 line, Confirm/Dismiss) | Right-side panel by kind, + task.comment, page.create; "Review all" walks a queue | ✅ |
| Participants tab: rename, link to Person, add to People, hide | Participants tab | ✅ |
| Meeting Timeline (speaker changes, slide snaps) | Timeline tab | ✅ |
| Clean transcript: copy, edit speakers and text | Transcript tab (same js/transcript.js) | ✅ |
| Live captions; Draft transcript (+ Retry when failed) | Transcript tab, label in the tab name | ✅ |
| Processing history | Processing tab (same js/processing-history.js) | ✅ |
| Feedback (target, thumbs, reasons, comment) | End of the Notes | ✅ |
| Audio playback | Player at the top of the Notes | ✅ |
| Live continuation audio preview | — | ❌ minor |
| "Ask anything" (disabled, coming soon) | — | n/a (was never live) |
| Coaching tab / stages | Not shown in v2 until its own ticket (Q41) | ❌ by decision |
| Hide plugins for one meeting | ⋯ › Hide plugins for this meeting (new; recording metadata plugins_excluded) | ✅ new |

## Suggested, To-dos, People, Memory

| Classic feature | Where in v2 | Status |
|---|---|---|
| To-dos page: open / done lists, tick, link to meeting | To-dos via the Surface contract (app.nav + app.page), filters To do / Done / All | ✅ |
| To-dos › Send to Slack | Selection bar (plugin selection action) | ✅ |
| To-dos › Suggested tab, nav count | Core Suggested page + sidebar count (only when pending); tab removed in v2 | ✅ |
| People list, add a person | People page | ✅ |
| Person: edit, seen in, merge | Person page | ✅ |
| Person Accounts (Confirm / Not them) | person.accounts rows | ✅ |
| Memory: search, add, merge, delete terms | Memory page | ✅ |

## Settings

| Classic panel | v2 panel | Status |
|---|---|---|
| Profile (name, role, About my work, Context for notes) | Profile | ✅ |
| Preferences (keep audio, open at login, tour) | Preferences | ✅ |
| Recording (Microphone, Refresh) | Recording | ✅ |
| Meeting types | Meeting types | ✅ |
| Processing & models (profile incl. Live captions; Whisper/notes models, download) | Processing & models (same js/processing.js, js/model-setup.js) | ✅ |
| Where models run (BYOK presets, test, load models, save) | Where models run (same js/providers.js) | ⚠️ "Use Google Cloud (Vertex AI)" credentials dialog not in v2 |
| Connections (connect, disconnect) | Connections, labels from the server | ✅ |
| Notion / Slack extras under Connections | One Settings panel per plugin (app.settings_section, drawn by Cora) | ✅ |
| Plugins on/off | Plugins (new; config.json plugins.<id>.enabled) | ✅ new |
| Claude / ChatGPT (MCP) | MCP | ✅ |
| Data & privacy (sizes, open data folder) | Data & privacy | ✅ |
| Beta (share, name, show shared, feedback, audio retention) | Beta | ✅ |
| Notifications & logs (list, view, bundle, send) | Notifications & logs | ✅ |

## Policy

| Rule | v2 | Status |
|---|---|---|
| Lockdown | Every plugin contribution is dropped server-side (both shells read the same endpoints) | ✅ |
| No plugin JS in the window | v2 loads no plugin script (lint + test) and names no plugin (boundary test) | ✅ |
| Nothing leaves the Mac without Confirm | Same Outbox confirm route | ✅ |

## Gaps for the owner

1. Live audio meters and the Microphone name on a live meeting.
2. Find in transcript / notes (⌘F).
3. Earlier version view shows notes only (no transcript).
4. Vertex AI credentials dialog (Where models run).
5. Onboarding runs in the classic look; tour slides still picture the classic look.
6. Detection hint and live continuation audio preview.
7. Coaching is not shown in v2 (its own ticket, Q41).
8. Under lockdown To-dos disappears from v2 too, because the spec drops every plugin contribution; classic keeps it. Decide whether To-dos (local only) should be exempt.
