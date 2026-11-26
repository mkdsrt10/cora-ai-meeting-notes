"""Slack plugin (spec §Slack plugin; Q29, Q30, Q57-Q59; ADR 0002, 0003).

Started by the user, never suggested: select Action items on the Recording
page or in To-dos, then "Send to Slack". That makes one message.post
Proposal holding all of them, shown in the confirm panel with the message
and destination editable. Confirm posts it once, as the user (user token),
and stores the permalink as a Link. No updates after posting; send again
instead. Reprocessing never posts anything.

"To": channels the user is a member of, a DM to themself, or a DM to a
Person with a confirmed Slack Account. Fetched when the composer opens
(names only, no meeting content). Defaults to the last destination used for
the Recording's folder.

Message: a fixed template (no model) with owners as mentions only when
their Slack Account is confirmed, else plain names. With Slack Usage
instructions written, the Recording's Text model drafts within them.
"""
from __future__ import annotations

from plugin_host import Plugin

from . import composer, surfaces

PLUGIN = Plugin(
    id="slack",
    name="Slack",
    routes=(
        ("GET", "settings", composer.get_settings),
        ("POST", "settings", composer.post_settings),
        ("POST", "compose", composer.post_compose),
    ),
    enabled_by_default=True,
    connection="slack",
    proposer=composer.SlackProposer(),
    surfaces=surfaces.surfaces,
    actions=surfaces.ACTIONS,
)
