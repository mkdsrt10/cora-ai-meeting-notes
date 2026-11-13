"""Beta telemetry: Usage events from Electron main and the renderer, the
"Show what Cora shares" export, and the sender's status for Settings."""
from __future__ import annotations

from api.router import route
import activity
import beta_sender
import feedback
import paths
import policy
import usage_events

EXPORT_NAME = "usage-events-export.jsonl"


@route("POST", '/api/events')
def post_api_events(req, path: str, body: dict) -> None:
    event_id = usage_events.record(body.get("name"), body.get("payload", {}))
    return req.send_json({"ok": True, "id": event_id})


@route("POST", '/api/activity')
def post_api_activity(req, path: str, body: dict) -> None:
    """One counted action ({action: id}) or active minute ({active_min: 1})."""
    activity.post(body)
    return req.send_json({"ok": True})


@route("POST", '/api/feedback')
def post_api_feedback(req, path: str, body: dict) -> None:
    result = feedback.submit(body.get("recording_id"), body.get("target"), body.get("rating"),
                             body.get("reasons"), body.get("comment", ""))
    return req.send_json({"ok": True, **result})


@route("GET", '/api/events/export')
def get_api_events_export(req, path: str, query: dict) -> None:
    out = usage_events.export_jsonl(paths.DATA_DIR / EXPORT_NAME)
    return req.send_json({"path": str(out)})


@route("GET", '/api/beta/status')
def get_api_beta_status(req, path: str, query: dict) -> None:
    return req.send_json({"sharing_enabled": usage_events.sharing_enabled(),
                          "unsent_events": usage_events.unsent_count(), **beta_sender.status()})


@route("GET", '/api/remote-config')
def get_api_remote_config(req, path: str, query: dict) -> None:
    """The remote config this start runs with (cached copy, else defaults),
    plus what the updater needs to judge it: version, variant, lockdown."""
    version, _commit = usage_events._versions()
    return req.send_json({**beta_sender.remote_config(), "app_version": version,
                          "build_variant": usage_events.build_variant(),
                          "lockdown": policy.lockdown_enabled()})
