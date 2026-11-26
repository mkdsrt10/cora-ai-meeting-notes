"""Slack plugin (T9) over HTTP with a FakeConnection: selected Action items
become one message.post Proposal; Confirm posts it once as the user and
stores the permalink as a Link; reprocessing posts nothing; owners are
mentions only with a confirmed Account; the destination defaults to the last
one used for the folder; destination lists carry no meeting content."""
import datetime as dt
import http.client
import json
import threading
import uuid

import pytest

import accounts
import action_items
import db
import outbox
import paths
import post_processing
import server
from api import auth

TOKEN = "slack-plugin-test-token"


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


@pytest.fixture
def slack(fake_conn):
    fake = fake_conn("slack")
    fake.on("POST", "/auth.test", {"ok": True, "user_id": "U0ME"})
    fake.on("GET", "/users.list", {"ok": True, "members": [
        {"id": "U0ME", "profile": {"real_name": "Mira Testwell"}},
        {"id": "U0VEX", "profile": {"real_name": "Vexa Moranti"}},
        {"id": "U0ORB", "profile": {"real_name": "Orbin Kestrel"}}]})
    fake.on("GET", "/users.conversations", {"ok": True, "channels": [{"id": "C0GEN", "name": "general"},
                                                                    {"id": "C0PROD", "name": "product"}]})
    fake.on("POST", "/conversations.open", lambda r: {"ok": True, "channel": {"id": "D" + r["json"]["users"]}})
    fake.on("POST", "/chat.postMessage", lambda r: {"ok": True, "channel": r["json"]["channel"], "ts": "1700000000.0001"})
    fake.on("GET", "/chat.getPermalink", lambda r: {"ok": True, "permalink":
                                                    f"https://acme.slack.com/archives/{r['query']['channel']}/p1"})
    db.init_db()
    db.set_setting("plugin_settings.slack", {})
    accounts.refresh_users("slack", force=True)
    fake.requests.clear()
    yield fake
    db.set_setting("plugin_settings.slack", {})


def person(name, slack_id=None):
    pid = f"sl_{uuid.uuid4().hex[:8]}"
    now = dt.datetime.now().astimezone().isoformat()
    db.upsert_person(pid, name, "", "", [], False, None, now, now, 0)
    if slack_id:
        accounts.confirm(pid, "slack", slack_id)
    return pid


def recording(rec_id, items, folder=None, title="Design review"):
    paths.ensure_data_dir()
    db.init_db()
    path = paths.RECORDINGS_DIR / rec_id
    path.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(path), title, "2026-11-13T09:00:00+00:00", 60, 1,
                            {"folder_id": folder} if folder else {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": list(items)})
    action_items.sync(rec_id)
    return [i["id"] for i in action_items.for_recording(rec_id)]


def compose(port, ids):
    status, body = call(port, "POST", "/api/plugins/slack/compose", {"action_item_ids": ids})
    assert status == 200, body
    return body["proposal"]


def posts(fake):
    return [r for r in fake.requests if r["path"] == "/chat.postMessage"]


def test_selected_items_become_one_message_posted_once_as_the_user(port, slack):
    person("Vexa Moranti", "U0VEX")
    person("Orbin Kestrel")                                       # no confirmed Account
    ids = recording("sl-one", ["Ship the icons (Owner: Vexa Moranti, Due: Fri)",
                               "Review the palette (Owner: Orbin Kestrel)", "Book the room"])
    p = compose(port, ids[:2])
    assert p["kind"] == "message.post" and p["action_item_ids"] == ids[:2]
    text = {f["name"]: f for f in p["fields"]}["text"]["value"]
    assert text.splitlines() == ["*Action items from Design review* · 2026-11-13",
                                 "• Ship the icons (<@U0VEX>, due Fri)",
                                 "• Review the palette (Orbin Kestrel)",
                                 'View notes: in Cora, "Design review"']
    assert posts(slack) == []                                     # nothing until Confirm

    status, body = call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"destination": "channel:C0PROD",
                                                                                         "text": text + "\nThanks!"}})
    assert status == 200
    assert [r["json"] for r in posts(slack)] == [{"channel": "C0PROD", "text": text + "\nThanks!",
                                                  "unfurl_links": False, "unfurl_media": False}]
    links = outbox.links(recording_id="sl-one", service="slack")
    assert [(lk["action_item_id"], lk["url"]) for lk in links] == [(i, "https://acme.slack.com/archives/C0PROD/p1")
                                                                    for i in ids[:2]]
    assert call(port, "POST", "/api/outbox/confirm", {"key": p["key"]})[0] == 409     # posted once
    post_processing.finish("sl-one")                                                  # reprocess
    assert len(posts(slack)) == 1 and outbox.get(p["key"])["state"] == "confirmed"
    assert [x for x in outbox.pending("sl-one") if x["plugin_id"] == "slack"] == []


def test_destinations_are_my_channels_me_and_confirmed_people_only(port, slack):
    person("Vexa Moranti", "U0VEX")
    ids = recording("sl-dest", ["Write the Quorvex spec"], title="Quorvex planning")
    p = compose(port, ids)
    options = {f["name"]: f for f in p["fields"]}["destination"]["options"]
    labels = [o["label"] for o in options]
    assert labels[:3] == ["Direct message to yourself", "#general", "#product"]
    assert "Direct message to Vexa Moranti" in labels and not any("Orbin" in label for label in labels)
    listing = [r for r in slack.requests if r["path"] != "/chat.postMessage"]
    assert listing and "Quorvex" not in json.dumps(listing)        # names only out, nothing about the meeting
    assert call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"destination": "channel:C0SECRET"}}) == \
        (400, {"error": "not_an_option:destination"})
    assert posts(slack) == []


def test_dm_to_self_opens_the_conversation_then_posts(port, slack):
    ids = recording("sl-dm", ["Email the vendor"])
    p = compose(port, ids)
    call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"destination": "dm:U0ME"}})
    assert [r["path"] for r in slack.requests if r["method"] == "POST" and r["path"] != "/auth.test"] == \
        ["/conversations.open", "/chat.postMessage"]
    assert posts(slack)[0]["json"]["channel"] == "DU0ME"


def test_destination_defaults_to_the_last_one_used_for_the_folder(port, slack):
    first = recording("sl-f1", ["Draft the roadmap"], folder="fold-design")
    p = compose(port, first)
    call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"destination": "channel:C0PROD"}})
    second = recording("sl-f2", ["Share the roadmap"], folder="fold-design")
    assert {f["name"]: f for f in compose(port, second)["fields"]}["destination"]["value"] == "channel:C0PROD"
    other = recording("sl-f3", ["Something else"], folder="fold-other")
    assert {f["name"]: f for f in compose(port, other)["fields"]}["destination"]["value"] == "dm:U0ME"


def test_text_model_drafts_only_with_usage_instructions(port, slack, fake_text):
    ids = recording("sl-draft", ["Fix the header"])
    fake_text.reply = "Hey team! Fix the header."
    compose(port, ids)
    assert fake_text.calls == []                                   # template, no model
    call(port, "POST", "/api/plugins/slack/settings", {"usage_instructions": "Casual, one line per item."})
    p = compose(port, ids)
    assert {f["name"]: f for f in p["fields"]}["text"]["value"] == "Hey team! Fix the header."
    assert "Casual, one line per item." in fake_text.calls[0]["prompt"]


def test_send_again_makes_a_new_message_never_an_update(port, slack):
    ids = recording("sl-again", ["Send the deck"])
    for _ in range(2):
        p = compose(port, ids)
        call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"destination": "channel:C0GEN"}})
    assert len(posts(slack)) == 2
    assert not [r for r in slack.requests if r["path"] == "/chat.update"]


def test_compose_without_a_connection(port, keychain):
    ids = recording("sl-nc", ["Anything"])
    assert call(port, "POST", "/api/plugins/slack/compose", {"action_item_ids": ids}) == (409, {"error": "not_connected"})
