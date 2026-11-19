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
    assert call(port, "GET", "/api/live/settings") == (200, {"mode": "on_device", "refused": None})


def test_live_settings_default_off(port):
    assert call(port, "GET", "/api/live/settings") == (200, {"mode": "off", "refused": None})


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


# --- T3: which transcript to show, Draft transcript, draft notes -------------

def make_folder(rec_id, *, transcript=False, live_lines=None, notes=None):
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    diarization = {"segments": [{"start": "00:00", "end": "00:03", "speaker_id": "You", "text": "Full words."}]} if transcript else {}
    db.create_recording(rec_id, str(folder), rec_id, "2026-11-20T09:00:00+00:00", 60, 1, {})
    if transcript:
        db.update_recording_data(rec_id, "diarization", diarization)
        (folder / "transcript_diarized.md").write_text("**00:00–00:03 · You**\n\nFull words.\n")
    if live_lines is not None:
        (folder / "live_transcript.jsonl").write_text("".join(json.dumps(x) + "\n" for x in live_lines))
    if notes:
        (folder / "enhanced_notes.md").write_text(notes)
    return folder


def test_view_while_recording_is_the_live_transcript(port):
    key = "meeting_2026-11-20T13-00-00-000Z"
    db.create_pending_recording(key, source_stem=key, recorded_at="2026-11-20T13:00:00", status="recording")
    # live off and nothing written: nothing to show yet
    assert call(port, "GET", f"/api/recording?id={key}")[1]["transcript_view"]["source"] == "none"
    db.set_setting("processing_preferences", processing.validate({"live": "on_device"}))
    body = call(port, "GET", f"/api/recording?id={key}")[1]
    assert body["transcript_view"] == {"source": "live", "label": "Live captions", "retry": False}
    write_inbox(key, [line(key, "mic", 0, "Hello.")])
    db.set_setting("processing_preferences", None)
    assert call(port, "GET", f"/api/recording?id={key}")[1]["transcript_view"]["source"] == "live"


def test_view_when_the_full_transcript_is_ready_is_the_full_one(port):
    rec = "2026-11-20_ready_aaa111"
    make_folder(rec, transcript=True, live_lines=[line(rec, "mic", 0, "Live words.")])
    body = call(port, "GET", f"/api/recording?id={rec}")[1]
    assert body["transcript_view"] == {"source": "full", "label": "Transcript", "retry": False}


def test_view_when_processing_failed_is_the_draft_transcript_with_retry(port):
    rec = "2026-11-20_failed_bbb222"
    make_folder(rec, live_lines=[line(rec, "mic", 0, "Only the live words survived.")])
    db.set_processing_failure(rec, {"code": "internal", "message": "boom"})
    body = call(port, "GET", f"/api/recording?id={rec}")[1]
    assert body["analysis_stage"] == "failed"
    assert body["transcript_view"] == {"source": "live", "label": "Draft transcript", "retry": True}
    lines = call(port, "GET", f"/api/recording/live-transcript?id={rec}&since=0")[1]["lines"]
    assert [x["text"] for x in lines] == ["Only the live words survived."]
    # without a Live transcript a failed Recording has nothing to show
    plain = "2026-11-20_failed_ccc333"
    make_folder(plain)
    db.set_processing_failure(plain, {"code": "internal", "message": "boom"})
    assert call(port, "GET", f"/api/recording?id={plain}")[1]["transcript_view"]["source"] == "none"


def long_lines(key, n=12):
    return [line(key, "mic" if i % 2 else "sys", i * 3, f"We agreed to ship the garden plan on Friday, item {i}.", seg=i)
            for i in range(n)]


def test_draft_notes_at_stop_then_replaced_by_full_notes(port, fake_text):
    key = "meeting_2026-11-20T14-00-00-000Z"
    db.create_pending_recording(key, source_stem=key, recorded_at="2026-11-20T14:00:00", status="processing")
    write_inbox(key, long_lines(key))
    fake_text.reply = "## Summary\nShip on Friday.\n## Decisions\n- Ship Friday\n## Action items\n- None noted."
    status, body = call(port, "POST", "/api/recording/draft-notes", {"id": key})
    assert (status, body["ok"]) == (200, True)
    call_ = fake_text.calls[-1]
    assert call_["max_tokens"] == 600 and call_["trace"] == "notes.draft_live"
    assert "We agreed to ship the garden plan" in call_["prompt"]
    pending = call(port, "GET", f"/api/recording?id={key}")[1]
    assert pending["draft_notes"]["label"] == "Draft"
    assert "Ship on Friday." in pending["draft_notes"]["markdown"]
    assert pending["transcript_view"] == {"source": "live", "label": "Draft transcript", "retry": False}

    # import: the draft and the Live transcript move into the Recording folder
    rec = "2026-11-20_draft_ddd444"
    folder = make_folder(rec)
    assert live_transcript.adopt(key, folder)
    assert (folder / "draft_notes.md").is_file() and not live_transcript.draft_inbox_path(key).exists()
    assert call(port, "GET", f"/api/recording?id={rec}")[1]["draft_notes"]["markdown"].startswith("## Summary")
    # full notes land: the draft is no longer shown (still on disk beside them)
    (folder / "enhanced_notes.md").write_text("## Full notes\n- Real ones\n")
    assert call(port, "GET", f"/api/recording?id={rec}")[1]["draft_notes"] is None


def test_draft_notes_refusals_change_nothing(port, fake_text, monkeypatch):
    key = "meeting_2026-11-20T15-00-00-000Z"
    assert call(port, "POST", "/api/recording/draft-notes", {"id": key})[1] == {"ok": False, "reason": "no_live_transcript"}
    write_inbox(key, [line(key, "mic", 0, "Too short.")])
    assert call(port, "POST", "/api/recording/draft-notes", {"id": key})[1] == {"ok": False, "reason": "too_short"}
    write_inbox(key, long_lines(key))

    class Busy:
        def __enter__(self):
            raise processing.ProcessingBusyError()

        def __exit__(self, *a):
            return False
    with monkeypatch.context() as m:
        m.setattr(processing, "scope", lambda *a, **k: Busy())
        assert call(port, "POST", "/api/recording/draft-notes", {"id": key})[1] == {"ok": False, "reason": "busy"}

    def boom(*a, **k):
        raise RuntimeError("provider down")
    fake_text.reply = boom
    assert call(port, "POST", "/api/recording/draft-notes", {"id": key})[1] == {"ok": False, "reason": "model_failed"}
    assert not live_transcript.draft_inbox_path(key).exists()


def test_export_never_includes_the_live_transcript():
    import recording_export
    rec = "2026-11-20_export_eee555"
    make_folder(rec, transcript=True, notes="## Notes\n- Final\n",
                live_lines=[line(rec, "mic", 0, "LIVE-ONLY-WORDS should never be exported.")])
    out = recording_export.build(rec, include_transcript=True)
    assert "Full words." in out["markdown"]
    assert "LIVE-ONLY-WORDS" not in out["markdown"]


def test_captured_recording_includes_the_live_transcript():
    import tarfile
    import capture
    rec = "2026-11-20_capture_fff666"
    folder = make_folder(rec, transcript=True, live_lines=[line(rec, "mic", 0, "Kept for review.")])
    (folder / "audio.mov").write_bytes(b"\0")
    archive = capture.build_archive(rec)
    try:
        with tarfile.open(archive) as tar:
            assert "live_transcript.jsonl" in tar.getnames()
    finally:
        archive.unlink(missing_ok=True)


def test_merged_continuation_keeps_one_live_record_and_deletes_the_child(fake_text, fake_transcriber, monkeypatch):
    """A Continuation is the one place Cora deletes a Recording folder: its
    Live transcript goes with it, its lines appended to the parent's."""
    from pipeline import runner
    parent = make_folder("live-parent", live_lines=[line("p", "mic", 0, "Parent words.")])
    child = make_folder("live-child", live_lines=[line("c", "sys", 1, "Child words.")])
    (child / "audio.wav").write_bytes(b"")
    db.update_recording_data("live-child", "metadata", {"continues_recording_id": "live-parent"})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "You")
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."}]
    fake_text.reply = lambda prompt, trace, **kw: "general" if trace == "template.select" else json.dumps(dict(
        title="Sync", overview="Deck.", action_items_md="- Send the deck", decisions_md="- None noted.",
        timeline_md="- Deck", open_questions_md="- None noted.", key_entities_md="- Deck"))
    result = runner.process_recording_local(child, dict(mode="local_light", transcription="local", provider="local_mlx",
                                                        model="", template="general", live="off"))
    assert result["recording_id"] == "live-parent"
    assert not child.exists()
    texts = [(x["text"], x["start"]) for x in live_transcript.read_all("live-parent")]
    assert texts[0] == ("Parent words.", 0)
    assert texts[1][0] == "Child words." and texts[1][1] >= 1
