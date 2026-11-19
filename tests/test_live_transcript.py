"""Live transcript, seam 3 (recording API): the Processing profile's `live`
field, the read route the Transcript tab polls, and the file's move into the
Recording folder (docs/specs/live-transcript.md, T2/T3)."""
import http.client
import json
import threading

import pytest

import db
import live_transcript
import paths
import processing
import server
from api import auth

TOKEN = "live-transcript-test-token"


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


@pytest.fixture(autouse=True)
def clean():
    paths.ensure_data_dir()
    db.init_db()
    db.set_setting("processing_preferences", None)
    yield
    db.set_setting("processing_preferences", None)


def line(rec, track, start, text, final=True, seg=0, speaker=None):
    return {"recording_id": rec, "track": track, "speaker": speaker, "start": start, "end": start + 1,
            "text": text, "final": final, "engine": "speech_transcriber", "seg": seg}


def write_inbox(key, lines, tail=""):
    path = live_transcript.inbox_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + tail)
    return path


# --- Processing profile: `live` ---------------------------------------------

def test_live_is_off_by_default_and_validated():
    assert processing.preferences()["live"] == "off"
    assert processing.validate({"mode": "cloud"})["live"] == "off"
    assert processing.validate({"live": "on_device"})["live"] == "on_device"
    with pytest.raises(ValueError):
        processing.validate({"live": "always"})


def test_live_is_independent_of_transcription_and_mode(port):
    status, body = call(port, "POST", "/api/processing", {"mode": "local_light", "live": "on_device"})
    assert status == 200 and body["preferences"]["live"] == "on_device"
    assert processing.preferences()["transcription"] == "local"
    # choosing another mode keeps the live engine
    assert processing.resolve({"mode": "local_thorough"})["live"] == "on_device"
    assert call(port, "GET", "/api/live/settings") == (200, {"mode": "on_device"})


def test_live_settings_default_off(port):
    assert call(port, "GET", "/api/live/settings") == (200, {"mode": "off"})


# --- Reading the file (Transcript tab, MCP) ----------------------------------

def test_read_route_returns_lines_after_the_cursor(port):
    key = "meeting_2026-11-20T10-00-00-000Z"
    write_inbox(key, [line(key, "mic", 0.5, "Good morning."), line(key, "sys", 1.5, "Hi.")],
                tail='{"half": "a line still being written')
    status, body = call(port, "GET", f"/api/recording/live-transcript?id={key}&since=0")
    assert status == 200
    assert [x["text"] for x in body["lines"]] == ["Good morning.", "Hi."]
    cursor = body["cursor"]
    # nothing new: same cursor, no lines
    assert call(port, "GET", f"/api/recording/live-transcript?id={key}&since={cursor}")[1]["lines"] == []
    # the writer finishes its line and adds one more (one malformed line skipped)
    path = live_transcript.inbox_path(key)
    text = path.read_text()
    path.write_text(text[: text.rindex("\n") + 1] + "not json\n" + json.dumps(line(key, "mic", 3, "Next.")) + "\n")
    status, body = call(port, "GET", f"/api/recording/live-transcript?id={key}&since={cursor}")
    assert [x["text"] for x in body["lines"]] == ["Next."]
    assert body["cursor"] == path.stat().st_size


def test_read_route_rejects_bad_ids_and_cursors(port):
    assert call(port, "GET", "/api/recording/live-transcript?id=../etc&since=0")[0] in (400, 404)
    assert call(port, "GET", "/api/recording/live-transcript?id=x&since=abc")[0] in (400, 404)
    assert call(port, "GET", "/api/recording/live-transcript?id=missing_one&since=0")[1] == {
        "id": "missing_one", "lines": [], "cursor": 0}


def test_adopt_moves_the_file_into_the_recording_folder_and_lookups_follow():
    key = "meeting_2026-11-20T11-00-00-000Z"
    write_inbox(key, [line(key, "mic", 0, "Kept beside the full transcript.")])
    folder = paths.RECORDINGS_DIR / "2026-11-20_kept_abc123"
    folder.mkdir(parents=True, exist_ok=True)
    assert live_transcript.adopt(key, folder) is True
    assert not live_transcript.inbox_path(key).exists()
    assert (folder / "live_transcript.jsonl").is_file()
    db.create_recording(folder.name, str(folder), key, "2026-11-20T11:00:00", 60, 1, {"live_recording_id": key})
    # the old live id and the folder id both find it
    assert [x["text"] for x in live_transcript.read_all(key)] == ["Kept beside the full transcript."]
    assert [x["text"] for x in live_transcript.read_all(folder.name)] == ["Kept beside the full transcript."]
    assert live_transcript.adopt("meeting_without_live", folder) is False


def test_a_later_chunk_reads_the_sessions_file():
    root = "meeting_2026-11-20T12-00-00-000Z"
    child = "meeting_2026-11-20T12-10-00-000Z"
    write_inbox(root, [line(root, "mic", 0, "First chunk."), line(child, "mic", 600, "Second chunk.")])
    db.create_pending_recording(child, source_stem=child, recorded_at="2026-11-20T12:10:00", status="recording",
                                continues_recording_id=root)
    assert [x["recording_id"] for x in live_transcript.read_all(child)] == [root, child]
