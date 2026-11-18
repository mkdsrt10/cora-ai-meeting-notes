---
status: accepted
date: 2026-11-18
spec: docs/planning/plugins-connectors-and-context.md
---

# Action items are records shown in the Notes, not text parsed out of them

## Context

Notes become editable in place, like a Notion page. Action items carry identity that other
things depend on: To-do done marks, Links to Notion Tasks and Slack messages, and pending
Proposals. One option is to keep the Notes Markdown as the single source and parse Action items
back out of it after every edit. That is simple to store, but any rewording, reordering or
formatting slip would change ids and break done marks and Links.

## Decision

- Action items are core records: text, owner, optional due, done, provenance (AI or the user).
- The Notes show them as a live checklist block. Editing a row edits the record, and typing a
  new row creates one. The rest of the Notes is free Markdown.
- `enhanced_notes.md` on disk is rendered from both, so MCP, Export .md and Call Log pages
  still read one Markdown file.
- Records the user added or edited are never superseded by reprocessing, and AI records the user
  deleted are kept as deletions so they don't return.

## Consequences

- Ids, done marks, Links and Proposals survive edits and reprocessing.
- The editor needs one custom block (the Action item checklist) rather than plain Markdown
  everywhere.
- The Markdown file is an output, not the source. Editing it by hand outside Cora won't change
  Action items.
