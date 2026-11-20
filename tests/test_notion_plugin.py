"""Notion plugin (T7) through processing, the Outbox HTTP API and a
FakeConnection: Task cache, matcher, link/create Proposals and apply,
Accounts for the Assignee, no duplicates after reprocessing, and automatic
calls that carry no meeting content. Tasks here are fictional."""
import datetime as dt
import http.client
import json
import re
import threading
import uuid

import pytest

import accounts
import action_items
import db
import notes_context
import outbox
import paths
import post_processing
import server
from api import auth
from pipeline.processing_notes import generate_notes

TOKEN = "notion-plugin-test-token"
MAPPING = {"title": "Name", "status": "Status", "done_value": "Done", "assignee": "Assignee", "due": "Due",
           "area": "Area"}
NOW = dt.datetime.now(dt.timezone.utc)


def page(pid, title, status="In progress", created=None, assignee=None):
    return {"id": pid, "url": f"https://www.notion.so/{pid}", "created_time": created or "2026-10-01T09:00:00.000Z",
            "last_edited_time": "2026-11-01T09:00:00.000Z", "properties": {
                "Name": {"type": "title", "title": [{"plain_text": title}]},
                "Status": {"type": "status", "status": {"name": status}},
                "Assignee": {"type": "people", "people": [{"id": assignee}] if assignee else []},
                "Due": {"type": "date", "date": None},
                "Area": {"type": "select", "select": None}}}


TASKS = [
    page("t-pricing", "Ship pricing page v2"),
    page("t-onboard", "Onboarding email sequence for trial users"),
    page("t-hiring", "Hire a backend engineer"),
    page("t-offsite", "Plan the Q1 offsite agenda"),
    page("t-old", "Migrate billing to Stripe", status="Done"),
]


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
def notion(fake_conn, port):
    fake = fake_conn("notion")
    state = {"tasks": list(TASKS), "created": 0}
    fake.on("GET", "/users/me", {"bot": {"owner": {"user": {"id": "n-me"}}}})
    fake.on("GET", "/users", {"results": [{"id": "n-me", "type": "person", "name": "Mira Testwell"},
                                          {"id": "n-quill", "type": "person", "name": "Quill Arbuthnot"}]})
    fake.on("POST", "/databases/db1/query", lambda r: {"results": state["tasks"], "has_more": False})

    def create(r):
        state["created"] += 1
        return {"id": f"new-{state['created']}", "url": f"https://www.notion.so/new-{state['created']}",
                "created_time": NOW.isoformat()}
    fake.on("POST", "/pages", create)
    fake.on("POST", "/comments", {"id": "c1"})
    db.init_db()
    db.set_setting("plugin_settings.notion", {})
    with db.get_db() as conn:
        conn.execute("DELETE FROM notion_tasks") if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'notion_tasks'").fetchone() else None
        conn.commit()
    assert call(port, "POST", "/api/plugins/notion/settings", {"database_id": "db1", "database_title": "Team Tasks",
                                                              "mapping": MAPPING})[0] == 200
    accounts.refresh_users("notion", force=True)
    fake.requests.clear()
    fake.state = state
    yield fake
    db.set_setting("plugin_settings.notion", {})   # leave the bundled plugin unconfigured for other suites


ITEM = re.compile(r'<item id="([^"]+)">([^<]*)</item>')


def model(decide):
    """A FakeText reply that answers the matcher's JSON from (item text) -> dict."""
    def reply(prompt, **kwargs):
        if 'Answer with JSON only: [{"action_item_id"' not in prompt:
            return "- x"
        return json.dumps([{"action_item_id": i, **decide(text)} for i, text in ITEM.findall(prompt)])
    return reply


def recording(rec_id, items, title="Weekly product sync"):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), title, "2026-11-12T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": list(items),
                                                      "processing": {"provider": "local_mlx", "model": ""}})
    return folder


def process(rec_id):
    post_processing.finish(rec_id)
    return outbox.pending(rec_id)


def proposals(port, rec_id):
    return call(port, "GET", f"/api/outbox?recording={rec_id}")[1]["proposals"]


def test_link_proposal_writes_a_comment_only_on_confirm(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "link", "task_id": "t-pricing", "confidence": 0.92}
                            if "pricing" in t.lower() else {"decision": "skip", "confidence": 0.9})
    recording("n-link", ["Finish the pricing page v2 copy (Owner: Quill Arbuthnot)", "FYI the room moved"])
    process("n-link")
    ps = proposals(port, "n-link")
    assert [(p["kind"], p["target"]["id"]) for p in ps] == [("task.link", "t-pricing")]
    assert len(fake_text.calls) == 1                         # one model call per Recording
    assert all(r["method"] != "POST" or r["path"] != "/comments" for r in notion.requests)

    status, body = call(port, "POST", "/api/outbox/confirm", {"key": ps[0]["key"]})
    assert status == 200
    writes = [r for r in notion.requests if r["method"] in ("POST", "PATCH") and "/query" not in r["path"]]
    assert writes == [{"method": "POST", "path": "/comments", "query": None, "json": {
        "parent": {"page_id": "t-pricing"},
        "rich_text": [{"type": "text", "text": {
            "content": "From Weekly product sync, 2026-11-12: Finish the pricing page v2 copy"}}]}}]
    links = outbox.links(recording_id="n-link")
    assert [(lk["external_id"], lk["kind"]) for lk in links] == [("t-pricing", "task")]


def test_low_confidence_becomes_create_with_three_link_instead(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "link", "task_id": "t-onboard", "confidence": 0.4})
    recording("n-low", ["Draft onboarding emails for trial users"])
    p = process("n-low")[0]
    assert p["kind"] == "task.create"
    instead = next(f for f in p["fields"] if f["name"] == "link_instead")
    assert [o["value"] for o in instead["options"]][:2] == ["", "t-onboard"] and len(instead["options"]) <= 4
    call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"link_instead": "t-onboard"}})
    assert [r["path"] for r in notion.requests if r["method"] == "POST" and "/query" not in r["path"]] == ["/comments"]
    assert outbox.links(recording_id="n-low")[0]["external_id"] == "t-onboard"


def test_model_cannot_link_to_a_task_it_was_not_shown(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "link", "task_id": "t-hiring", "confidence": 0.99})
    recording("n-guard", ["Order new office chairs"])
    assert process("n-guard")[0]["kind"] == "task.create"


def test_create_assignee_only_from_a_confirmed_account(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    pid = f"p_{uuid.uuid4().hex[:6]}"
    now = NOW.isoformat()
    db.upsert_person(pid, "Quill Arbuthnot", "", "", [], False, None, now, now, 0)
    recording("n-assign", ["Book the venue (Owner: Quill Arbuthnot, Due: 2026-11-20)", "Order pizza (Owner: Zed Nobody)"])
    venue, pizza = process("n-assign")
    field = {f["name"]: f for f in venue["fields"]}
    assert field["assignee"]["value"] == "" and field["due"]["value"] == "2026-11-20"   # unconfirmed: empty
    accounts.confirm(pid, "notion", "n-quill")
    venue = next(p for p in process("n-assign") if p["key"] == venue["key"])            # refreshed in place
    assert {f["name"]: f for f in venue["fields"]}["assignee"]["value"] == "n-quill"
    call(port, "POST", "/api/outbox/confirm", {"key": venue["key"]})
    call(port, "POST", "/api/outbox/confirm", {"key": pizza["key"]})
    bodies = [r["json"] for r in notion.requests if r["path"] == "/pages" and r["method"] == "POST"]
    assert bodies[0]["properties"]["Assignee"] == {"people": [{"id": "n-quill"}]}
    assert bodies[0]["properties"]["Due"] == {"date": {"start": "2026-11-20"}}
    assert "Assignee" not in bodies[1]["properties"]                                     # left empty
    assert bodies[0]["parent"] == {"database_id": "db1"}


def test_reprocessing_proposes_nothing_twice_and_creates_no_duplicates(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    recording("n-dup", ["Write the launch blog post", "Record the demo video"])
    blog, video = process("n-dup")
    call(port, "POST", "/api/outbox/confirm", {"key": blog["key"]})
    call(port, "POST", "/api/outbox/dismiss", {"key": video["key"]})
    for _ in range(3):
        assert process("n-dup") == []
    assert notion.state["created"] == 1
    assert len([r for r in notion.requests if r["path"] == "/pages" and r["method"] == "POST"]) == 1


def test_same_title_created_in_the_last_day_is_flagged(port, notion, fake_text):
    notion.state["tasks"] = TASKS + [page("t-fresh", "Prepare investor update", created=NOW.isoformat())]
    from plugins.notion import tasks
    tasks.refresh(force=True)
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    recording("n-twin", ["Prepare investor update"])
    warning = {f["name"]: f for f in process("n-twin")[0]["fields"]}["warning"]
    assert "Prepare investor update" in warning["value"] and warning["editable"] is False


def test_usage_instructions_fold_sub_steps_into_one_task_checklist(port, notion, fake_text):
    call(port, "POST", "/api/plugins/notion/settings", {"usage_instructions": "Chunky tasks; fold sub-steps."})
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9, "group": "launch"}
                            if "launch" in t.lower() else {"decision": "create", "confidence": 0.9})
    recording("n-group", ["Prepare the launch checklist", "Book launch photographer", "Renew the domain"])
    ps = process("n-group")
    assert sorted(len(p["action_item_ids"]) for p in ps) == [1, 2]
    grouped = next(p for p in ps if len(p["action_item_ids"]) == 2)
    call(port, "POST", "/api/outbox/confirm", {"key": grouped["key"]})
    body = next(r["json"] for r in notion.requests if r["path"] == "/pages" and r["method"] == "POST")
    assert [b["to_do"]["rich_text"][0]["text"]["content"] for b in body["children"] if b["type"] == "to_do"] == \
        ["Book launch photographer"]
    assert len(outbox.links(recording_id="n-group")) == 2      # both Action items Linked
    assert "Chunky tasks" in fake_text.calls[0]["prompt"]


def test_automatic_calls_carry_no_meeting_content(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    recording("n-egress", ["Escalate the Xylophant contract"], title="Secret Xylophant review")
    process("n-egress")
    call(port, "POST", "/api/plugins/notion/refresh", {})
    accounts.refresh_users("notion", force=True)
    assert notion.requests and "Xylophant" not in notion.bodies()


def test_nothing_without_a_database_or_a_connection(port, notion, fake_text, keychain):
    import connections
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    db.set_setting("plugin_settings.notion", {})
    recording("n-unset", ["Write the plan"])
    assert process("n-unset") == []
    connections.use("notion", None)
    db.set_setting("plugin_settings.notion", {"database_id": "db1", "mapping": MAPPING})
    assert process("n-unset") == [] and fake_text.calls == []


def test_notion_tasks_reach_the_notes_prompt_as_context(port, notion, fake_text):
    from plugins.notion import tasks
    tasks.refresh(force=True)
    saved = db.get_setting(notes_context.SETTING)
    db.set_setting(notes_context.SETTING, True)
    try:
        folder = recording("n-context", [])
        fake_text.reply = "- x"
        fake_text.calls.clear()
        generate_notes("[00:00 - 00:05] Quill: I'll ship it.", [], [{"speaker_name": "Quill", "start": "00:00",
                                                                      "end": "00:05", "text": "I'll ship it."}],
                       options={"provider": "local_mlx", "model": "", "template": "general", "mode": "local_light"},
                       folder=folder)
        prompt = {c["trace"]: c["prompt"] for c in fake_text.calls}["enhanced_notes.action_items"]
        assert '<context source="notion.tasks">' in prompt and "- Ship pricing page v2" in prompt
        assert "Migrate billing to Stripe" not in prompt          # done Tasks are not offered
    finally:
        db.set_setting(notes_context.SETTING, saved)


def test_link_never_edits_title_or_body(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "link", "task_id": "t-hiring", "confidence": 0.95})
    recording("n-noedit", ["Hire a backend engineer by December"])
    p = process("n-noedit")[0]
    call(port, "POST", "/api/outbox/confirm", {"key": p["key"], "edits": {"comment": "From sync: hiring update"}})
    assert not [r for r in notion.requests if r["method"] == "PATCH"]
    assert [r["path"] for r in notion.requests if r["method"] == "POST" and "/query" not in r["path"]] == ["/comments"]
    assert action_items.for_recording("n-noedit")[0]["id"] in p["action_item_ids"]


# ---- T8: done both ways -------------------------------------------------------

def linked_item(port, notion, fake_text, rec_id, text, task_id):
    fake_text.reply = model(lambda t: {"decision": "link", "task_id": task_id, "confidence": 0.95})
    recording(rec_id, [text])
    p = process(rec_id)[0]
    assert call(port, "POST", "/api/outbox/confirm", {"key": p["key"]})[0] == 200
    return p["action_item_ids"][0]


def done_proposals(port, rec_id):
    return [p for p in proposals(port, rec_id) if p["kind"] == "task.update"]


def test_done_in_notion_marks_the_linked_todo_done_once(port, notion, fake_text):
    from plugins.notion import PLUGIN
    item = linked_item(port, notion, fake_text, "n-pull", "Plan the Q1 offsite agenda draft", "t-offsite")
    notion.state["tasks"] = [t if t["id"] != "t-offsite" else page("t-offsite", "Plan the Q1 offsite agenda",
                                                                     status="Done") for t in TASKS]
    PLUGIN.hooks["daily"]()
    assert action_items.get(item)["done"] is True
    assert done_proposals(port, "n-pull") == []          # already done there: nothing to suggest back
    call(port, "POST", f"/api/action-items/{item}", {"done": False})   # the user unticks it
    PLUGIN.hooks["daily"]()
    assert action_items.get(item)["done"] is False       # not re-ticked


def test_done_in_cora_raises_exactly_one_mark_done_proposal(port, notion, fake_text):
    item = linked_item(port, notion, fake_text, "n-push", "Hire a backend engineer soon", "t-hiring")
    notion.on("GET", "/pages/t-hiring", {"id": "t-hiring", "properties": {"Status": {"type": "status"}}})
    for done in (True, True):
        call(port, "POST", "/api/plugins/todo/done", {"id": item, "done": done})
    process("n-push")                                     # reprocessing keeps it, no duplicate
    ups = done_proposals(port, "n-push")
    assert len(ups) == 1 and ups[0]["title"] == "Mark done in Notion: 'Hire a backend engineer'"
    assert not [r for r in notion.requests if r["method"] == "PATCH"]   # nothing until Confirm

    call(port, "POST", "/api/outbox/confirm", {"key": ups[0]["key"]})
    patches = [r for r in notion.requests if r["method"] == "PATCH"]
    assert patches == [{"method": "PATCH", "path": "/pages/t-hiring", "query": None,
                        "json": {"properties": {"Status": {"status": {"name": "Done"}}}}}]
    call(port, "POST", "/api/action-items/" + item, {"done": False})
    call(port, "POST", "/api/action-items/" + item, {"done": True})
    assert done_proposals(port, "n-push") == []           # confirmed key never comes back


def test_unticking_before_confirm_withdraws_and_reticking_restores_one(port, notion, fake_text):
    item = linked_item(port, notion, fake_text, "n-flip", "Launch referral program pilot", "t-onboard")
    call(port, "POST", f"/api/action-items/{item}", {"done": True})
    call(port, "POST", f"/api/action-items/{item}", {"done": False})
    assert done_proposals(port, "n-flip") == []
    call(port, "POST", f"/api/action-items/{item}", {"done": True})
    assert len(done_proposals(port, "n-flip")) == 1


def test_an_unlinked_todo_done_raises_nothing(port, notion, fake_text):
    fake_text.reply = model(lambda t: {"decision": "create", "confidence": 0.9})
    recording("n-unlinked", ["Buy a new kettle"])
    process("n-unlinked")
    item = action_items.for_recording("n-unlinked")[0]["id"]
    call(port, "POST", f"/api/action-items/{item}", {"done": True})
    assert done_proposals(port, "n-unlinked") == []
