"""Live capture control: start/stop/pause/resume, live entries, screenshots."""
from __future__ import annotations
import datetime as dt
import subprocess
from pathlib import Path

from api.router import route
from pathlib import Path
import datetime as dt
import db
import paths
import subprocess
from api.core import ARCHETYPES, INBOX, safe_folder, safe_id
from api.views import PENDING_TITLES


@route("GET", '/api/unprocessed-recording')
def get_api_unprocessed_recording(req, path: str, query: dict) -> None:
    rec = db.get_unprocessed_recording()
    return req.send_json({"id": rec["id"]} if rec else {})


@route("POST", '/api/recording/start')
def post_api_recording_start(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    started_at = str(body.get("started_at") or dt.datetime.now().astimezone().isoformat())
    archetype_id = body.get("archetype_id")
    archetype = None
    if archetype_id is not None:
        try:
            aid = int(archetype_id)
            archetype = ARCHETYPES.get(aid)
        except (ValueError, TypeError):
            pass
    meeting_tool = str(body.get("meeting_tool") or "").strip() or None
    continues_recording_id = str(body.get("continues_recording_id") or "").strip() or None
    db.create_pending_recording(recording_id, source_stem=recording_id, recorded_at=started_at, status="recording", archetype=archetype, meeting_tool=meeting_tool, continues_recording_id=continues_recording_id)
    return req.send_json({"ok": True, "id": recording_id}, 201)


@route("POST", '/api/recording/status')
def post_api_recording_status(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    status = str(body.get("status", ""))
    if status not in PENDING_TITLES:
        raise ValueError(f"Invalid status: {status}")
    db.set_pending_recording_status(recording_id, status)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/continuation-status')
def post_api_recording_continuation_status(req, path: str, body: dict) -> None:
    recording_id = safe_id(str(body.get("id", "")))
    status = body.get("status")
    if status is not None and status not in ("recording", "processing"):
        raise ValueError(f"Invalid continuation status: {status}")
    child_id = str(body.get("child_id") or "").strip() or None
    db.set_continuation_status(recording_id, status, child_id=child_id)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/stop')
def post_api_recording_stop(req, path: str, body: dict) -> None:
    subprocess.run(["pkill", "-INT", "dual-capture"], check=False)
    return req.send_json({"ok": True})


@route("POST", '/api/recording/trigger-start')
def post_api_recording_trigger_start(req, path: str, body: dict) -> None:
    check = subprocess.run(["pgrep", "-f", "dual-capture"], capture_output=True, text=True)
    if check.returncode == 0 and check.stdout.strip():
        return req.send_json({"ok": False, "error": "Already recording."})
    continues_id = str(body.get("continues_recording_id") or "").strip() or None
    timestamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    recording_id = f"meeting_{timestamp}"
    out_file = INBOX / f"{recording_id}.mov"
    INBOX.mkdir(parents=True, exist_ok=True)
    capture_bin = paths.CAPTURE_DIR / "dual-capture"
    if not capture_bin.exists():
        return req.send_json({"ok": False, "error": f"Capture binary not found at {capture_bin}"}, 500)
    db.create_pending_recording(
        recording_id,
        source_stem=recording_id,
        recorded_at=dt.datetime.now().astimezone().isoformat(),
        status="recording",
        continues_recording_id=continues_id,
    )
    if continues_id:
        db.set_continuation_status(continues_id, "recording", child_id=recording_id)
    subprocess.Popen([str(capture_bin), str(out_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return req.send_json({"ok": True, "id": recording_id})


@route("POST", '/api/recording/pause')
def post_api_recording_pause(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", "")).strip()
    subprocess.run(["pkill", "-INT", "dual-capture"], check=False)
    if rec_id:
        db.set_pending_recording_status(rec_id, "paused")
    return req.send_json({"ok": True, "status": "paused"})


@route("POST", '/api/recording/resume')
def post_api_recording_resume(req, path: str, body: dict) -> None:
    rec_id = str(body.get("id", "")).strip()
    timestamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3] + "Z"
    new_recording_id = f"meeting_{timestamp}"
    out_file = INBOX / f"{new_recording_id}.mov"
    INBOX.mkdir(parents=True, exist_ok=True)
    capture_bin = paths.CAPTURE_DIR / "dual-capture"
    if not capture_bin.exists():
        return req.send_json({"ok": False, "error": f"Capture binary not found at {capture_bin}"}, 500)
    db.create_pending_recording(
        new_recording_id,
        source_stem=new_recording_id,
        recorded_at=dt.datetime.now().astimezone().isoformat(),
        status="recording",
        continues_recording_id=rec_id or None,
    )
    if rec_id:
        db.set_continuation_status(rec_id, "recording", child_id=new_recording_id)
    subprocess.Popen([str(capture_bin), str(out_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return req.send_json({"ok": True, "id": new_recording_id, "status": "recording"})


@route("POST", '/api/recording/screenshot')
def post_api_recording_screenshot(req, path: str, body: dict) -> None:
    folder = safe_folder(body.get("id", ""))
    import screenshot_engine
    meta = db.get_recording_data(folder.name, "metadata") or {}
    started = meta.get("source_modified_at") or meta.get("processed_at")
    elapsed = None
    if started:
        try:
            elapsed = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(started)).total_seconds()
        except Exception:
            elapsed = None
    entry = screenshot_engine.capture_and_ocr(folder, elapsed_sec=elapsed)
    return req.send_json({"ok": True, "screenshot": entry})


@route("POST", '/api/recording/live-entry')
def post_api_recording_live_entry(req, path: str, body: dict) -> None:
    # Called by the Electron main process right after a manual
    # "Snap Meeting Slide" screenshot is captured + OCR'd, so it
    # lands inline in the live chat-style feed at the moment it
    # was actually taken — not bolted on after the fact.
    rec_id = str(body.get("id", ""))
    if not db.get_recording(rec_id):
        raise FileNotFoundError(rec_id)
    db.add_live_transcript_entry(
        rec_id,
        entry_type=str(body.get("type", "screenshot")),
        speaker_id=body.get("speaker_id"),
        start_seconds=body.get("at_seconds"),
        end_seconds=body.get("at_seconds"),
        text=body.get("text"),
        # Bare filename only — resolved to a servable URL later
        # via live_transcript_payload(), against whichever of
        # inbox/ or the archived folder currently has it.
        image_path=Path(str(body.get("image_path", ""))).name or None,
    )
    return req.send_json({"ok": True})
