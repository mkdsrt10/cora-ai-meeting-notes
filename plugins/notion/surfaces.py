"""What Notion shows in the Surfaces Cora draws (ADR 0005), and its Actions.

Recording: one chip per Action item for its open Proposal or Link, the
meeting-level suggestion row, a "Notion" property row when the Recording
itself is Linked, and "Suggest again" in the ⋯ menu and ⌘K.
App: the Settings section (loaded only when you open it: the database list
and schema are listing calls, never made in the background) and ⌘K "Refresh
Notion Tasks". Person: the Notion Account row.
Every network call here is a listing call (ADR 0002); writes stay Proposals.
"""
from __future__ import annotations

from typing import Any

import connections
from surfaces import (Action, Contribution, SurfaceContext, SurfaceError, account_actions, account_row, outbox_chips,
                      outbox_footer)

from . import routes, tasks

MAP = (("title", "Title", ("title",)), ("status", "Status", ("status", "select", "checkbox")),
       ("assignee", "Assignee", ("people",)), ("due", "Due date", ("date",)),
       ("area", "Area", ("select",)), ("meeting", "Meeting (relation)", ("relation",)))


def surfaces(ctx: SurfaceContext) -> list[Contribution]:
    connected = connections.connected("notion")
    if ctx.context == "recording":
        out = outbox_chips(ctx, "Notion") + outbox_footer(ctx, "Notion suggestion")
        for link in ctx.links:
            if not link.get("action_item_id"):
                out.append(Contribution("recording.property", "annotation", "Notion", target=ctx.id,
                                        detail="Call Log ✓", url=link.get("url") or None, icon="notion"))
        if connected:
            out.append(Contribution("recording.menu", "action", "Suggest again (Notion)", icon="notion",
                                    action=Action("suggest_again", "recording")))
        return out
    if ctx.context == "app" and connected:
        return [
            Contribution("app.settings_section", "panel", "Notion", id="notion", icon="notion",
                         panel={"title": "Notion", "load": "settings_form", "blocks": [
                             {"type": "text", "text": "Your Tasks database, how its properties map, and your Usage instructions."}]}),
            Contribution("app.command", "action", "Refresh Notion Tasks", icon="notion", action=Action("refresh_tasks", "app")),
        ]
    if ctx.context == "person" and connected:
        return [account_row(ctx.id or "", "notion", "Notion")]
    return []


def _options(values: list[tuple[str, str]], current: str | None, empty: str = "—") -> list[dict[str, str]]:
    return [{"value": "", "label": empty}] + [{"value": v, "label": label} for v, label in values]


def settings_form(ctx) -> dict[str, Any]:
    """The Notion Settings section, built when the user opens it. Changing the
    database saves it and redraws the property mapping."""
    s = tasks.settings()
    _apply_link(ctx.values)
    chosen = ctx.values.get("database_id")
    if chosen and chosen != s.get("database_id"):
        tasks.save_settings({"database_id": chosen, "database_title": str(ctx.values.get("database_title") or ""),
                             "data_sources": ctx.values.get("data_sources") or [], "mapping": {}})
        tasks.refresh(force=True)
        s = tasks.settings()
    source = ctx.values.get("data_source_id")
    if source and not chosen and source != s.get("data_source_id"):
        tasks.save_settings({"data_source_id": source, "mapping": {}})
        tasks.refresh(force=True)
        s = tasks.settings()
    try:
        conn = connections.get("notion")
        props = routes.schema(conn) if s.get("database_id") else []
        s = tasks.settings()
    except connections.NotConnected:
        raise SurfaceError("not_connected", 409) from None
    except connections.BlockedByPolicy:
        raise SurfaceError("blocked_policy", 403) from None
    except connections.ConnectionFailed as exc:
        raise SurfaceError(f"notion_{exc.kind}", 502) from None
    mapping = s.get("mapping") or {}
    title = s.get("database_title") or "Untitled"
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": f"Tasks database: {title}" if s.get("database_id") else "No Tasks database picked yet."},
        {"type": "field", "name": "database_link", "label": "Change database" if s.get("database_id") else "Tasks database link",
         "input": "text", "value": "", "reload": True, "placeholder": "https://www.notion.so/…",
         "help": "In Notion, open your Tasks database and use ⋯ → Copy link, then paste it here."}]
    sources = s.get("data_sources") or []
    if len(sources) > 1:
        blocks.append({"type": "field", "name": "data_source_id", "label": "Data source with your Tasks", "input": "select",
                       "value": s.get("data_source_id") or "", "reload": True,
                       "options": [{"value": d["id"], "label": d["name"] or "Untitled"} for d in sources]})
    if s.get("database_id"):
        for key, label, types in MAP:
            blocks.append({"type": "field", "name": f"mapping.{key}", "label": label, "input": "select",
                           "value": mapping.get(key, ""),
                           "options": _options([(p["name"], p["name"]) for p in props if p["type"] in types], mapping.get(key))})
        status = next((p for p in props if p["name"] == mapping.get("status")), None)
        if status and status["type"] != "checkbox":
            blocks.append({"type": "field", "name": "mapping.done_value", "label": "Status that means done", "input": "select",
                           "value": mapping.get("done_value", ""),
                           "options": _options([(o, o) for o in status["options"]], mapping.get("done_value"))})
    blocks.append({"type": "field", "name": "usage_instructions", "label": "Notion Usage instructions", "input": "textarea",
                   "value": s.get("usage_instructions") or tasks.STARTER_INSTRUCTIONS, "maxlength": 4000})
    at = tasks.fetched_at()
    blocks.append({"type": "text", "muted": True, "text": "Suggestions are made on this Mac with your notes model. Open Task titles are "
                   "used as context for notes; when your notes model is a cloud one, those titles go to it. "
                   f"Cached: {len(tasks.all_tasks())} Tasks{' · ' + at.strftime('%d %b %H:%M') if at else ''}."})
    return {"panel": {"title": "Notion", "blocks": blocks, "submit": "save_settings",
                      "buttons": [{"label": "Refresh Tasks", "action": "refresh_tasks"}]}}


def _apply_link(values: dict) -> None:
    """A pasted database link wins over the dropdown: it resolves to that database."""
    link = str(values.get("database_link") or "").strip()
    if not link:
        return
    try:
        found = routes.database_from_link(connections.get("notion"), link)
    except connections.NotConnected:
        raise SurfaceError("not_connected", 409) from None
    except connections.BlockedByPolicy:
        raise SurfaceError("blocked_policy", 403) from None
    except connections.ConnectionFailed as exc:
        raise SurfaceError(f"notion_{exc.kind}", 502) from None
    values["database_id"], values["database_title"], values["data_sources"] = found["id"], found["title"], found["data_sources"]


def save_settings(ctx) -> dict[str, Any]:
    v = ctx.values
    _apply_link(v)
    mapping = {k.split(".", 1)[1]: val for k, val in v.items() if k.startswith("mapping.") and val}
    before = tasks.settings().get("database_id")
    body: dict[str, Any] = {"mapping": mapping}
    if "usage_instructions" in v:
        body["usage_instructions"] = str(v["usage_instructions"] or "")
    if v.get("database_id") and v["database_id"] != before:
        # A different database: the old property mapping doesn't apply to it.
        body.update(database_id=v["database_id"], database_title=str(v.get("database_title") or ""),
                    data_sources=v.get("data_sources") or [], mapping={})
    elif v.get("data_source_id") and v["data_source_id"] != tasks.settings().get("data_source_id"):
        body.update(data_source_id=v["data_source_id"], mapping={})
    saved = tasks.save_settings(body)
    if saved.get("database_id") != before:
        tasks.refresh(force=True)
    return {"toast": "Notion settings saved."}


def refresh_tasks(ctx) -> dict[str, Any]:
    tasks.refresh(force=True)
    routes.status_pull()
    return {"toast": f"{len(tasks.all_tasks())} Tasks cached."}


def suggest_again(ctx) -> dict[str, Any]:
    import outbox
    if not ctx.id:
        raise ValueError("id is required")
    made = outbox.refresh(ctx.id).get("notion", 0)
    return {"refresh": True, "toast": "Couldn't make suggestions." if made < 0 else f"{made} suggestion{'s' if made != 1 else ''}."}


ACTIONS = {"settings_form": settings_form, "save_settings": save_settings, "refresh_tasks": refresh_tasks,
           "suggest_again": suggest_again, **account_actions("notion")}
