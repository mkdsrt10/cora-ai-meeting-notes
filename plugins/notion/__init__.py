"""Notion plugin (spec §Notion plugin; ADR 0002, 0003).

Links meetings to the user's own Notion Tasks: after processing it suggests,
per Action item, linking to an open Task or creating one (Proposals the user
confirms in the confirm panel); a Task done in Notion marks its Linked To-do
done, and ticking a Linked To-do done suggests "Mark done in Notion".

Acts only when the user has connected Notion (Settings > Connections) and
picked a Tasks database. Matching runs on the Recording's configured Text
model, local included. The old cora-notion-sync script keeps writing Call
Log pages (Q60); its areas and skip-people rules moved into the Usage
instructions starter template.
"""
from __future__ import annotations

from plugin_host import Plugin

from . import proposer, routes, sources, tasks


def after_meeting(recording_id: str) -> None:
    tasks.refresh()          # only when older than 15 minutes; lists the database, no meeting content


def daily() -> None:
    tasks.refresh(force=True)
    routes.status_pull()


PLUGIN = Plugin(
    id="notion",
    name="Notion",
    routes=(
        ("GET", "settings", routes.get_settings),
        ("POST", "settings", routes.post_settings),
        ("GET", "databases", routes.get_databases),
        ("GET", "schema", routes.get_schema),
        ("POST", "refresh", routes.post_refresh),
    ),
    hooks={"after_meeting": after_meeting, "daily": daily},
    enabled_by_default=True,
    connection="notion",
    proposer=proposer.NotionProposer(),
    context_sources=(sources.NotionTasks(),),
)
