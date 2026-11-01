"""Todo/Planner: its after_meeting Hook stores a Recording's Action items as
To-dos with stable ids, so done marks survive reprocessing. The page (GET
/api/plugins/todo/items) reads the stored To-dos."""
import pytest

import db
import paths
import plugin_host


class _Req:
    def send_json(self, payload, status=200):
        self.payload, self.status = payload, status


@pytest.fixture
def todo():
    plugin_host.discover()
    from plugins.todo import items
    return items


def _recording(rec_id, action_items):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), f"Title {rec_id}", "2026-11-01T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "call_summary", {"action_items": action_items})


def _page(todo, rec_id):
    req = _Req()
    todo.get_items(req, "", {})
    return [i for i in req.payload["items"] if i["recording_id"] == rec_id]


def _done(todo, **body):
    req = _Req()
    todo.post_done(req, "", {"done": True, **body})
    return req


def test_hook_stores_action_items_deduplicated(todo):
    _recording("todo-hook", ["Send the deck", {"action": "Book the room"}, "send the  deck."])
    assert plugin_host.run_hook("after_meeting", "todo-hook")["todo"] is True
    page = _page(todo, "todo-hook")
    assert [(i["text"], i["done"]) for i in page] == [("Send the deck", False), ("Book the room", False)]
    assert len({i["id"] for i in page}) == 2


def test_ids_are_stable_and_done_marks_survive_reprocessing(todo):
    _recording("todo-reprocess", ["Send the deck", "Book the room"])
    plugin_host.run_hook("after_meeting", "todo-reprocess")
    before = {i["text"]: i["id"] for i in _page(todo, "todo-reprocess")}
    _done(todo, id=before["Book the room"])

    # Reprocessing reorders, rewords one item and drops another.
    _recording("todo-reprocess", ["Draft the budget", "Book the room"])
    plugin_host.run_hook("after_meeting", "todo-reprocess")
    after = {i["text"]: (i["id"], i["done"]) for i in _page(todo, "todo-reprocess")}
    assert after == {"Draft the budget": (after["Draft the budget"][0], False),
                     "Book the room": (before["Book the room"], True)}
    assert "Send the deck" not in after  # superseded, no longer listed

    # A superseded item that comes back keeps its id.
    _recording("todo-reprocess", ["Send the deck", "Book the room"])
    plugin_host.run_hook("after_meeting", "todo-reprocess")
    assert {i["text"]: i["id"] for i in _page(todo, "todo-reprocess")}["Send the deck"] == before["Send the deck"]


def test_done_by_listed_index_still_works(todo):
    _recording("todo-index", ["Send the deck", "Book the room"])
    plugin_host.run_hook("after_meeting", "todo-index")
    page = _page(todo, "todo-index")
    _done(todo, recording_id="todo-index", index=page[1]["index"])
    assert [i["done"] for i in _page(todo, "todo-index")] == [False, True]


def test_legacy_index_done_marks_migrate_once(todo):
    _recording("todo-legacy", ["", "Send the deck", "Book the room"])
    db.set_todo_state("todo-legacy", 2, True, "2026-10-01T10:00:00+00:00")
    page = _page(todo, "todo-legacy")  # not yet stored: backfilled on read
    assert [(i["text"], i["done"]) for i in page] == [("Send the deck", False), ("Book the room", True)]
    _recording("todo-legacy", ["Book the room", "Send the deck"])
    plugin_host.run_hook("after_meeting", "todo-legacy")
    assert {i["text"]: i["done"] for i in _page(todo, "todo-legacy")} == {"Book the room": True, "Send the deck": False}


def test_unknown_item_is_rejected(todo):
    with pytest.raises(FileNotFoundError):
        _done(todo, id="nope")
