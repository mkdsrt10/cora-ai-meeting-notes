"""Route registry for the local API.

Handlers are plain functions registered with @route; they receive the
request handler (for send_json/serve_file/headers), the path, and either the
parsed query string (GET) or the JSON body (POST).
"""
from __future__ import annotations

from typing import Any, Callable

Handler = Callable[[Any, str, dict], None]
_exact: dict[tuple[str, str], Handler] = {}
_prefix: list[tuple[str, str, Handler]] = []


def route(method: str, *paths: str, prefix: bool = False) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        for p in paths:
            if prefix:
                _prefix.append((method, p, fn))
            elif (method, p) in _exact:
                raise ValueError(f"duplicate route {method} {p}")
            else:
                _exact[(method, p)] = fn
        return fn
    return register


def match(method: str, path: str) -> Handler | None:
    fn = _exact.get((method, path))
    if fn:
        return fn
    for m, p, handler in _prefix:
        if m == method and path.startswith(p):
            return handler
    return None


def registered() -> list[tuple[str, str]]:
    return sorted(set(_exact) | {(m, p) for m, p, _ in _prefix})
