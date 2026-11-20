"""Outbox (ADR 0002): where Proposals wait for the user's Confirm or Dismiss,
and the only path from Cora to an external write.

Plugin-facing:
    Proposal(key, kind, title, fields, body_md, payload, action_item_ids, target)
    proposer.propose(ctx) -> [Proposal]          # automatic, after processing
    proposer.apply(proposal, edits, conn) -> Applied
    proposer.on_action_item(event, item, ctx) -> [Proposal]   # optional (done in Cora)

Host-facing:
    refresh(recording_id)           # call automatic proposers, upsert by key, retire stale
    submit(plugin_id, recording_id, proposals)   # user-started (Slack "Send")
    pending(recording_id=None)      # for the UI; expires 14-day-old ones first
    confirm(key, edits, click=...)  # the only path to an external write
    dismiss(key)

Behind it:
- Idempotency: a key is upserted. Reprocessing refreshes a pending Proposal
  but never re-proposes a confirmed or dismissed one. A pending Proposal its
  plugin no longer proposes is retired (kept, not deleted).
- Only a click applies: confirm() needs a UserClick, which only the HTTP
  route in api/routes/outbox.py makes. No Hook, schedule or rule reaches it.
- Lockdown refuses confirm (audit outcome "blocked").
- Audit: one row per confirm/dismiss/failure with the OS user, plugin, kind,
  target id, sha256 of the payload and outcome. Never content.
- Links: every Applied becomes a row in `links` for each Action item it covers.
- A disabled plugin's Proposals are hidden and cannot be confirmed; a raising
  proposer only costs itself.
"""
from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import action_items
import connections
import db
import plugin_host
import policy

KINDS = ("task.create", "task.link", "task.update", "message.post")
STATES = ("pending", "confirmed", "dismissed", "retired", "failed")
EXPIRE_DAYS = 14

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS outbox (
        key TEXT PRIMARY KEY,
        plugin_id TEXT NOT NULL,
        recording_id TEXT,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        fields_json TEXT NOT NULL DEFAULT '[]',
        body_md TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT '{}',
        action_item_ids_json TEXT NOT NULL DEFAULT '[]',
        target_json TEXT,
        state TEXT NOT NULL CHECK (state IN ('pending','confirmed','dismissed','retired','failed')),
        retired_reason TEXT,
        error TEXT,
        applied_ref_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS outbox_recording ON outbox (recording_id, state)",
    """CREATE TABLE IF NOT EXISTS links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recording_id TEXT,
        action_item_id TEXT,
        plugin_id TEXT NOT NULL,
        service TEXT NOT NULL,
        external_id TEXT NOT NULL,
        url TEXT,
        kind TEXT NOT NULL,
        proposal_key TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS links_item ON links (action_item_id)",
    """CREATE TABLE IF NOT EXISTS outbox_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        os_user TEXT NOT NULL,
        plugin_id TEXT NOT NULL,
        key_sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,
        target TEXT,
        payload_sha256 TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('confirmed','dismissed','failed','blocked'))
    )""",
)


class OutboxError(RuntimeError):
    """A confirm or dismiss the Outbox refuses; `code` is shown on the card."""

    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


# ---- plugin-facing types ----------------------------------------------------

@dataclass(frozen=True)
class Field:
    name: str
    label: str
    value: Any = ""
    editable: bool = True
    type: str = "text"            # text | textarea | select | readonly
    options: tuple[Any, ...] = ()  # for select: ({"value", "label"}, ...)


@dataclass(frozen=True)
class Proposal:
    key: str
    kind: str
    title: str
    fields: tuple[Field, ...] = ()
    body_md: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    action_item_ids: tuple[str, ...] = ()
    target: dict[str, Any] | None = None    # existing external object {id, title, url}
    sends: str = ""                          # the 🔒 line: exactly what will be sent, and where


@dataclass(frozen=True)
class Applied:
    service: str
    external_id: str
    url: str = ""
    kind: str = ""


@dataclass
class ProposeContext:
    """Read-only view a proposer gets. No Connection: propose never writes,
    and automatic network calls (caches) happen elsewhere without content."""
    plugin_id: str
    recording_id: str | None
    recording: dict[str, Any] | None
    action_items: list[dict[str, Any]]
    links: list[dict[str, Any]]

    def text_model(self):
        """The Recording's configured Text model (local included)."""
        from pipeline.text_model import text_model
        info = ((self.recording or {}).get("call_summary") or {}).get("processing") or {}
        return text_model({"provider": info.get("provider") or "local_mlx", "model": info.get("model") or ""})

    def settings(self) -> dict[str, Any]:
        return plugin_settings(self.plugin_id)


class UserClick:
    """Proof that a confirm comes from the user's click. Made only by the
    HTTP route (api/routes/outbox.py); a test asserts nothing else makes one."""
    __slots__ = ("source",)

    def __init__(self, source: str):
        self.source = source


# ---- storage ----------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _ensure(conn) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def plugin_settings(plugin_id: str) -> dict[str, Any]:
    value = db.get_setting(f"plugin_settings.{plugin_id}") or {}
    return value if isinstance(value, dict) else {}


def save_plugin_settings(plugin_id: str, values: dict[str, Any]) -> dict[str, Any]:
    merged = {**plugin_settings(plugin_id), **values}
    db.set_setting(f"plugin_settings.{plugin_id}", merged)
    return merged


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _row(row) -> dict[str, Any]:
    r = dict(row)
    payload = json.loads(r["payload_json"])
    sends = payload.pop("_sends", "")
    return {
        "key": r["key"], "plugin_id": r["plugin_id"], "recording_id": r["recording_id"], "kind": r["kind"],
        "title": r["title"], "fields": json.loads(r["fields_json"]), "body_md": r["body_md"],
        "payload": payload, "sends": sends, "action_item_ids": json.loads(r["action_item_ids_json"]),
        "target": json.loads(r["target_json"]) if r["target_json"] else None, "state": r["state"],
        "retired_reason": r["retired_reason"], "error": r["error"],
        "applied": json.loads(r["applied_ref_json"]) if r["applied_ref_json"] else None,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def get(key: str) -> dict[str, Any] | None:
    with db.get_db() as conn:
        _ensure(conn)
        row = conn.execute("SELECT * FROM outbox WHERE key = ?", (key,)).fetchone()
    return _row(row) if row else None


def _plugin(plugin_id: str):
    return next((p for p in plugin_host.enabled_plugins() if p.id == plugin_id), None)


def _upsert(conn, plugin_id: str, recording_id: str | None, p: Proposal, now: str) -> str:
    """Insert or refresh one Proposal; returns 'new' | 'refreshed' | 'kept'."""
    if p.kind not in KINDS:
        raise ValueError(f"unknown Proposal kind {p.kind!r}")
    existing = conn.execute("SELECT state, retired_reason, plugin_id FROM outbox WHERE key = ?", (p.key,)).fetchone()
    values = (p.kind, p.title, json.dumps([asdict(f) for f in p.fields]), p.body_md,
              json.dumps({**p.payload, "_sends": p.sends}), json.dumps(list(p.action_item_ids)),
              json.dumps(p.target) if p.target else None)
    if existing is None:
        conn.execute("INSERT INTO outbox (key, plugin_id, recording_id, kind, title, fields_json, body_md, payload_json, "
                     "action_item_ids_json, target_json, state, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                     (p.key, plugin_id, recording_id, *values, now, now))
        return "new"
    if existing["plugin_id"] != plugin_id:
        raise ValueError("Proposal key belongs to another plugin")
    state, reason = existing["state"], existing["retired_reason"]
    if state in ("confirmed", "dismissed") or (state == "retired" and reason == "expired"):
        return "kept"   # never re-propose a decided (or expired) key
    conn.execute("UPDATE outbox SET kind = ?, title = ?, fields_json = ?, body_md = ?, payload_json = ?, "
                 "action_item_ids_json = ?, target_json = ?, state = CASE WHEN state = 'failed' THEN 'failed' "
                 "ELSE 'pending' END, retired_reason = NULL, updated_at = ? WHERE key = ?", (*values, now, p.key))
    return "refreshed"


def _context(plugin_id: str, recording_id: str | None) -> ProposeContext:
    recording = db.get_recording(recording_id) if recording_id else None
    items = action_items.for_recording(recording_id) if recording_id else []
    return ProposeContext(plugin_id, recording_id, recording, items, links(recording_id=recording_id)
                          if recording_id else [])


def refresh(recording_id: str) -> dict[str, int]:
    """Run every enabled plugin's automatic proposer for one Recording.
    Returns {plugin_id: proposals made} (-1 when the proposer raised)."""
    result: dict[str, int] = {}
    for plugin in plugin_host.enabled_plugins():
        proposer = plugin.proposer
        if proposer is None or not getattr(proposer, "automatic", True) or not hasattr(proposer, "propose"):
            continue
        if plugin.connection and not connections.connected(plugin.connection):
            continue   # only when connected (Q56)
        try:
            proposals = list(proposer.propose(_context(plugin.id, recording_id)) or [])
        except Exception as exc:  # one plugin failing never stops the rest
            plugin_host._log(plugin.id, "propose", exc)
            result[plugin.id] = -1
            continue
        _store(plugin.id, recording_id, proposals, retire_missing=True)
        result[plugin.id] = len(proposals)
    return result


def submit(plugin_id: str, recording_id: str | None, proposals: list[Proposal]) -> list[dict[str, Any]]:
    """Store user-started Proposals (e.g. Slack 'Send'); nothing is applied."""
    if _plugin(plugin_id) is None:
        raise OutboxError("plugin_disabled", 404)
    _store(plugin_id, recording_id, proposals, retire_missing=False)
    return [get(p.key) for p in proposals]  # type: ignore[misc]


def _store(plugin_id: str, recording_id: str | None, proposals: list[Proposal], *, retire_missing: bool) -> None:
    now = _now().isoformat()
    with db.get_db() as conn:
        _ensure(conn)
        seen = set()
        for p in proposals:
            _upsert(conn, plugin_id, recording_id, p, now)
            seen.add(p.key)
        if retire_missing:   # only automatic kinds; user-started ones (send, mark done) stay
            stale = [r["key"] for r in conn.execute(
                "SELECT key FROM outbox WHERE plugin_id = ? AND recording_id IS ? AND state = 'pending' "
                "AND kind NOT IN ('message.post', 'task.update')", (plugin_id, recording_id)) if r["key"] not in seen]
            conn.executemany("UPDATE outbox SET state = 'retired', retired_reason = 'invalid', updated_at = ? "
                             "WHERE key = ?", [(now, k) for k in stale])
        conn.commit()


def on_action_item_change(event: str, item_id: str) -> None:
    """Listener on core Action items: lets a plugin propose in response to a
    user change (e.g. done in Cora -> 'Mark done in Notion')."""
    item = action_items.get(item_id)
    if item is None:
        return
    for plugin in plugin_host.enabled_plugins():
        hook = getattr(plugin.proposer, "on_action_item", None)
        if hook is None:
            continue
        try:
            proposals = list(hook(event, item, _context(plugin.id, item["recording_id"])) or [])
        except Exception as exc:
            plugin_host._log(plugin.id, "on_action_item", exc)
            continue
        if proposals:
            _store(plugin.id, item["recording_id"], proposals, retire_missing=False)


action_items.on_change(on_action_item_change)


def withdraw(key: str) -> bool:
    """A plugin withdraws its own pending Proposal (e.g. the To-do was unticked
    before 'Mark done in Notion' was confirmed). Kept as retired, not deleted."""
    with db.get_db() as conn:
        _ensure(conn)
        cur = conn.execute("UPDATE outbox SET state = 'retired', retired_reason = 'invalid', updated_at = ? "
                           "WHERE key = ? AND state IN ('pending', 'failed')", (_now().isoformat(), key))
        conn.commit()
    return cur.rowcount > 0


def expire() -> int:
    cutoff = (_now() - dt.timedelta(days=EXPIRE_DAYS)).isoformat()
    with db.get_db() as conn:
        _ensure(conn)
        cur = conn.execute("UPDATE outbox SET state = 'retired', retired_reason = 'expired', updated_at = ? "
                           "WHERE state IN ('pending', 'failed') AND created_at < ?", (_now().isoformat(), cutoff))
        conn.commit()
    return cur.rowcount


def pending(recording_id: str | None = None) -> list[dict[str, Any]]:
    """Pending (and retryable failed) Proposals of enabled plugins, oldest first."""
    expire()
    enabled = {p.id for p in plugin_host.enabled_plugins()}
    sql = "SELECT * FROM outbox WHERE state IN ('pending', 'failed')"
    args: tuple = ()
    if recording_id is not None:
        sql, args = sql + " AND recording_id = ?", (recording_id,)
    with db.get_db() as conn:
        _ensure(conn)
        rows = [_row(r) for r in conn.execute(sql + " ORDER BY created_at, key", args)]
    return [r for r in rows if r["plugin_id"] in enabled]


def for_recording(recording_id: str) -> list[dict[str, Any]]:
    """Every Proposal of a Recording, any state (for chips), enabled plugins only."""
    expire()
    enabled = {p.id for p in plugin_host.enabled_plugins()}
    with db.get_db() as conn:
        _ensure(conn)
        rows = [_row(r) for r in conn.execute(
            "SELECT * FROM outbox WHERE recording_id = ? ORDER BY created_at, key", (recording_id,))]
    return [r for r in rows if r["plugin_id"] in enabled]


def _audit(conn, plugin_id: str, key: str, kind: str, target: str | None, payload: Any, outcome: str) -> None:
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    conn.execute("INSERT INTO outbox_audit (at, os_user, plugin_id, key_sha256, kind, target, payload_sha256, outcome) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (_now().isoformat(), user, plugin_id, hashlib.sha256(key.encode()).hexdigest(), kind, target,
                  sha256(payload), outcome))


def audit_rows() -> list[dict[str, Any]]:
    with db.get_db() as conn:
        _ensure(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM outbox_audit ORDER BY id")]


def _edited(row: dict[str, Any], edits: dict[str, Any]) -> dict[str, Any]:
    """The values to apply: each editable field as shown, replaced by the user's edits."""
    editable = {f["name"]: f for f in row["fields"] if f.get("editable")}
    clean: dict[str, Any] = {name: f.get("value") for name, f in editable.items()}
    for name, value in (edits or {}).items():
        if name not in editable:
            raise OutboxError(f"field_not_editable:{name}", 400)
        if isinstance(value, str) and len(value) > 8000:
            raise OutboxError(f"field_too_long:{name}", 400)
        clean[name] = value
    return clean


def _target_id(row: dict[str, Any]) -> str | None:
    return str((row.get("target") or {}).get("id") or "") or None


def confirm(key: str, edits: dict[str, Any] | None, *, click: UserClick) -> dict[str, Any]:
    """Apply one Proposal through its plugin's Connection. Needs the user's click."""
    if not isinstance(click, UserClick):
        raise OutboxError("needs_user_click", 403)
    row = get(key)
    if row is None:
        raise OutboxError("unknown_proposal", 404)
    plugin = _plugin(row["plugin_id"])
    if plugin is None or plugin.proposer is None:
        raise OutboxError("plugin_disabled", 404)
    if row["state"] not in ("pending", "failed"):
        raise OutboxError(f"already_{row['state']}")
    clean = _edited(row, edits or {})
    payload = row["payload"]
    audited = {"payload": payload, "edits": clean}
    now = _now().isoformat()
    if policy.lockdown_enabled():
        with db.get_db() as conn:
            _ensure(conn)
            _audit(conn, plugin.id, key, row["kind"], _target_id(row), audited, "blocked")
            conn.execute("UPDATE outbox SET error = 'blocked_policy', updated_at = ? WHERE key = ?", (now, key))
            conn.commit()
        raise OutboxError("blocked_policy", 403)
    try:
        conn_ = connections.get(plugin.connection) if plugin.connection else None
    except connections.NotConnected:
        raise OutboxError("not_connected") from None
    except connections.BlockedByPolicy:
        raise OutboxError("blocked_policy", 403) from None
    proposal = Proposal(key=row["key"], kind=row["kind"], title=row["title"],
                        fields=tuple(Field(**f) for f in row["fields"]), body_md=row["body_md"], payload=payload,
                        action_item_ids=tuple(row["action_item_ids"]), target=row["target"])
    try:
        applied = plugin.proposer.apply(proposal, clean, conn_)
    except Exception as exc:
        code = f"{exc.kind}" if isinstance(exc, connections.ConnectionFailed) else type(exc).__name__
        plugin_host._log(plugin.id, "apply", exc)
        with db.get_db() as conn:
            _ensure(conn)
            _audit(conn, plugin.id, key, row["kind"], _target_id(row), audited, "failed")
            conn.execute("UPDATE outbox SET state = 'failed', error = ?, updated_at = ? WHERE key = ?",
                         (code, now, key))
            conn.commit()
        raise OutboxError(f"failed:{code}", 502) from None
    if not isinstance(applied, Applied):
        raise OutboxError("bad_apply_result", 500)
    with db.get_db() as conn:
        _ensure(conn)
        for item_id in row["action_item_ids"] or [None]:
            conn.execute("INSERT INTO links (recording_id, action_item_id, plugin_id, service, external_id, url, kind, "
                         "proposal_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row["recording_id"], item_id, plugin.id, applied.service, applied.external_id, applied.url,
                          applied.kind or row["kind"], key, now))
        _audit(conn, plugin.id, key, row["kind"], applied.external_id, audited, "confirmed")
        conn.execute("UPDATE outbox SET state = 'confirmed', error = NULL, applied_ref_json = ?, updated_at = ? "
                     "WHERE key = ?", (json.dumps(asdict(applied)), now, key))
        conn.commit()
    return get(key)  # type: ignore[return-value]


def dismiss(key: str) -> dict[str, Any]:
    row = get(key)
    if row is None or _plugin(row["plugin_id"]) is None:
        raise OutboxError("unknown_proposal", 404)
    if row["state"] not in ("pending", "failed"):
        raise OutboxError(f"already_{row['state']}")
    with db.get_db() as conn:
        _ensure(conn)
        _audit(conn, row["plugin_id"], key, row["kind"], _target_id(row), {"payload": row["payload"]}, "dismissed")
        conn.execute("UPDATE outbox SET state = 'dismissed', updated_at = ? WHERE key = ?", (_now().isoformat(), key))
        conn.commit()
    return get(key)  # type: ignore[return-value]


def links(*, recording_id: str | None = None, action_item_id: str | None = None,
          service: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM links WHERE 1 = 1", []
    for column, value in (("recording_id", recording_id), ("action_item_id", action_item_id), ("service", service)):
        if value is not None:
            sql += f" AND {column} = ?"
            args.append(value)
    with db.get_db() as conn:
        _ensure(conn)
        return [dict(r) for r in conn.execute(sql + " ORDER BY id", args)]


def count() -> int:
    return len(pending())
