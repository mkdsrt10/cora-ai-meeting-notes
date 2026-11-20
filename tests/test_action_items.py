"""Core Action items (ADR 0004): records with identity, owner, due, done and
provenance, kept across reprocessing. Driven through the HTTP API and the
after_meeting path, the way the app and the To-dos View reach them."""
import http.client
import json
import threading

import pytest

import action_items
import db
import paths
import plugin_host
import post_processing
import server
from api import auth

TOKEN = "action-items-test-token"


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


def call(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, (json.loads(data) if data else {})


def recording(rec_id, items):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), f"Title {rec_id}", "2026-11-01T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": items})


def process(rec_id, items):
    """Save new notes for the Recording and run what follows processing."""
    recording(rec_id, items)
    post_processing.finish(rec_id)


def listed(port, rec_id):
    status, body = call(port, "GET", f"/api/action-items?recording={rec_id}")
    assert status == 200
    return body["items"]


def by_text(items):
    return {i["text"]: i for i in items}


def test_processing_stores_records_with_owner_and_due(port):
    process("ai-shape", ["Send the deck (Owner: Priya, Due: Friday)",
                         {"action": "Book the room", "owner_speaker_id": "Alex", "due_date": ""},
                         "Draft the budget"])
    items = by_text(listed(port, "ai-shape"))
    assert set(items) == {"Send the deck", "Book the room", "Draft the budget"}
    assert (items["Send the deck"]["owner"], items["Send the deck"]["due"]) == ("Priya", "Friday")
    assert items["Book the room"]["owner"] == "Alex" and items["Book the room"]["due"] is None
    assert items["Draft the budget"]["owner"] is None
    assert {i["provenance"] for i in items.values()} == {"ai"}
    assert not any(i["done"] for i in items.values())


def test_ids_and_done_marks_survive_reprocessing(port):
    process("ai-reprocess", ["Send the deck", "Book the room"])
    before = by_text(listed(port, "ai-reprocess"))
    assert call(port, "POST", f"/api/action-items/{before['Book the room']['id']}", {"done": True})[0] == 200
    process("ai-reprocess", ["Book the room (Owner: Sam)", "Send the deck"])
    after = by_text(listed(port, "ai-reprocess"))
    assert after["Book the room"]["id"] == before["Book the room"]["id"] and after["Book the room"]["done"]
    assert after["Book the room"]["owner"] == "Sam"  # AI record refreshed by the AI


def test_reworded_item_keeps_its_id(port):
    process("ai-reword", ["Send the pricing deck to the Acme team"])
    old = listed(port, "ai-reword")[0]
    call(port, "POST", f"/api/action-items/{old['id']}", {"done": True})
    process("ai-reword", ["Send the pricing deck to the Acme team today"])
    new = listed(port, "ai-reword")
    assert [(i["id"], i["text"], i["done"]) for i in new] == [
        (old["id"], "Send the pricing deck to the Acme team today", True)]


def test_unrelated_new_item_gets_a_new_id_and_the_old_one_is_superseded(port):
    process("ai-replace", ["Send the deck"])
    old = listed(port, "ai-replace")[0]
    process("ai-replace", ["Draft the budget"])
    new = listed(port, "ai-replace")
    assert [i["text"] for i in new] == ["Draft the budget"] and new[0]["id"] != old["id"]


def test_user_edit_wins_over_reprocessing(port):
    process("ai-edit", ["Send the deck", "Book the room"])
    item = by_text(listed(port, "ai-edit"))["Send the deck"]
    status, body = call(port, "POST", f"/api/action-items/{item['id']}",
                        {"text": "Send the v2 deck to Acme", "owner": "Priya", "due": "Nov 30"})
    assert status == 200 and body["item"]["provenance"] == "user"
    # Reprocessing returns the original wording, and later drops it entirely.
    process("ai-edit", ["Send the deck (Owner: Sam)", "Book the room"])
    process("ai-edit", ["Book the room"])
    edited = by_text(listed(port, "ai-edit"))["Send the v2 deck to Acme"]
    assert (edited["id"], edited["owner"], edited["due"]) == (item["id"], "Priya", "Nov 30")


def test_user_added_item_survives_reprocessing(port):
    process("ai-add", ["Book the room"])
    status, body = call(port, "POST", "/api/action-items", {"recording_id": "ai-add", "text": "Call the venue"})
    assert status == 200 and body["item"]["provenance"] == "user"
    process("ai-add", ["Book the room"])
    process("ai-add", [])
    assert [i["text"] for i in listed(port, "ai-add")] == ["Call the venue"]


def test_user_deleted_ai_item_stays_deleted(port):
    process("ai-delete", ["Send the pricing deck to Acme", "Book the room"])
    junk = by_text(listed(port, "ai-delete"))["Send the pricing deck to Acme"]
    assert call(port, "POST", f"/api/action-items/{junk['id']}/delete", {})[0] == 200
    process("ai-delete", ["send the pricing deck to acme.", "Book the room"])
    process("ai-delete", ["Send the pricing deck to Acme now", "Book the room"])  # reworded copy stays gone too
    assert [i["text"] for i in listed(port, "ai-delete")] == ["Book the room"]


def test_unknown_item_is_404(port):
    assert call(port, "POST", "/api/action-items/nope", {"done": True})[0] == 404
    assert call(port, "POST", "/api/action-items/nope/delete", {})[0] == 404


def test_migration_from_the_todo_store_keeps_ids_and_done_marks(port):
    """An Install that stored To-dos in the plugin's own table before core
    Action items existed: ids and done marks carry over once."""
    recording("ai-migrate", ["Send the deck", "Book the room"])
    with db.get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS todo_items (id TEXT PRIMARY KEY, recording_id TEXT NOT NULL,
                        text TEXT NOT NULL, position INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0, done_at TEXT,
                        superseded_at TEXT, created_at TEXT NOT NULL)""")
        conn.execute("CREATE TABLE IF NOT EXISTS todo_synced (recording_id TEXT PRIMARY KEY, synced_at TEXT NOT NULL)")
        conn.execute("INSERT INTO todo_items VALUES ('legacyid000000a1', 'ai-migrate', 'Send the deck', 0, 0, NULL, NULL, 'x')")
        conn.execute("INSERT INTO todo_items VALUES ('legacyid000000a2', 'ai-migrate', 'Book the room', 1, 1, '2026-11-02', NULL, 'x')")
        conn.execute("INSERT INTO todo_synced VALUES ('ai-migrate', 'x')")
        conn.commit()
    action_items.migrate_from_todo_store(force=True)
    process("ai-migrate", ["Book the room", "Send the deck"])
    items = by_text(listed(port, "ai-migrate"))
    assert (items["Book the room"]["id"], items["Book the room"]["done"]) == ("legacyid000000a2", True)
    assert (items["Send the deck"]["id"], items["Send the deck"]["done"]) == ("legacyid000000a1", False)


def test_todos_view_reads_core_records(port):
    process("ai-todo-view", ["Send the deck"])
    item = listed(port, "ai-todo-view")[0]
    call(port, "POST", f"/api/action-items/{item['id']}", {"done": True})
    todos = [i for i in call(port, "GET", "/api/plugins/todo/items")[1]["items"] if i["recording_id"] == "ai-todo-view"]
    assert [(i["id"], i["text"], i["done"]) for i in todos] == [(item["id"], "Send the deck", True)]
    assert plugin_host.is_enabled("todo")


def test_parse_bullet_reads_owner_and_due():
    assert action_items.parse_item("Ship the fix (Owner: Priya, Due: Friday)") == \
        {"text": "Ship the fix", "owner": "Priya", "due": "Friday"}
    assert action_items.parse_item("Ship the fix (owner: unassigned)") == {"text": "Ship the fix", "owner": None, "due": None}
    assert action_items.parse_item({"action": "Ship", "owner_speaker_id": "SPEAKER_2", "due_date": "Mon"}) == \
        {"text": "Ship", "owner": "SPEAKER_2", "due": "Mon"}


def test_mcp_action_items_read_core_records(port):
    import mcp_server
    process("mcp-core", ["Send the deck (Owner: Priya, Due: Friday)", "Book the room"])
    items = by_text(listed(port, "mcp-core"))
    assert call(port, "POST", f"/api/action-items/{items['Book the room']['id']}", {"done": True})[0] == 200
    status, added = call(port, "POST", "/api/action-items", {"recording_id": "mcp-core", "text": "Call the vendor"})
    assert status in (200, 201)

    def mine(status):
        return {i["action"]: i for i in mcp_server.cora_get_action_items(status=status, limit=500)
                if i["recording_id"] == "mcp-core"}

    pending, done = mine("pending"), mine("done")
    assert set(pending) == {"Send the deck", "Call the vendor"}
    assert set(done) == {"Book the room"} and done["Book the room"]["id"] == items["Book the room"]["id"]
    assert (pending["Send the deck"]["owner"], pending["Send the deck"]["due_date"]) == ("Priya", "Friday")
    assert pending["Call the vendor"]["owner"] == "Unassigned"
