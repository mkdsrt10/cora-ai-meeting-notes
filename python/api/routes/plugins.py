"""Plugin seam over HTTP: the renderer's plugin list, and every plugin's
routes under /api/plugins/<id>/<subpath> (see plugin_host)."""
from __future__ import annotations

import plugin_host
import recording_stage
from api.router import route


@route("GET", "/api/plugins")
def get_api_plugins(req, path: str, query: dict) -> None:
    return req.send_json({"plugins": plugin_host.views(), "stages": recording_stage.labels()})


@route("GET", "/api/plugins/", prefix=True)
def get_api_plugin_route(req, path: str, query: dict) -> None:
    handler = plugin_host.route_for("GET", path)
    if handler is None:
        return req.send_json({"error": "Unknown endpoint"}, 404)
    return handler(req, path, query)


@route("POST", "/api/plugins/", prefix=True)
def post_api_plugin_route(req, path: str, body: dict) -> None:
    handler = plugin_host.route_for("POST", path)
    if handler is None:
        return req.send_json({"error": "Unknown endpoint"}, 404)
    return handler(req, path, body)
