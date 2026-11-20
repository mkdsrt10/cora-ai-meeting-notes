"""Accounts (GLOSSARY, Q55): who a Person is in one Connection (their Notion
user, their Slack user). Suggested by name from the Connection's user list,
confirmed once by the user ("Confirm" / "Not them"), then reused for the
Notion Assignee and Slack mentions. No confirmed Account means: Assignee
left empty, plain name in Slack.

The user list is fetched with an automatic call that carries no meeting
content, and only ids and names are kept on the Mac (no emails, no avatars).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any

import connections
import db

STALE_AFTER = dt.timedelta(hours=24)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS service_users (
        service TEXT NOT NULL,
        external_id TEXT NOT NULL,
        name TEXT NOT NULL,
        is_self INTEGER NOT NULL DEFAULT 0,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY (service, external_id)
    )""",
    """CREATE TABLE IF NOT EXISTS person_accounts (
        person_id TEXT NOT NULL,
        service TEXT NOT NULL,
        external_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('confirmed', 'rejected')),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (person_id, service, external_id)
    )""",
)


def _now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _ensure(conn) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


# ---- the Connection's user list (names only) --------------------------------

def _fetch(service: str) -> list[tuple[str, str, bool]]:
    conn = connections.get(service)
    users: list[tuple[str, str, bool]] = []
    if service == "notion":
        me = conn.request("GET", "/users/me")
        owner = ((me.get("bot") or {}).get("owner") or {}).get("user") or {}
        cursor = None
        for _ in range(20):
            body = conn.request("GET", "/users", query={"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
            for u in body.get("results") or []:
                if u.get("type") == "person" and u.get("id") and u.get("name"):
                    users.append((str(u["id"]), str(u["name"]), u.get("id") == owner.get("id")))
            cursor = body.get("next_cursor")
            if not body.get("has_more") or not cursor:
                break
    else:
        me = conn.request("POST", "/auth.test")
        cursor = ""
        for _ in range(20):
            body = conn.request("GET", "/users.list", query={"limit": 200, **({"cursor": cursor} if cursor else {})})
            for u in body.get("members") or []:
                if u.get("deleted") or u.get("is_bot") or u.get("id") == "USLACKBOT":
                    continue
                name = (u.get("profile") or {}).get("real_name") or u.get("real_name") or u.get("name")
                if u.get("id") and name:
                    users.append((str(u["id"]), str(name), u.get("id") == me.get("user_id")))
            cursor = ((body.get("response_metadata") or {}).get("next_cursor") or "")
            if not cursor:
                break
    return users


def refresh_users(service: str, *, force: bool = False) -> bool:
    """Refresh the cached user list when older than a day (or forced).
    Returns True when it fetched. Never raises for a network failure."""
    if not connections.connected(service):
        return False
    with db.get_db() as c:
        _ensure(c)
        row = c.execute("SELECT MAX(fetched_at) AS at FROM service_users WHERE service = ?", (service,)).fetchone()
    if not force and row and row["at"] and _now() - dt.datetime.fromisoformat(row["at"]) < STALE_AFTER:
        return False
    try:
        users = _fetch(service)
    except (connections.ConnectionFailed, connections.NotConnected, connections.BlockedByPolicy):
        return False
    now = _now().isoformat()
    with db.get_db() as c:
        _ensure(c)
        c.execute("DELETE FROM service_users WHERE service = ?", (service,))
        c.executemany("INSERT OR REPLACE INTO service_users (service, external_id, name, is_self, fetched_at) "
                      "VALUES (?, ?, ?, ?, ?)", [(service, uid, name[:200], int(me), now) for uid, name, me in users])
        c.commit()
    return True


def users(service: str) -> list[dict[str, Any]]:
    with db.get_db() as c:
        _ensure(c)
        return [{"id": r["external_id"], "name": r["name"], "is_self": bool(r["is_self"])}
                for r in c.execute("SELECT * FROM service_users WHERE service = ? ORDER BY name", (service,))]


def user(service: str, external_id: str) -> dict[str, Any] | None:
    return next((u for u in users(service) if u["id"] == external_id), None)


def self_user(service: str) -> dict[str, Any] | None:
    return next((u for u in users(service) if u["is_self"]), None)


# ---- a Person's Account ------------------------------------------------------

def _states(person_id: str, service: str) -> dict[str, str]:
    with db.get_db() as c:
        _ensure(c)
        return {r["external_id"]: r["state"] for r in c.execute(
            "SELECT external_id, state FROM person_accounts WHERE person_id = ? AND service = ?", (person_id, service))}


def confirmed(person_id: str, service: str) -> dict[str, Any] | None:
    for external_id, state in _states(person_id, service).items():
        if state == "confirmed":
            return user(service, external_id) or {"id": external_id, "name": "", "is_self": False}
    return None


def suggest(person_id: str, service: str) -> dict[str, Any] | None:
    """The user-list entry whose name matches the Person's, unless rejected.
    Full name first; then a unique first-name-and-last-initial match."""
    person = db.get_person(person_id)
    if not person:
        return None
    rejected = {k for k, s in _states(person_id, service).items() if s == "rejected"}
    want = norm(person["name"])
    if not want:
        return None
    candidates = [u for u in users(service) if u["id"] not in rejected]
    exact = [u for u in candidates if norm(u["name"]) == want]
    if len(exact) == 1:
        return exact[0]
    parts = want.split()
    if len(parts) >= 2:
        loose = [u for u in candidates if norm(u["name"]).split()[:1] == parts[:1]
                 and norm(u["name"]).split()[-1:][0][:1] == parts[-1][:1]]
        if len(loose) == 1:
            return loose[0]
    return None


def account_state(person_id: str, service: str) -> dict[str, Any]:
    account = confirmed(person_id, service)
    if account:
        return {"state": "confirmed", "account": account}
    guess = suggest(person_id, service)
    return {"state": "suggested", "account": guess} if guess else {"state": "none", "account": None}


def _set(person_id: str, service: str, external_id: str, state: str) -> None:
    if db.get_person(person_id) is None:
        raise FileNotFoundError(person_id)
    if user(service, external_id) is None:
        raise ValueError("Unknown account")
    with db.get_db() as c:
        _ensure(c)
        if state == "confirmed":   # one confirmed Account per Person and service
            c.execute("DELETE FROM person_accounts WHERE person_id = ? AND service = ? AND state = 'confirmed'",
                      (person_id, service))
        c.execute("INSERT INTO person_accounts (person_id, service, external_id, state, updated_at) VALUES (?, ?, ?, ?, ?) "
                  "ON CONFLICT(person_id, service, external_id) DO UPDATE SET state = excluded.state, "
                  "updated_at = excluded.updated_at", (person_id, service, external_id, state, _now().isoformat()))
        c.commit()


def confirm(person_id: str, service: str, external_id: str) -> None:
    _set(person_id, service, external_id, "confirmed")


def reject(person_id: str, service: str, external_id: str) -> None:
    _set(person_id, service, external_id, "rejected")


def person_for_name(name: str | None) -> dict[str, Any] | None:
    """The Person an Action item owner names: exact name, else a unique first-name match."""
    want = norm(name or "")
    if not want:
        return None
    people = db.get_all_people()
    exact = [p for p in people if norm(p["name"]) == want]
    if len(exact) == 1:
        return exact[0]
    if " " not in want:
        first = [p for p in people if norm(p["name"]).split()[:1] == [want]]
        if len(first) == 1:
            return first[0]
    return None


def for_owner(owner: str | None, service: str) -> dict[str, Any] | None:
    """The confirmed Account for an Action item's owner, or None (leave the
    Assignee empty / write the plain name)."""
    person = person_for_name(owner)
    return confirmed(person["id"], service) if person else None
