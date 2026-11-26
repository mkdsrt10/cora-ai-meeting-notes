"""Outbox and Connections over HTTP (ADR 0002, 0003; see outbox.py, connections.py).

GET  /api/outbox?recording=<id>          pending Proposals (all meetings when no id)
GET  /api/outbox/recording?id=<id>       every Proposal of one Recording (chips), any state
GET  /api/outbox/count                   pending count, for the To-dos nav badge
POST /api/outbox/refresh                 {recording_id}: "Suggest again"
POST /api/outbox/confirm                 {key, edits?}: the user's click; the only write path
POST /api/outbox/dismiss                 {key}
POST /api/outbox/restore                 {key}: undo a dismiss (pending again; nothing is sent)
GET  /api/outbox/dismissed               dismissed in the last 30 days, newest first
GET  /api/links?recording=<id>
GET  /api/connections                    {service: {connected, account_label, blocked_policy}}
POST /api/connections/connect            {service, token}: token goes to the Keychain only
POST /api/connections/disconnect         {service}
GET  /api/person/accounts?id=<person>    Notion/Slack Account per connected service
POST /api/person/accounts/confirm|reject {person_id, service, external_id}
"""
from __future__ import annotations

import connections
import outbox
from api.router import route


def _q(query: dict, name: str) -> str:
    return (query.get(name) or [""])[0]


def _error(req, exc: outbox.OutboxError) -> None:
    return req.send_json({"error": exc.code}, exc.status)


@route("GET", "/api/outbox")
def get_outbox(req, path: str, query: dict) -> None:
    recording_id = _q(query, "recording") or None
    items = outbox.pending(recording_id)
    return req.send_json({"proposals": items, "count": len(items)})


@route("GET", "/api/outbox/recording")
def get_outbox_recording(req, path: str, query: dict) -> None:
    return req.send_json({"proposals": outbox.for_recording(_q(query, "id")),
                          "links": outbox.links(recording_id=_q(query, "id"))})


@route("GET", "/api/outbox/count")
def get_outbox_count(req, path: str, query: dict) -> None:
    return req.send_json({"count": outbox.count()})


@route("POST", "/api/outbox/refresh")
def post_outbox_refresh(req, path: str, body: dict) -> None:
    recording_id = str(body.get("recording_id") or "")
    if not recording_id:
        raise ValueError("recording_id is required")
    return req.send_json({"ok": True, "plugins": outbox.refresh(recording_id),
                          "proposals": outbox.for_recording(recording_id)})


@route("POST", "/api/outbox/confirm")
def post_outbox_confirm(req, path: str, body: dict) -> None:
    edits = body.get("edits") or {}
    if not isinstance(edits, dict):
        raise ValueError("edits must be an object")
    try:
        row = outbox.confirm(str(body.get("key") or ""), edits, click=outbox.UserClick("ui"))
    except outbox.OutboxError as exc:
        return _error(req, exc)
    return req.send_json({"ok": True, "proposal": row})


@route("POST", "/api/outbox/dismiss")
def post_outbox_dismiss(req, path: str, body: dict) -> None:
    try:
        row = outbox.dismiss(str(body.get("key") or ""))
    except outbox.OutboxError as exc:
        return _error(req, exc)
    return req.send_json({"ok": True, "proposal": row})


@route("POST", "/api/outbox/restore")
def post_outbox_restore(req, path: str, body: dict) -> None:
    try:
        row = outbox.restore(str(body.get("key") or ""))
    except outbox.OutboxError as exc:
        return _error(req, exc)
    return req.send_json({"ok": True, "proposal": row})


@route("GET", "/api/outbox/dismissed")
def get_outbox_dismissed(req, path: str, query: dict) -> None:
    return req.send_json({"proposals": outbox.dismissed()})


@route("GET", "/api/links")
def get_links(req, path: str, query: dict) -> None:
    return req.send_json({"links": outbox.links(recording_id=_q(query, "recording") or None)})


@route("GET", "/api/connections")
def get_connections(req, path: str, query: dict) -> None:
    return req.send_json({"connections": connections.status()})


@route("POST", "/api/connections/connect")
def post_connection_connect(req, path: str, body: dict) -> None:
    service = str(body.get("service") or "")
    try:
        state = connections.connect(service, str(body.get("token") or ""))
    except connections.BlockedByPolicy:
        return req.send_json({"error": "blocked_policy"}, 403)
    except connections.ConnectionFailed as exc:
        return req.send_json({"error": f"check_failed:{exc.kind}"}, 400)
    return req.send_json({"ok": True, "connection": state})


@route("POST", "/api/connections/disconnect")
def post_connection_disconnect(req, path: str, body: dict) -> None:
    connections.disconnect(str(body.get("service") or ""))
    return req.send_json({"ok": True, "connections": connections.status()})


# ---- Accounts on the Person page (accounts.py) --------------------------------

@route("GET", "/api/person/accounts")
def get_person_accounts(req, path: str, query: dict) -> None:
    import accounts
    person_id = _q(query, "id")
    result = {}
    for service in connections.SERVICES:
        if not connections.connected(service):
            continue
        accounts.refresh_users(service)   # names only; no meeting content
        result[service] = accounts.account_state(person_id, service)
    return req.send_json({"accounts": result})


@route("POST", "/api/person/accounts/confirm", "/api/person/accounts/reject")
def post_person_account(req, path: str, body: dict) -> None:
    import accounts
    service = str(body.get("service") or "")
    if service not in connections.SERVICES:
        raise ValueError("unknown service")
    action = accounts.confirm if path.endswith("/confirm") else accounts.reject
    action(str(body.get("person_id") or ""), service, str(body.get("external_id") or ""))
    return req.send_json({"ok": True, "account": accounts.account_state(str(body.get("person_id") or ""), service)})
