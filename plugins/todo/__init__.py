"""Cora Todo/Planner plugin (skeleton).

One page listing the Action items from every processed Recording. Its
after_meeting Hook stores each Recording's Action items as To-dos with stable
ids (store.py), so done marks survive reprocessing. Bundled and on by
default; turn it off with `plugins.todo.enabled: false` in config.json. Fully
local: it reads notes already in the database and calls no model.
"""
from __future__ import annotations

from plugin_host import Plugin, View

from . import items

PLUGIN = Plugin(
    id="todo",
    name="To-dos",
    view=View(title="To-dos", subtitle="Action items from your meetings, in one list.", icon="check"),
    routes=(("GET", "items", items.get_items), ("POST", "done", items.post_done)),
    hooks={"after_meeting": items.after_meeting},
    enabled_by_default=True,
)
