"""continuation_status: pause/resume and "Continue this meeting" must show
live progress on the original recording's card without ever wiping its
real content back to the bare "Recording in progress…" placeholder (the
bug this whole mechanism replaced — see db.set_continuation_status)."""
import http.client
import json
import threading

import pytest

import db
import paths
import server
from api import auth, views

TOKEN = "continuation-test-token"


@pytest.fixture(scope="module")
def port():
    auth.API_TOKEN = TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": TOKEN}
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    return resp.status, (json.loads(data) if data else {})


@pytest.fixture
def finished_recording(tmp_path):
    paths.ensure_data_dir()
    db.init_db()
    rec_id = f"rec_{tmp_path.name}"
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True)
    db.create_recording(rec_id, str(folder), "Weekly Sync", "2026-09-25T10:00:00", 600, 1, {})
    db.update_recording_data(rec_id, "diarization", {
        "summary": "Overview.", "model": "whisper-test",
        "segments": [{"speaker_id": "You", "speaker_name": "You", "start": "00:00", "end": "00:10", "text": "hi"}],
    })
    db.update_recording_data(rec_id, "call_summary", {"title": "Weekly Sync", "decisions": ["Ship it"]})
    return rec_id


def test_set_and_clear_round_trips():
    db.create_recording("rec_cs_1", "/tmp/rec_cs_1", "Test", "2026-09-25T10:00:00", 60, 1, {})
    db.set_continuation_status("rec_cs_1", "recording")
    meta = db.get_recording_data("rec_cs_1", "metadata")
    assert meta["continuation_status"] == "recording"
    assert "continuation_started_at" in meta

    db.set_continuation_status("rec_cs_1", None)
    meta = db.get_recording_data("rec_cs_1", "metadata")
    assert "continuation_status" not in meta


def test_continuation_in_progress_keeps_real_content_visible(port, finished_recording):
    rec_id = finished_recording
    status, _ = request(port, "POST", "/api/recording/continuation-status", {"id": rec_id, "status": "recording"})
    assert status == 200

    item = next(i for i in views.all_recordings() if i["id"] == rec_id)
    # The actual bug: naively reusing the pending-placeholder `status` column
    # here would make this show up as a bare "Recording in progress…" card
    # with no title, no summary, and duration_seconds=0 — exactly what must
    # NOT happen to an already-finished meeting someone is adding audio to.
    assert item["title"] == "Weekly Sync"
    assert item["call_summary"]["decisions"] == ["Ship it"]
    assert item["continuation_status"] == "recording"


def test_invalid_continuation_status_rejected(port, finished_recording):
    status, body = request(port, "POST", "/api/recording/continuation-status",
                            {"id": finished_recording, "status": "bogus"})
    assert status == 400


def test_live_audio_rejects_while_still_recording(port):
    db.create_pending_recording("rec_live_1", source_stem="rec_live_1", recorded_at="2026-09-25T10:00:00",
                                 status="recording")
    status, body = request(port, "GET", "/api/recording/live-audio?id=rec_live_1")
    assert status == 409


def test_live_audio_404s_with_no_source_file(port):
    db.create_pending_recording("rec_live_2", source_stem="rec_live_2", recorded_at="2026-09-25T10:00:00",
                                 status="processing")
    status, _ = request(port, "GET", "/api/recording/live-audio?id=rec_live_2")
    assert status == 404
