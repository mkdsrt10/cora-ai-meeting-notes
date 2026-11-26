---
status: accepted
date: 2026-11-18
spec: docs/planning/plugins-connectors-and-context.md
---

# Connections are personal and act as the user

## Context

Notion and Slack could be reached through one team-wide integration (a "Cora" bot, an
admin-installed workspace app, a shared token), or each user could connect their own account.
Cora runs on one Mac for one person, and each user uses these tools in their own way.

## Decision

- Each Connection belongs to one user on one Install, and its token is stored in that Mac's
  Keychain. There are no shared tokens, no team bot and no Cora server in the token path.
- Slack writes post as the user, using a user token, never a bot.
- Notion writes go through the user's own integration. Notion's API records the integration as
  author, so "as the user" in Notion means: the user's workspace and pages, the user as
  Assignee, and an optional "via Cora" footer. To verify against current API behaviour in the
  P0 spike.
- How a user wants each tool used lives in that Plugin's per-user Usage instructions, not in
  a Cora default.

## Consequences

- Each external tool's own audit log attributes every write to a person. A Cora audit row
  records the write too, holding a hash rather than content.
- Every user connects their own accounts. There is no central admin view of who connected
  what, beyond the admin policy that can disable a Connection outright.
- A team-wide bot later would mean a second Connection kind and a new ADR, not a change to
  this one.
