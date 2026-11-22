"""Surface contract over HTTP (ADR 0005; see surfaces.py).

GET  /api/surfaces?context=app|recording|person|folder&id=<id>   contributions, filtered
POST /api/surfaces/action      {plugin_id, action_id, context, id?, action_item_ids?, values?}
POST /api/recording/plugins-excluded   {id, excluded}: "Hide plugins for this meeting"
"""
from __future__ import annotations

import surfaces
from api.router import route


def _q(query: dict, name: str) -> str:
    return (query.get(name) or [""])[0]


@route("GET", "/api/surfaces")
def get_surfaces(req, path: str, query: dict) -> None:
    context = _q(query, "context") or "app"
    target = _q(query, "id") or None
    params = {k: v[0] for k, v in query.items() if k not in ("context", "id") and v}
    try:
        rows = surfaces.contributions(context, target, params)
    except ValueError as exc:
        return req.send_json({"error": str(exc)}, 400)
    return req.send_json({"context": context, "id": target, "contributions": rows})


@route("POST", "/api/surfaces/action")
def post_surface_action(req, path: str, body: dict) -> None:
    ids = body.get("action_item_ids") or []
    values = body.get("values") or {}
    if not isinstance(ids, list) or len(ids) > 200 or not isinstance(values, dict):
        raise ValueError("action_item_ids must be a list and values an object")
    try:
        result = surfaces.run_action(str(body.get("plugin_id") or ""), str(body.get("action_id") or ""),
                                     context=str(body.get("context") or "app"), target=body.get("id") or None,
                                     action_item_ids=ids, values=values)
    except surfaces.SurfaceError as exc:
        return req.send_json({"error": exc.code}, exc.status)
    return req.send_json({"ok": True, **result})


@route("POST", "/api/recording/plugins-excluded")
def post_plugins_excluded(req, path: str, body: dict) -> None:
    surfaces.set_excluded(str(body.get("id") or ""), bool(body.get("excluded")))
    return req.send_json({"ok": True, "excluded": bool(body.get("excluded"))})
