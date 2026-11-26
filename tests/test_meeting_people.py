"""A meeting's People (participant_names) include the captured roster, not only
labelled speakers: the meeting page's People row, Home's avatars and the
person filter all read it."""
import json

import db
import paths
from api import views


def _meeting(rec_id, roster, overrides=None):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.m4a").write_bytes(b"x")
    meta = {"participant_overrides": overrides} if overrides else {}
    if not db.get_recording(rec_id):
        db.create_recording(rec_id, str(folder), rec_id, "2026-11-20T09:00:00+00:00", 60, 1, meta)
    (folder / "participants.json").write_text(json.dumps(roster))
    return next(r for r in views.all_recordings() if r["id"] == rec_id)


def test_captured_roster_names_are_the_meetings_people():
    item = _meeting("people-roster", ["Priya Shah", "Tom Reyes"])
    assert item["participant_names"] == ["Priya Shah", "Tom Reyes"]


def test_hidden_renamed_and_linked_participants_are_respected():
    db.upsert_person("p-dana", "Dana Whitfield", "", "", [], False, None, None, None, 0)
    item = _meeting("people-overrides", ["Junk Name", "Alex M", "D. W."], {
        "Junk Name": {"hidden": True},
        "Alex M": {"display_name": "Alex Moreno"},
        "D. W.": {"person_id": "p-dana"},
    })
    assert item["participant_names"] == ["Alex Moreno", "Dana Whitfield"]
