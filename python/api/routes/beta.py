"""Beta telemetry: Usage events from Electron main and the renderer, the
"Show what Cora shares" export, and the sender's status for Settings."""
from __future__ import annotations

from api.router import route
import paths
import usage_events

EXPORT_NAME = "usage-events-export.jsonl"


@route("POST", '/api/events')
def post_api_events(req, path: str, body: dict) -> None:
    event_id = usage_events.record(body.get("name"), body.get("payload", {}))
    return req.send_json({"ok": True, "id": event_id})


@route("GET", '/api/events/export')
def get_api_events_export(req, path: str, query: dict) -> None:
    out = usage_events.export_jsonl(paths.DATA_DIR / EXPORT_NAME)
    return req.send_json({"path": str(out)})


@route("GET", '/api/beta/status')
def get_api_beta_status(req, path: str, query: dict) -> None:
    # pending_captures, last_flush_at and last_error belong to the sender
    # (beta_sender / capture); null until those land.
    return req.send_json({"sharing_enabled": usage_events.sharing_enabled(),
                          "unsent_events": usage_events.unsent_count(),
                          "pending_captures": None, "last_flush_at": None, "last_error": None})
