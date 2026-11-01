"""Cora Todo/Planner plugin (skeleton).

One page listing the action items from every processed Recording, with a
done state kept in the todo_state table. Bundled and on by default; turn it
off with `plugins.todo.enabled: false` in config.json. Fully local: it reads
call summaries already in the database and calls no model.
"""
from __future__ import annotations

from plugin_host import Plugin, View

from . import items

PLUGIN = Plugin(
    id="todo",
    name="To-dos",
    view=View(title="To-dos", subtitle="Action items from your meetings, in one list.", icon="check"),
    routes=(("GET", "items", items.get_items), ("POST", "done", items.post_done)),
    enabled_by_default=True,
)
