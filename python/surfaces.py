"""Surface contract (ADR 0005, docs/specs/ui-shell-v2.md): Cora draws every
plugin surface; a Plugin only supplies data for it.

A Surface is a place in the app attached to a Cora object (the app, a
Recording, an Action item, a selection, a Person, a Folder). A Plugin fills
Surfaces by declaring ``surfaces(ctx) -> [Contribution]`` next to its
``proposer`` and ``context_sources``, and the handlers its Actions run as
``actions = {id: fn(ActionContext) -> dict}``.

Host-facing:
    contributions(context, id=None, params=None) -> [dict]   # GET /api/surfaces
    run_action(plugin_id, action_id, ...)        -> dict     # POST /api/surfaces/action
    set_excluded(recording_id, excluded)                       # "Hide plugins for this meeting"

Rules the host enforces, whatever a plugin returns:
- Only catalog surfaces, in the context they belong to; only the three kinds.
- Nothing under enterprise lockdown, nothing for a Recording excluded from
  plugins, nothing from a disabled plugin.
- One chip per Action item: pending Proposal first, then Link, then plugin
  order; the rest are marked hidden and counted behind "+N".
- Plugins never define keyboard shortcuts (there is no field for one) and
  never call each other: an Action runs only the named plugin's handler.
- One plugin raising costs only its own contributions (logged by type only).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

import db
import plugin_host
import policy

CONTEXTS = ("app", "recording", "person", "folder")
KINDS = ("annotation", "action", "panel")
APPLIES_TO = ("app", "recording", "selection", "action_item")
BLOCK_TYPES = ("text", "list", "kv", "link", "field")

# surface -> the contexts it can appear in
CATALOG: dict[str, tuple[str, ...]] = {
    "app.nav": ("app",),
    "app.nav_badge": ("app",),
    "app.page": ("app",),
    "app.settings_section": ("app",),
    "app.command": ("app",),
    "recording.property": ("recording",),
    "recording.notes_block": ("recording",),
    "recording.tab": ("recording",),
    "recording.footer": ("recording",),
    "recording.menu": ("recording",),
    "action_item.chip": ("recording",),
    "action_item.hover": ("recording",),
    "action_item.menu": ("recording",),
    "action_item.on_done": ("recording",),
    "selection.action": ("app", "recording"),
    "person.accounts": ("person",),
    "folder.defaults": ("folder",),
}

CHIP_RANK = {"pending": 0, "failed": 0, "link": 1}


class SurfaceError(RuntimeError):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True)
class Action:
    id: str
    applies_to: str = "recording"


@dataclass(frozen=True)
class Contribution:
    surface: str
    kind: str
    label: str = ""
    id: str | None = None              # app.page id an app.nav opens; a stable id otherwise
    target: str | None = None          # action_item id, recording id, person id ...
    icon: str | None = None
    url: str | None = None
    badge: int | str | None = None
    detail: str | None = None          # secondary text (e.g. an Account's state)
    state: str | None = None           # chip: pending | failed | link
    action: Action | None = None
    panel: dict[str, Any] | None = None    # {title, blocks: [{type, ...}], submit?: action id}
    proposal_key: str | None = None


@dataclass
class SurfaceContext:
    """What a plugin's surfaces() gets: read-only data for one context."""
    plugin_id: str
    context: str
    id: str | None
    recording: dict[str, Any] | None = None
    action_items: list[dict[str, Any]] = field(default_factory=list)
    proposals: list[dict[str, Any]] = field(default_factory=list)   # this plugin's, any state
    links: list[dict[str, Any]] = field(default_factory=list)       # this plugin's
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ActionContext:
    plugin_id: str
    action_id: str
    context: str
    id: str | None
    action_item_ids: list[str]
    values: dict[str, Any]


def _log(plugin_id: str, where: str, exc: BaseException) -> None:
    print(f"[surfaces] {plugin_id}: {where} failed ({type(exc).__name__})", flush=True)


# ---- excluded Recordings ------------------------------------------------------

def is_excluded(recording: dict[str, Any] | None) -> bool:
    return bool(((recording or {}).get("metadata") or {}).get("plugins_excluded"))


def set_excluded(recording_id: str, excluded: bool) -> None:
    if not db.get_recording(recording_id):
        raise FileNotFoundError(recording_id)
    db.set_recording_metadata(recording_id, plugins_excluded=bool(excluded))


# ---- helpers a plugin uses to declare its Outbox records as chips -------------

def proposal_label(p: dict[str, Any]) -> str:
    verb = {"task.create": "Create task", "task.link": "Link to task", "task.update": "Update task",
            "task.comment": "Comment on task", "message.post": "Send message", "page.create": "Create page"}
    label = verb.get(p.get("kind"), p.get("kind") or "Suggestion")
    title = (p.get("target") or {}).get("title")
    return f"{label}: {title}" if title else label


def outbox_chips(ctx: SurfaceContext, service_label: str) -> list[Contribution]:
    """Chips for this plugin's open Proposals and Links on the Recording's Action items."""
    chips: list[Contribution] = []
    for p in ctx.proposals:
        if p.get("state") not in ("pending", "failed"):
            continue
        for item_id in p.get("action_item_ids") or []:
            chips.append(Contribution("action_item.chip", "annotation", proposal_label(p), target=item_id,
                                      state=p["state"], proposal_key=p["key"], icon=ctx.plugin_id))
    for link in ctx.links:
        if link.get("action_item_id"):
            chips.append(Contribution("action_item.chip", "annotation", service_label, target=link["action_item_id"],
                                      url=link.get("url") or None, state="link", icon=ctx.plugin_id))
    return chips


def outbox_footer(ctx: SurfaceContext, noun: str) -> list[Contribution]:
    """The meeting-level suggestion row: this plugin's open Proposals for the Recording."""
    open_ = [p for p in ctx.proposals if p.get("state") in ("pending", "failed")]
    if not open_:
        return []
    return [Contribution("recording.footer", "annotation", f"{len(open_)} {noun}{'s' if len(open_) != 1 else ''}",
                         target=ctx.id, badge=len(open_), icon=ctx.plugin_id,
                         proposal_key=open_[0]["key"])]


# ---- the read side ------------------------------------------------------------

def _context_for(plugin_id: str, context: str, target: str | None, recording: dict | None,
                 items: list, params: dict[str, str]) -> SurfaceContext:
    proposals: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    if context == "recording" and target:
        import outbox
        proposals = [p for p in outbox.for_recording(target) if p["plugin_id"] == plugin_id]
        links = [lk for lk in outbox.links(recording_id=target) if lk["plugin_id"] == plugin_id]
    return SurfaceContext(plugin_id, context, target, recording, items, proposals, links, dict(params))


def _valid(plugin_id: str, context: str, c: Any) -> bool:
    if not isinstance(c, Contribution):
        _log(plugin_id, "contribution type", TypeError())
        return False
    if context not in CATALOG.get(c.surface, ()):
        _log(plugin_id, f"surface {c.surface} in {context}", ValueError())
        return False
    if c.kind not in KINDS or (c.action is not None and c.action.applies_to not in APPLIES_TO):
        _log(plugin_id, f"kind {c.kind}", ValueError())
        return False
    if c.panel is not None and any(b.get("type") not in BLOCK_TYPES for b in c.panel.get("blocks") or []):
        _log(plugin_id, "panel block", ValueError())
        return False
    return True


def _public(plugin_id: str, c: Contribution) -> dict[str, Any]:
    value = {k: v for k, v in asdict(c).items() if v is not None}
    value["plugin_id"] = plugin_id
    return value


def order_chips(rows: list[dict[str, Any]], plugin_order: list[str]) -> list[dict[str, Any]]:
    """One chip per Action item: the first by (pending Proposal, Link, other),
    then plugin order, then declared order; the rest hidden behind '+N'."""
    chips = [r for r in rows if r["surface"] == "action_item.chip"]
    others = [r for r in rows if r["surface"] != "action_item.chip"]
    by_target: dict[str, list[tuple[int, dict]]] = {}
    for n, chip in enumerate(chips):
        by_target.setdefault(chip.get("target") or "", []).append((n, chip))
    ordered: list[dict[str, Any]] = []
    for target, group in by_target.items():
        group.sort(key=lambda nc: (CHIP_RANK.get(nc[1].get("state") or "", 2),
                                   plugin_order.index(nc[1]["plugin_id"]) if nc[1]["plugin_id"] in plugin_order else 99,
                                   nc[0]))
        for rank, (_, chip) in enumerate(group):
            chip = {**chip, "shown": rank == 0}
            if rank == 0:
                chip["more"] = len(group) - 1
            ordered.append(chip)
    return others + ordered


def contributions(context: str, target: str | None = None, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every enabled plugin's contributions for one context, filtered and ordered."""
    if context not in CONTEXTS:
        raise ValueError("unknown context")
    if context != "app" and not target:
        raise ValueError("id is required")
    if policy.lockdown_enabled():
        return []
    recording = None
    items: list[dict[str, Any]] = []
    if context == "recording":
        recording = db.get_recording(target)
        if recording is None:
            raise FileNotFoundError(target)
        if is_excluded(recording):
            return []
        import action_items
        items = action_items.for_recording(target)
    enabled = [p for p in plugin_host.enabled_plugins() if p.surfaces is not None]
    rows: list[dict[str, Any]] = []
    for p in enabled:
        try:
            declared = list(p.surfaces(_context_for(p.id, context, target, recording, items, params or {})) or [])
        except Exception as exc:  # one plugin failing never hides the others
            _log(p.id, "surfaces", exc)
            continue
        rows += [_public(p.id, c) for c in declared if _valid(p.id, context, c)]
    return order_chips(rows, [p.id for p in enabled])


# ---- the action side -----------------------------------------------------------

def run_action(plugin_id: str, action_id: str, *, context: str = "app", target: str | None = None,
               action_item_ids: Iterable[str] = (), values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one plugin's Action handler; never another plugin's.

    The handler returns a dict the renderer understands: {proposal} opens the
    confirm panel, {panel} redraws the section, {toast}, {refresh: true}."""
    if context not in CONTEXTS:
        raise ValueError("unknown context")
    if policy.lockdown_enabled():
        raise SurfaceError("blocked_policy", 403)
    plugin = next((p for p in plugin_host.enabled_plugins() if p.id == plugin_id), None)
    handler: Callable[[ActionContext], dict] | None = plugin.actions.get(action_id) if plugin else None
    if handler is None:
        raise SurfaceError("unknown_action", 404)
    ids = [str(i) for i in action_item_ids]
    recording_ids = {target} if context == "recording" and target else set()
    if ids:
        import action_items
        found = [action_items.get(i) for i in ids]
        if any(f is None for f in found):
            raise SurfaceError("unknown_action_item", 404)
        recording_ids |= {f["recording_id"] for f in found if f}
    for rid in recording_ids:
        if is_excluded(db.get_recording(rid)):
            raise SurfaceError("excluded", 409)
    try:
        result = handler(ActionContext(plugin_id, action_id, context, target, ids, dict(values or {})))
    except (ValueError, FileNotFoundError, SurfaceError):
        raise
    except Exception as exc:
        _log(plugin_id, f"action {action_id}", exc)
        raise SurfaceError("action_failed", 500) from None
    return result if isinstance(result, dict) else {"ok": True}
