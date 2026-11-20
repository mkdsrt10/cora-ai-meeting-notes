"""FakeConnection: stands in for connections.Connection in tests. Records every
request (method, path, json, query) and answers from a script, so tests never
reach Notion or Slack."""
from __future__ import annotations

import json
from typing import Any, Callable

import connections


class FakeConnection:
    def __init__(self, service: str = "notion"):
        self.service = service
        self.requests: list[dict[str, Any]] = []
        self.routes: dict[tuple[str, str], Any] = {}
        self.fail: dict[tuple[str, str], connections.ConnectionFailed] = {}

    def on(self, method: str, path: str, reply: Any | Callable[[dict], Any]) -> "FakeConnection":
        self.routes[(method, path)] = reply
        return self

    def request(self, method: str, path: str, json: dict | None = None, query: dict | None = None) -> dict:
        self.requests.append({"method": method, "path": path, "json": json, "query": query})
        if (method, path) in self.fail:
            raise self.fail.pop((method, path))
        reply = self.routes.get((method, path))
        if reply is None:
            for (m, p), r in self.routes.items():
                if m == method and p.endswith("*") and path.startswith(p[:-1]):
                    reply = r
                    break
        if callable(reply):
            reply = reply({"path": path, "json": json, "query": query})
        return reply if reply is not None else {"ok": True}

    def bodies(self) -> str:
        """Every request's path, query and body, as one string to search."""
        return "\n".join(json.dumps(r, default=str) for r in self.requests)
