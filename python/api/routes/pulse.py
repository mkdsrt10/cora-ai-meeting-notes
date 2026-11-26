"""What's new and the satisfaction survey (python/pulse.py).

GET  /api/pulse                 {whats_new: {version, title, items} | null, csat_due}
POST /api/pulse/whats-new       {version, helpful: up|down|null}
POST /api/pulse/csat            {score 1-5, comment?, trigger?} or {outcome: later|never}
"""
from __future__ import annotations

import pulse
from api.router import route


@route("GET", "/api/pulse")
def get_pulse(req, path: str, query: dict) -> None:
    return req.send_json(pulse.state())


@route("POST", "/api/pulse/whats-new")
def post_whats_new(req, path: str, body: dict) -> None:
    pulse.whats_new_closed(str(body.get("version") or ""), body.get("helpful"))
    return req.send_json({"ok": True})


@route("POST", "/api/pulse/csat")
def post_csat(req, path: str, body: dict) -> None:
    pulse.csat_answer(score=body.get("score"), comment=str(body.get("comment") or ""),
                      outcome=str(body.get("outcome") or "answered"), trigger=str(body.get("trigger") or "periodic"))
    return req.send_json({"ok": True})
