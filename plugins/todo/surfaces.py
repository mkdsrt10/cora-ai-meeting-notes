"""To-dos on the Surface contract (ADR 0005, UI shell v2 T6).

App: a nav item and a page Cora draws: the Action items of every processed
Recording as lists (open, done, or all, as a filter), each linked to its
meeting; and "Mark done" for selected items. Turning To-dos off removes all
of it. Ticking and Mark done change the core Action item record. The classic
shell keeps its own page (src/ui/web/plugins/todo.js).
"""
from __future__ import annotations

from typing import Any

import action_items
from surfaces import Action, Contribution, SurfaceContext

from . import store

FILTERS = (("open", "To do"), ("done", "Done"), ("all", "All"))


def _item(i: dict[str, Any]) -> dict[str, Any]:
    return {"id": i["id"], "text": i["text"], "owner": i["owner"], "due": i["due"], "done": bool(i["done"]),
            "recording_id": i["recording_id"], "recording_title": i["recording_title"]}


def page_blocks(filter_id: str) -> list[dict[str, Any]]:
    items = store.listed()
    open_ = [_item(i) for i in items if not i["done"]]
    done = [_item(i) for i in items if i["done"]]
    if not items:
        return [{"type": "text", "muted": True, "text": "No Action items yet. They show up here once a meeting's notes are ready."}]
    blocks = []
    if filter_id in ("open", "all"):
        blocks.append({"type": "list", "selectable": True, "items": open_, "empty": "Everything is done."})
    if filter_id in ("done", "all"):
        blocks.append({"type": "list", "title": "Done" if filter_id == "all" else None, "selectable": True, "items": done,
                       "empty": "Nothing done yet."})
    return blocks


def surfaces(ctx: SurfaceContext) -> list[Contribution]:
    if ctx.context != "app":
        return []
    filter_id = ctx.params.get("filter") if ctx.params.get("filter") in dict(FILTERS) else "open"
    return [
        Contribution("app.nav", "action", "To-dos", id="todos", icon="check"),
        Contribution("app.page", "panel", "To-dos", id="todos", icon="check", panel={
            "title": "To-dos", "subtitle": "Action items from your meetings, in one list.",
            "filters": [{"id": f, "label": label} for f, label in FILTERS], "filter": filter_id,
            "blocks": page_blocks(filter_id)}),
        Contribution("selection.action", "action", "Mark done", icon="check", action=Action("mark_done", "selection")),
    ]


def mark_done(ctx) -> dict[str, Any]:
    if not ctx.action_item_ids:
        raise ValueError("Select at least one Action item")
    for key in ctx.action_item_ids:
        action_items.set_done(key, True)
    n = len(ctx.action_item_ids)
    return {"refresh": True, "toast": f"Marked {n} done."}


ACTIONS = {"mark_done": mark_done}
