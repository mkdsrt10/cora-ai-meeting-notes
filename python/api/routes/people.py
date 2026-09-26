"""People directory, participants and speaker labelling."""
from __future__ import annotations
import datetime as dt
import re

from api.router import route
from diarization import confirm_speaker
from diarization import label_speaker
from diarization import reset_speaker
import datetime as dt
import db
import re
from api.core import safe_folder
from api.views import RAW_ID_PATTERN


@route("GET", '/api/people')
def get_api_people(req, path: str, query: dict) -> None:
    return req.send_json({"people": db.get_all_people()})


@route("GET", '/api/person')
def get_api_person(req, path: str, query: dict) -> None:
    person_id = query.get("id", [""])[0]
    person = db.get_person(person_id)
    if not person:
        raise FileNotFoundError(person_id)
    recordings = db.get_person_recordings(person_id)
    for r in recordings:
        if not r.get("title") or RAW_ID_PATTERN.match(r["title"]):
            r["title"] = "Recording"
    return req.send_json({"person": person, "recordings": recordings})


@route("POST", '/api/people/create')
def post_api_people_create(req, path: str, body: dict) -> None:
    name = str(body.get("name", "")).strip()
    if not name:
        raise ValueError("Name is required")
    role = str(body.get("role", "")).strip()
    relationship = str(body.get("relationship", "")).strip()
    person_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or dt.datetime.now().strftime("p%Y%m%d%H%M%S%f")
    now = dt.datetime.now().astimezone().isoformat()
    db.upsert_person(
        person_id, name, role, str(body.get("organization", "")).strip(),
        [relationship] if relationship else [], False, None, now, now, 0,
    )
    return req.send_json({"ok": True, "person": db.get_person(person_id)}, 201)


@route("POST", '/api/people/update')
def post_api_people_update(req, path: str, body: dict) -> None:
    person_id = str(body.get("id", ""))
    person = db.get_person(person_id)
    if not person:
        raise FileNotFoundError(person_id)
    db.upsert_person(
        person_id,
        str(body.get("name", person["name"])),
        str(body.get("role", person["role"] or "")),
        str(body.get("organization", person["organization"] or "")),
        body.get("tags", person["tags"]),
        bool(person["is_self"]),
        person["reference_clip_path"],
        person["first_seen"],
        person["last_seen"],
        person["recordings_count"],
    )
    return req.send_json({"ok": True, "person": db.get_person(person_id)})


@route("POST", '/api/people/merge')
def post_api_people_merge(req, path: str, body: dict) -> None:
    primary_id = str(body.get("primary_id", ""))
    duplicate_id = str(body.get("duplicate_id", ""))
    if not primary_id or not duplicate_id or primary_id == duplicate_id:
        raise ValueError("primary_id and duplicate_id must be distinct")
    if not db.get_person(primary_id) or not db.get_person(duplicate_id):
        raise FileNotFoundError("Unknown person id")
    db.merge_people(primary_id, duplicate_id)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/participant')
def post_api_recording_participant(req, path: str, body: dict) -> None:
    # Edits (rename / hide / map-to-person) against one entry in
    # the AX-discovered roster. Keyed by raw_name — the raw
    # detected string, not a stable id, since participants.json
    # itself has no ids — see participants_payload().
    rec_id = str(body.get("id", ""))
    raw_name = str(body.get("raw_name", ""))
    action = str(body.get("action", ""))
    if not db.get_recording(rec_id):
        raise FileNotFoundError(rec_id)
    if not raw_name:
        raise ValueError("raw_name is required")
    metadata = db.get_recording_data(rec_id, "metadata") or {}
    overrides = metadata.setdefault("participant_overrides", {})
    entry = overrides.setdefault(raw_name, {})
    if action == "rename":
        entry["display_name"] = str(body.get("display_name") or "").strip() or None
    elif action == "hide":
        entry["hidden"] = True
    elif action == "unhide":
        entry["hidden"] = False
    elif action == "map":
        entry["person_id"] = body.get("person_id") or None
    else:
        raise ValueError(f"Unknown action: {action}")
    db.update_recording_data(rec_id, "metadata", metadata)
    return req.send_json({"ok": True})


@route("POST", '/api/confirm-speaker')
def post_api_confirm_speaker(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    result = confirm_speaker(folder, str(body.get("speaker_id", "")))
    return req.send_json({"ok": True, "identity": result})


@route("POST", '/api/label-speaker')
def post_api_label_speaker(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    result = label_speaker(
        folder,
        str(body.get("speaker_id", "")),
        str(body.get("name", "")),
        str(body.get("role", "")),
        str(body.get("organization", "")),
    )
    return req.send_json({"ok": True, "speaker": result})


@route("POST", '/api/reset-speaker')
def post_api_reset_speaker(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    reset_speaker(folder)
    return req.send_json({"ok": True})
