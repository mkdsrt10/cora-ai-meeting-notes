---
status: accepted
date: 2026-11-18
spec: docs/planning/plugins-connectors-and-context.md
---

# External writes are Proposals the user confirms; automatic calls carry no meeting content

## Context

Notion and Slack Plugins write to tools other people read. Some users work under regulatory and
contractual data rules, and a Recording's transcript holds words spoken by people outside
the user's organization. The obvious alternative is an LLM agent with Notion/Slack write tools,
or rules such as "always post to #standup". The first lets transcript text steer real writes
(prompt injection). Both send meeting content out of the Mac with nobody looking.

## Decision

- A Plugin never writes to an external tool itself. It returns typed **Proposals**.
- The host's Outbox applies a Proposal only when the user clicks Confirm in the UI. There is no
  auto-apply, no auto-send and no rule- or schedule-driven path to an external write.
- Automatic network calls (refreshing the list of Notion tasks, Slack channels or users) only
  list things from the external tool. Their requests carry no recording text, titles, notes or
  Action items. Matching runs against the copy of that list kept on the Mac.
- An LLM may suggest (match an Action item to a Task, draft a message). The host validates every
  suggested target against what it fetched. Writes contain only the confirmed payload.

## Consequences

- One code path for external writes, which can be audited, locked down and tested ("confirm is
  reachable only from a UI route"; "request bodies made during propose contain no recording text").
- The user does more clicks. "Confirm all" on a Recording is the batch form, and it is still a click.
- Revisiting this (for example, an opt-in auto-send) needs a new ADR. It would also need a
  compliance review, because it changes what leaves the Mac unattended.
