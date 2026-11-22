"""Connections (ADR 0003): the user's own link to Notion or Slack.

    conn = connections.get("notion")           # NotConnected / BlockedByPolicy
    conn.request("POST", "/pages", json={...})  # -> dict; ConnectionFailed(kind)
    connections.connect(service, token) / disconnect(service) / status()

- The token is pasted by the user and kept only in the macOS Keychain under
  account ``connection.<service>``. It never reaches config.json, the DB,
  logs, Usage events or audit rows. Without a Keychain, connect refuses.
- Every request checks the outbound policy (lockdown refuses), retries
  rate-limited and transient failures with backoff (honouring Retry-After),
  and maps errors to ConnectionFailed(kind = auth | rate | transient | permanent).
- Each request is logged to ``logs/connections.jsonl`` with the service,
  method, path template, status and latency. Never a body or a query value.

Tests swap the network for a FakeConnection with ``use(service, fake)``.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

import credentials
import db
import paths
import policy

SERVICES = ("notion", "slack")
# How the UI names each service and hints its token, so a renderer can draw
# Settings › Connections from data alone (UI shell v2, ADR 0005).
DISPLAY = {"notion": ("Notion", "secret_… / ntn_…"), "slack": ("Slack", "xoxp-…")}
NOTION_VERSION = "2022-06-28"
MAX_ATTEMPTS = 3
_ID_SEGMENT = re.compile(r"^[0-9a-fA-F-]{16,}$|^[A-Z][A-Z0-9]{6,}$")


class NotConnected(RuntimeError):
    """No token for this service on this Mac."""


class BlockedByPolicy(RuntimeError):
    """Enterprise lockdown (or an admin policy) forbids this Connection."""


class ConnectionFailed(RuntimeError):
    def __init__(self, kind: str, status: int | None = None, code: str = ""):
        super().__init__(f"{kind}{f' ({status})' if status else ''}{f': {code}' if code else ''}")
        self.kind, self.status, self.code = kind, status, code

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate", "transient")


@dataclass(frozen=True)
class Adapter:
    service: str
    base_url: str
    headers: Callable[[str], dict[str, str]]
    # Slack answers HTTP 200 with {"ok": false, "error": ...}; Notion uses statuses.
    body_error: Callable[[dict], str | None] = lambda body: None
    whoami: tuple[str, str] = ("GET", "/")
    label: Callable[[dict], str] = lambda body: ""


def _slack_error(body: dict) -> str | None:
    return None if body.get("ok", True) else str(body.get("error") or "error")


ADAPTERS: dict[str, Adapter] = {
    "notion": Adapter(
        "notion", "https://api.notion.com/v1",
        lambda token: {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION},
        whoami=("GET", "/users/me"),
        label=lambda body: str((body.get("bot") or {}).get("workspace_name") or body.get("name") or ""),
    ),
    "slack": Adapter(
        "slack", "https://slack.com/api",
        lambda token: {"Authorization": f"Bearer {token}"},
        body_error=_slack_error,
        whoami=("POST", "/auth.test"),
        label=lambda body: " · ".join(x for x in (str(body.get("team") or ""), str(body.get("user") or "")) if x),
    ),
}

_SCHEMA = """CREATE TABLE IF NOT EXISTS connections (
    service TEXT PRIMARY KEY,
    account_label TEXT,
    connected_at TEXT NOT NULL,
    checked_at TEXT
)"""


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _ensure(conn) -> None:
    conn.execute(_SCHEMA)


# ---- token storage (Keychain only) -----------------------------------------

def _account(service: str) -> str:
    return f"connection.{service}"


class _Keychain:
    """Indirection so tests never touch the real login Keychain."""

    def set(self, account: str, secret: str) -> bool:
        return credentials._keychain_set(account, secret)

    def get(self, account: str) -> str | None:
        return credentials._keychain_get(account)

    def delete(self, account: str) -> bool:
        return credentials._keychain_delete(account)


keychain = _Keychain()


def _service(service: str) -> str:
    if service not in SERVICES:
        raise ValueError(f"unknown service {service!r}")
    return service


# ---- logging (no bodies) ---------------------------------------------------

def path_template(path: str) -> str:
    """'/pages/1f2e…/comments?x=y' -> '/pages/{id}/comments' (no ids, no query)."""
    bare = path.split("?", 1)[0]
    return "/".join("{id}" if _ID_SEGMENT.match(part) else part for part in bare.split("/"))


def _log(service: str, method: str, path: str, status: int | None, ms: float, outcome: str) -> None:
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with (paths.LOGS_DIR / "connections.jsonl").open("a") as handle:
            handle.write(json.dumps({"at": _now(), "service": service, "method": method,
                                     "path": path_template(path), "status": status,
                                     "ms": round(ms, 1), "outcome": outcome}) + "\n")
    except OSError:
        pass


# ---- the Connection --------------------------------------------------------

def _classify(status: int, code: str = "") -> str:
    if status in (401, 403) or code in ("invalid_auth", "not_authed", "token_revoked", "account_inactive"):
        return "auth"
    if status == 429 or code == "ratelimited":
        return "rate"
    if status >= 500 or status == 0:
        return "transient"
    return "permanent"


class Connection:
    """One service's HTTP client acting as the user. Stdlib only."""

    sleep = staticmethod(time.sleep)

    def __init__(self, adapter: Adapter, token: str):
        self.adapter = adapter
        self.service = adapter.service
        self._token = token

    def __repr__(self) -> str:  # never show the token
        return f"Connection({self.service})"

    def _send(self, method: str, url: str, headers: dict[str, str], data: bytes | None) -> tuple[int, dict, dict]:
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310 - fixed https base URLs
                raw = resp.read()
                return resp.status, dict(resp.headers), json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                body = {}
            return exc.code, dict(exc.headers or {}), body
        except (urllib.error.URLError, TimeoutError, OSError):
            return 0, {}, {}

    def request(self, method: str, path: str, json: dict | None = None,
                query: dict[str, Any] | None = None) -> dict:
        try:
            policy.require_outbound_allowed(f"{self.service} connection")
        except policy.LockdownError as exc:
            raise BlockedByPolicy(str(exc)) from None
        url = self.adapter.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {**self.adapter.headers(self._token), "Content-Type": "application/json; charset=utf-8"}
        data = None if json is None else _dumps(json)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.monotonic()
            status, resp_headers, body = self._send(method, url, headers, data)
            ms = (time.monotonic() - started) * 1000
            code = self.adapter.body_error(body) if 200 <= status < 300 else None
            if 200 <= status < 300 and not code:
                _log(self.service, method, path, status, ms, "ok")
                return body
            kind = _classify(status, code or str(body.get("code") or ""))
            _log(self.service, method, path, status, ms, kind)
            if kind not in ("rate", "transient") or attempt == MAX_ATTEMPTS:
                raise ConnectionFailed(kind, status or None, code or str(body.get("code") or ""))
            self.sleep(_retry_after(resp_headers, attempt))
        raise ConnectionFailed("transient")  # pragma: no cover


def _dumps(value: Any) -> bytes:
    return json.dumps(value).encode()


def _retry_after(headers: dict, attempt: int) -> float:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return min(float(value), 30.0)
            except ValueError:
                break
    return min(0.5 * 2 ** (attempt - 1), 8.0)


# ---- the module interface ---------------------------------------------------

_fakes: dict[str, Any] = {}


def use(service: str, fake: Any) -> None:
    """Tests: every get(service) returns `fake` (None restores the real one)."""
    if fake is None:
        _fakes.pop(service, None)
    else:
        _fakes[_service(service)] = fake


def _require_allowed(service: str) -> None:
    if policy.lockdown_enabled():
        raise BlockedByPolicy(f"{service} is disabled by enterprise lockdown.")


def get(service: str) -> Any:
    _service(service)
    _require_allowed(service)
    if service in _fakes:
        return _fakes[service]
    token = keychain.get(_account(service))
    if not token:
        raise NotConnected(service)
    return Connection(ADAPTERS[service], token)


def connected(service: str) -> bool:
    if service in _fakes:
        return True
    with db.get_db() as conn:
        _ensure(conn)
        return conn.execute("SELECT 1 FROM connections WHERE service = ?", (service,)).fetchone() is not None


def connect(service: str, token: str) -> dict[str, Any]:
    """Store the pasted token in the Keychain after checking it against the
    service (one whoami call, no meeting content). Returns status()."""
    _service(service)
    _require_allowed(service)
    token = (token or "").strip()
    if not token or len(token) > 512 or any(c.isspace() for c in token):
        raise ValueError("Paste the token as one line")
    conn = _fakes.get(service) or Connection(ADAPTERS[service], token)
    method, path = ADAPTERS[service].whoami
    body = conn.request(method, path)
    if not keychain.set(_account(service), token):
        raise ValueError("Could not save the token in the Keychain")
    with db.get_db() as c:
        _ensure(c)
        c.execute("INSERT INTO connections (service, account_label, connected_at, checked_at) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(service) DO UPDATE SET account_label = excluded.account_label, "
                  "checked_at = excluded.checked_at",
                  (service, ADAPTERS[service].label(body)[:200], _now(), _now()))
        c.commit()
    return status()[service]


def disconnect(service: str) -> None:
    _service(service)
    keychain.delete(_account(service))
    with db.get_db() as c:
        _ensure(c)
        c.execute("DELETE FROM connections WHERE service = ?", (service,))
        c.commit()


def status() -> dict[str, dict[str, Any]]:
    with db.get_db() as c:
        _ensure(c)
        rows = {r["service"]: dict(r) for r in c.execute("SELECT * FROM connections")}
    blocked = policy.lockdown_enabled()
    return {s: {"connected": s in rows or s in _fakes, "account_label": (rows.get(s) or {}).get("account_label") or "",
                "checked_at": (rows.get(s) or {}).get("checked_at"), "blocked_policy": blocked,
                "label": DISPLAY.get(s, (s.title(), ""))[0], "token_hint": DISPLAY.get(s, ("", ""))[1]} for s in SERVICES}
