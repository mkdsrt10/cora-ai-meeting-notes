"""The notes-context eval's scoring (tools/eval_notes_context.py): counts per
arm from judge labels, so the checkpoint gates read the right numbers."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("eval_notes_context", Path(__file__).resolve().parents[1] / "tools" / "eval_notes_context.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def notes(actions, decisions=("- None noted.",)):
    return {"overview": "o", "action_items_md": "\n".join(actions), "decisions_md": "\n".join(decisions),
            "open_questions_md": "- None noted."}


def test_score_counts_precision_recall_owners_and_follow_ups(tmp_path):
    write(tmp_path / "judge/M1/reference.json", {"action_items": [{"id": "A1"}, {"id": "A2"}], "decisions": [{"id": "D1"}],
                                                 "open_questions": []})
    write(tmp_path / "notes/M1/B.json", {"seconds": 10, "notes": notes(
        ["- Send the deck (Owner: Priya)", "- Follow-up: book the room (Owner: Sam)", "- Draft it", "- Send the deck again"],
        ["- Price stays"])})
    write(tmp_path / "judge/M1/B.json", {
        "action_items": [{"i": 0, "label": "supported", "ref": "A1", "owner": "correct", "continues": None},
                         {"i": 1, "label": "supported", "ref": "A2", "owner": "wrong", "continues": "P1"},
                         {"i": 2, "label": "fabricated", "ref": None, "owner": "missing", "continues": "P2"},
                         {"i": 3, "label": "duplicate", "ref": "A1", "owner": "correct", "continues": None}],
        "decisions": [{"i": 0, "label": "distorted", "ref": "D1"}], "open_questions": [],
        "overview": {"accuracy": 4, "usefulness": 3}})
    b = ev.score(tmp_path)["B"]
    acts = b["action_items"]
    assert (acts["produced"], acts["supported"], acts["recalled"], acts["reference"]) == (4, 2, 2, 2)
    assert (acts["owner_given"], acts["owner_correct"]) == (2, 1)
    assert (acts["follow_ups"], acts["follow_ups_marked"], acts["marked_not_follow_up"]) == (2, 1, 0)
    assert (b["decisions"]["supported"], b["decisions"]["recalled"], b["decisions"]["distorted"]) == (0, 0, 1)


def test_items_of_reads_owner_due_and_follow_up_marks():
    items = ev.items_of(notes(["- Follow-up: send the deck (Owner: Priya, Due: Fri)", "- - None noted."]))
    assert items["action_items"][0] == {"text": "Follow-up: send the deck", "owner": "Priya", "due": "Fri",
                                        "marked_follow_up": True}
