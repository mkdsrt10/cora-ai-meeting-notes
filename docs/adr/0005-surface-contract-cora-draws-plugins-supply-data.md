---
status: accepted
date: 2026-11-22
spec: docs/specs/ui-shell-v2.md
design: docs/planning/plugins-connectors-and-context.md §13.10 (Q32–Q41, Q63–Q66)
---

# Surface contract: Cora draws every plugin surface; plugins only supply data

## Context

The new UI shell has to leave room for plugins that don't exist yet (Linear, Teams, email, a
morning brief) without a redesign each time. Two options: let each plugin ship its own UI code
into the app window, as To-dos and Coaching do today, or have Cora own a fixed catalog of places
a plugin can fill and draw them itself. Own-UI plugins are faster to write but look different
from Cora, can break the app, and mean third-party code runs where meeting content is shown,
which is hard to review for users with strict data rules.

## Decision

- **Catalog.** Every surface hangs off a Cora object: App (nav item and badge, page, Settings
  section, ⌘K command), Recording (property row, Notes block, tab, footer suggestion, ⋯ menu),
  Action item (inline chip, hover icon, ⋯ menu, on done), Selection (selection-bar action),
  Person (Accounts row), Folder (defaults). A surface with nothing in it is not drawn.
- **Kinds.** A plugin contributes an Annotation (shows something), an Action (something you
  trigger) or a Panel (a block of content) as data. Cora renders it with its own components.
- **External writes are Proposals** (ADR 0002), drawn by type (`task.create|link|update|comment`,
  `message.post`, `page.create`) in one right-side confirm panel, never per plugin.
- **Rules.** One chip per Action item (pending Proposal, then Link, then plugin order; extras
  behind "+N"). Cora owns every keyboard shortcut; plugin actions are reached via ⌘K, the
  selection bar or the ⋯ menu. Plugins never call each other; they meet through core records
  (Action item, Link, Account). Cora drops contributions under lockdown, for Recordings excluded
  from plugins, and for disabled plugins; a plugin can't override this.
- New surfaces are added only when a real plugin needs one.

## Consequences

- Every plugin looks and behaves like Cora, and turning one off removes it everywhere.
- No plugin JavaScript runs in the app window. To-dos and Coaching move onto the contract
  (To-dos first); until then they are the only exceptions.
- A plugin that needs a surface outside the catalog waits for Cora to add it.
- A new tool of an existing type (Linear for tasks, Teams for messages) needs no new UI.
