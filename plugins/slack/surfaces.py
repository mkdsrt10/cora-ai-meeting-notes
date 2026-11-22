"""What Slack shows in the Surfaces Cora draws (ADR 0005), and its Actions.

Selection: "Send to Slack" on selected Action items (meeting page and the
To-dos page), which makes one message.post Proposal for the confirm panel.
Recording: a chip per Action item for its pending message and its Link.
App: the Settings section (Usage instructions; no network). Person: the
Slack Account row. Shown only while Slack is connected.
"""
from __future__ import annotations

from typing import Any

import connections
from surfaces import Action, Contribution, SurfaceContext, SurfaceError, account_actions, account_row, outbox_chips

from . import composer


def surfaces(ctx: SurfaceContext) -> list[Contribution]:
    if not connections.connected("slack"):
        return []
    send = Contribution("selection.action", "action", "Send to Slack", icon="slack", action=Action("send", "selection"))
    if ctx.context == "recording":
        return outbox_chips(ctx, "Slack") + [send]
    if ctx.context == "app":
        s = composer.settings()
        return [send, Contribution("app.settings_section", "panel", "Slack", id="slack", icon="slack", panel={
            "title": "Slack", "submit": "save_settings", "blocks": [
                {"type": "field", "name": "usage_instructions", "label": "Slack Usage instructions", "input": "textarea",
                 "value": s["usage_instructions"], "maxlength": 4000,
                 "placeholder": "Optional. Leave empty for the fixed template (no model). Example: casual tone, one line per item, tag owners."},
                {"type": "text", "muted": True, "text": "Slack messages are sent only from selected Action items, after you confirm the exact text and destination."},
            ]})]
    if ctx.context == "person":
        return [account_row(ctx.id or "", "slack", "Slack")]
    return []


def send(ctx) -> dict[str, Any]:
    if not ctx.action_item_ids:
        raise ValueError("Select at least one Action item")
    try:
        return {"proposal": composer.compose(ctx.action_item_ids)}
    except connections.NotConnected:
        raise SurfaceError("not_connected", 409) from None
    except connections.BlockedByPolicy:
        raise SurfaceError("blocked_policy", 403) from None
    except connections.ConnectionFailed as exc:
        raise SurfaceError(f"slack_{exc.kind}", 502) from None


def save_settings(ctx) -> dict[str, Any]:
    text = str(ctx.values.get("usage_instructions") or "")
    if len(text) > 4000:
        raise ValueError("Usage instructions must be at most 4000 characters")
    import outbox
    outbox.save_plugin_settings(composer.PLUGIN_ID, {"usage_instructions": text.strip()})
    return {"toast": "Slack settings saved."}


ACTIONS = {"send": send, "save_settings": save_settings, **account_actions("slack")}
