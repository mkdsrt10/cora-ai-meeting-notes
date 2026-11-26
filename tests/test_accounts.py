"""Accounts on the Person page (T6, Q55) over HTTP with FakeConnections:
suggested by name from the Connection's user list (names only), Confirm /
Not them, reused; an unconfirmed owner has no Account."""
import datetime as dt
import http.client
import json
import threading
import uuid

import pytest

import accounts
import db
import server
from api import auth

TOKEN = "accounts-test-token"


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, (json.loads(data) if data else {})


def person(name):
    db.init_db()
    pid = f"acc_{uuid.uuid4().hex[:8]}"
    now = dt.datetime.now().astimezone().isoformat()
    db.upsert_person(pid, name, "", "", [], False, None, now, now, 0)
    return pid


@pytest.fixture
def services(fake_conn):
    notion = fake_conn("notion")
    notion.on("GET", "/users/me", {"bot": {"owner": {"user": {"id": "n-me"}}}})
    notion.on("GET", "/users", {"results": [
        {"id": "n-me", "type": "person", "name": "Mayank Tester"},
        {"id": "n-odalys", "type": "person", "name": "Odalys Brennt"},
        {"id": "n-odalys2", "type": "person", "name": "Odalys Bramwell"},
        {"id": "n-bot", "type": "bot", "name": "Odalys Brennt"}], "has_more": False})
    slack = fake_conn("slack")
    slack.on("POST", "/auth.test", {"ok": True, "user_id": "U0ME"})
    slack.on("GET", "/users.list", {"ok": True, "members": [
        {"id": "U0ME", "name": "me", "profile": {"real_name": "Mayank Tester"}},
        {"id": "U0ODALYS", "name": "odalys", "profile": {"real_name": "Odalys Brennt"}},
        {"id": "U0GONE", "name": "gone", "deleted": True, "profile": {"real_name": "Teodor Lee"}}],
        "response_metadata": {"next_cursor": ""}})
    with db.get_db() as conn:
        accounts._ensure(conn)
        conn.execute("DELETE FROM service_users")
        conn.commit()
    return notion, slack


def test_suggests_by_name_then_confirm_is_reused(port, services):
    notion, slack = services
    pid = person("Odalys Brennt")
    status, body = call(port, "GET", f"/api/person/accounts?id={pid}")
    assert status == 200
    assert body["accounts"]["notion"] == {"state": "suggested", "account": {"id": "n-odalys", "name": "Odalys Brennt", "is_self": False}}
    assert body["accounts"]["slack"]["account"]["id"] == "U0ODALYS"
    # the user list is a listing call: no body, nothing about meetings
    assert all(r["json"] is None for r in notion.requests + slack.requests)

    assert call(port, "POST", "/api/person/accounts/confirm",
                {"person_id": pid, "service": "notion", "external_id": "n-odalys"})[0] == 200
    before = len(notion.requests)
    body = call(port, "GET", f"/api/person/accounts?id={pid}")[1]
    assert body["accounts"]["notion"]["state"] == "confirmed"
    assert len(notion.requests) == before          # cached list, no refetch within a day
    assert accounts.for_owner("Odalys Brennt", "notion")["id"] == "n-odalys"
    assert accounts.for_owner("Odalys", "notion")["id"] == "n-odalys"   # unique first name
    assert accounts.for_owner("Odalys Brennt", "slack") is None          # only confirmed per service


def test_not_them_drops_the_suggestion(port, services):
    pid = person("Teodor Vask")
    accounts.refresh_users("slack", force=True)
    with db.get_db() as conn:
        conn.execute("INSERT INTO service_users (service, external_id, name, is_self, fetched_at) VALUES "
                     "('slack', 'U0TEODOR', 'Teodor Vask', 0, ?)", (dt.datetime.now().astimezone().isoformat(),))
        conn.commit()
    assert accounts.suggest(pid, "slack")["id"] == "U0TEODOR"
    assert call(port, "POST", "/api/person/accounts/reject",
                {"person_id": pid, "service": "slack", "external_id": "U0TEODOR"})[1]["account"] == {"state": "none", "account": None}
    assert accounts.for_owner("Teodor Vask", "slack") is None


def test_ambiguous_or_unknown_names_are_not_guessed(port, services):
    accounts.refresh_users("notion", force=True)
    assert accounts.suggest(person("Odalys B"), "notion") is None      # Brennt or Bramwell: no guess
    assert accounts.suggest(person("Nobody Known"), "notion") is None
    assert accounts.for_owner("Unknown Owner", "notion") is None
    assert accounts.for_owner(None, "notion") is None


def test_confirm_refuses_an_account_not_in_the_list(port, services):
    pid = person("Odalys Brennt")
    accounts.refresh_users("notion", force=True)
    assert call(port, "POST", "/api/person/accounts/confirm",
                {"person_id": pid, "service": "notion", "external_id": "n-made-up"})[0] == 400


def test_not_connected_service_has_no_row(port, keychain):
    pid = person("Odalys Brennt")
    assert call(port, "GET", f"/api/person/accounts?id={pid}")[1] == {"accounts": {}}


def test_a_personal_token_is_you_even_without_the_user_list(services):
    """A personal Notion token's /users/me is the person; when /users is not
    allowed (no "read user information"), you are still known."""
    import connections
    notion, _ = services
    notion.on("GET", "/users/me", {"object": "user", "type": "person", "id": "n-me", "name": "Mayank Tester"})
    notion.fail[("GET", "/users")] = connections.ConnectionFailed("forbidden", status=403)
    assert accounts.refresh_users("notion", force=True)
    assert accounts.self_user("notion") == {"id": "n-me", "name": "Mayank Tester", "is_self": True}


def test_assignee_for_owner_you_confirmed_or_unique_full_name(services):
    accounts.refresh_users("notion", force=True)
    assert accounts.assignee_for_owner("You", "notion") == (accounts.user("notion", "n-me"), "self")
    assert accounts.assignee_for_owner("Odalys Brennt", "notion")[1] == "name"
    assert accounts.assignee_for_owner("Odalys", "notion") == (None, "")        # first name alone: two people
    assert accounts.assignee_for_owner("Zed Nobody", "notion") == (None, "")


def test_an_integration_token_without_user_info_is_still_you_via_its_owner(services):
    """A token whose /users/me is a bot owned by you, with /users refused (403)."""
    import connections
    notion, _ = services
    notion.on("GET", "/users/me", {"object": "user", "type": "bot", "id": "bot-1", "name": "Cora",
                                   "bot": {"owner": {"type": "user", "user": {"object": "user", "type": "person",
                                                                              "id": "n-me", "name": "Mayank Tester"}}}})
    notion.fail[("GET", "/users")] = connections.ConnectionFailed("auth", status=403, code="restricted_resource")
    assert accounts.refresh_users("notion", force=True)
    assert accounts.self_user("notion") == {"id": "n-me", "name": "Mayank Tester", "is_self": True}


def test_people_seen_on_tasks_become_choices_and_survive_a_refresh(services):
    import connections
    notion, _ = services
    assert accounts.remember_users("notion", [("n-odalys", "Odalys Brennt"), ("n-teo", "Teodor Lee"), ("", "x")]) == 2
    names = {u["name"] for u in accounts.users("notion")}
    assert names == {"Odalys Brennt", "Teodor Lee"}
    notion.on("GET", "/users/me", {"type": "bot", "bot": {"owner": {"user": {"id": "n-me", "name": "Mayank Tester"}}}})
    notion.fail[("GET", "/users")] = connections.ConnectionFailed("auth", status=403, code="restricted_resource")
    assert accounts.refresh_users("notion", force=False)          # seen-only rows do not count as fetched
    by_id = {u["id"]: u for u in accounts.users("notion")}
    assert by_id["n-me"]["is_self"] and {"n-odalys", "n-teo"} <= set(by_id)
    assert accounts.remember_users("notion", [("n-me", "Someone Else")]) == 0
    assert accounts.user("notion", "n-me")["name"] == "Mayank Tester"   # never overrides you


def test_the_accounts_row_offers_every_known_account_to_link_by_hand(services):
    from surfaces import account_row
    nick = f"Odalys {uuid.uuid4().hex[:5]}"
    pid = person(nick)                            # matches nobody by name
    accounts.refresh_users("notion", force=True)
    row = account_row(pid, "notion", "Notion")
    labels = [c["label"] for c in row.panel["choices"]]
    assert labels == sorted(labels, key=str.lower) and "Mayank Tester (you)" in labels and "Odalys Bramwell" in labels
    accounts.confirm(pid, "notion", "n-odalys2")  # what the Link button runs (account_confirm)
    assert accounts.assignee_for_owner(nick, "notion") == (accounts.user("notion", "n-odalys2"), "confirmed")
