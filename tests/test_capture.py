"""Captured Recordings (python/capture.py): which Recordings get captured,
what the archive holds, and how the sender uploads it to a stub receiver
started by the test. Observations are what a teammate or the Cora team would
see: archive members, rows in the "Show what Cora shares" export, the beta
status route, and what reached the receiver."""
import datetime as dt
import io
import json
import shutil
import tarfile
import time
import uuid

import pytest
from test_beta_sender import BEARER, api, port, stub, team_build, wait_for  # noqa: F401 - fixtures

ARCHIVED = ["audio.mov", "call_summary.json", "diarization.json", "enhanced_notes.md", "metadata.json",
            "participants.json", "run_metadata.json", "speakers_timeline.json", "transcript_diarized.md"]


def _clear_captures():
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM captures")
        conn.commit()


@pytest.fixture
def clean_captures(team_build):
    """team_build with no captures queued before or after the test (other
    suites run the sender against the real capture module)."""
    _clear_captures()
    yield team_build
    import beta_sender
    beta_sender.stop(final_flush=False)
    _clear_captures()


def make_recording(duration_s=600.0, recording_id=None):
    """An archived Recording folder as the pipeline leaves it: what a capture
    takes plus what it must leave behind (playback mix, screenshots, OCR,
    capture status, earlier versions, progress file, transcription audio)."""
    import ai_trace
    import db
    import paths
    recording_id = recording_id or f"2026-11-10_14-00-00_meeting_{uuid.uuid4().hex[:8]}"
    folder = paths.RECORDINGS_DIR / recording_id
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "screenshots").mkdir(parents=True)
    (folder / "versions" / "20261110T140000").mkdir(parents=True)
    files = {
        "audio.mov": b"mic and system tracks",
        "transcript_diarized.md": b"# Meeting Transcript",
        "diarization.json": b'{"segments": []}',
        "speakers_timeline.json": b"[]",
        "participants.json": b'["A", "B"]',
        "enhanced_notes.md": b"# Notes",
        "call_summary.json": b"{}",
        "metadata.json": b'{"duration_seconds": 600}',
        "playback.m4a": b"mix",
        "audio_transcribed.wav": b"16k mono",
        "slides_ocr.json": b"[]",
        "capture_status.json": b"{}",
        ".pipeline_progress.json": b"{}",
        "screenshots/slide_1.png": b"png",
        "screenshots/slide_1.txt": b"slide text",
        "versions/20261110T140000/enhanced_notes.md": b"# Old notes",
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    db.create_recording(recording_id, str(folder), "Standup", "2026-11-10T14:00:00+00:00", duration_s, 100,
                        {"duration_seconds": duration_s})
    db.update_notes(recording_id, "my private manual notes")
    with ai_trace.run("local_meeting_pipeline", recording_id=recording_id):
        pass
    return recording_id


def members(archive):
    with tarfile.open(archive, "r:gz") as tar:
        return sorted(m.name for m in tar.getmembers())


# ---- the archive -----------------------------------------------------------------

def test_the_archive_holds_audio_transcript_timeline_participants_notes_and_run_metadata_only(clean_captures):
    import capture
    recording_id = make_recording()

    archive = capture.build_archive(recording_id)
    try:
        assert members(archive) == ARCHIVED
        with tarfile.open(archive, "r:gz") as tar:
            assert tar.extractfile("audio.mov").read() == b"mic and system tracks"
            runs = json.loads(tar.extractfile("run_metadata.json").read())
            text = tar.extractfile("run_metadata.json").read().decode()
        assert [r["pipeline"] for r in runs["runs"]] == ["local_meeting_pipeline"]
        assert "my private manual notes" not in text
    finally:
        archive.unlink()


# ---- asking for a capture --------------------------------------------------------

def test_a_request_queues_the_recording_once_and_keeps_the_first_reason(clean_captures, port):  # noqa: F811
    import capture
    recording_id = make_recording()

    assert capture.request(recording_id, "feedback") is True
    assert capture.request(recording_id, "sample") is False
    assert capture.request(recording_id, "feedback") is False

    assert capture.has_pending(recording_id) is True
    assert capture.pending_count() == 1
    pending = capture.next_pending()
    assert (pending["recording_id"], pending["reason"]) == (recording_id, "feedback")
    assert api(port, "GET", "/api/beta/status")[1]["pending_captures"] == 1


def test_pending_captures_come_out_oldest_first_and_leave_the_queue_once_uploaded(clean_captures):
    import capture
    first, second = make_recording(), make_recording()
    capture.request(first, "sample")
    capture.request(second, "feedback")

    assert capture.next_pending()["recording_id"] == first
    capture.mark_uploaded(first)
    assert capture.has_pending(first) is False
    assert capture.next_pending()["recording_id"] == second
    capture.mark_uploaded(second)
    assert not capture.next_pending()
    assert capture.pending_count() == 0
    assert capture.request(first, "feedback") is False  # at most once per Recording, even after upload


@pytest.mark.parametrize("veto", ["lockdown", "share_off", "no_receiver"])
def test_with_sharing_vetoed_a_request_queues_nothing(clean_captures, monkeypatch, veto):
    import capture
    import db
    if veto == "lockdown":
        monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    elif veto == "share_off":
        db.set_setting("share_usage", False)
    else:
        monkeypatch.setenv("CORA_BETA_RECEIVER_URL", "")
    recording_id = make_recording()

    assert capture.request(recording_id, "feedback") is False
    assert capture.has_pending(recording_id) is False
    assert capture.pending_count() == 0


@pytest.mark.parametrize("recording_id, reason", [("../etc", "feedback"), ("ok-id", "because")])
def test_a_request_the_receiver_would_refuse_raises(clean_captures, recording_id, reason):
    import capture
    with pytest.raises(ValueError):
        capture.request(recording_id, reason)


# ---- the sample --------------------------------------------------------------------
# Seeded draws, random.Random(recording_id).random(), worked out once for these ids.
DRAW_0_124 = "2026-11-10_09-00-00_standup_00000010"
DRAW_0_373 = "2026-11-10_09-00-00_standup_00000005"
DRAW_0_949 = "2026-11-10_09-00-00_standup_00000001"


def processing_finished(recording_id, duration_s=1200, **extra):
    import usage_events
    usage_events.record("processing_finished", {"recording_id": recording_id, "status": "ok",
                                                "duration_s": duration_s, **extra})


def remote_config(**overrides):
    import beta_sender
    import paths
    (paths.DATA_DIR / "remote_config.json").write_text(json.dumps({**beta_sender.CONFIG_DEFAULTS, **overrides}))


def queued():
    import db
    with db.get_db() as conn:
        return {r["recording_id"]: r["reason"] for r in conn.execute("SELECT * FROM captures")}


def test_at_the_default_rate_a_quarter_of_recordings_fall_in_the_sample_by_their_id(clean_captures):
    for recording_id in (DRAW_0_124, DRAW_0_373, DRAW_0_949):
        processing_finished(recording_id)
    assert queued() == {DRAW_0_124: "sample"}


def test_the_remote_config_sets_the_sample_rate(clean_captures):
    remote_config(capture_sample_rate=0.5)
    for recording_id in (DRAW_0_124, DRAW_0_373, DRAW_0_949):
        processing_finished(recording_id)
    assert queued() == {DRAW_0_124: "sample", DRAW_0_373: "sample"}


@pytest.mark.parametrize("cap, duration_s, sampled", [
    (60, 3599, True), (60, 3600, False), (60, 7200, False), (30, 1799, True), (30, 1800, False), (60, None, False)])
def test_recordings_at_or_over_the_length_cap_are_not_sampled(clean_captures, cap, duration_s, sampled):
    remote_config(capture_max_minutes=cap)
    processing_finished(DRAW_0_124, duration_s=duration_s)
    assert queued() == ({DRAW_0_124: "sample"} if sampled else {})


def test_reprocessing_or_a_later_rating_captures_a_sampled_recording_only_once(clean_captures):
    import capture
    processing_finished(DRAW_0_124)
    processing_finished(DRAW_0_124)
    assert capture.request(DRAW_0_124, "feedback") is False
    assert queued() == {DRAW_0_124: "sample"}


def test_other_events_never_sample(clean_captures):
    import usage_events
    usage_events.record("recording_stopped", {"recording_id": DRAW_0_124, "duration_s": 600})
    assert queued() == {}


def test_under_lockdown_nothing_is_sampled(clean_captures, monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    processing_finished(DRAW_0_124)
    assert queued() == {}


# ---- expiry ------------------------------------------------------------------------

T0 = dt.datetime(2026, 11, 1, 9, 0, tzinfo=dt.timezone.utc)


def at(monkeypatch, when):
    import capture
    monkeypatch.setattr(capture, "_now", lambda: when)


def dropped_events():
    import paths
    import usage_events
    path = usage_events.export_jsonl(paths.DATA_DIR / "test-export.jsonl")
    return [row["payload"] for row in map(json.loads, path.read_text().splitlines())
            if row["name"] == "capture_dropped"]


@pytest.fixture
def no_events(clean_captures):
    import db
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.commit()
    return clean_captures


def test_a_capture_not_uploaded_within_7_days_is_dropped_with_a_capture_dropped_event(no_events, monkeypatch):
    import capture
    old, fresh, sent = make_recording(), make_recording(), make_recording()
    at(monkeypatch, T0)
    capture.request(old, "feedback")
    capture.request(sent, "sample")
    capture.mark_uploaded(sent)
    at(monkeypatch, T0 + dt.timedelta(days=6))
    capture.request(fresh, "sample")

    at(monkeypatch, T0 + dt.timedelta(days=7))
    assert capture.drop_expired() == 0
    at(monkeypatch, T0 + dt.timedelta(days=7, seconds=1))
    assert capture.drop_expired() == 1

    assert capture.has_pending(old) is False and capture.has_pending(fresh) is True
    assert capture.next_pending()["recording_id"] == fresh
    assert dropped_events() == [{"recording_id": old, "reason": "feedback"}]
    assert capture.drop_expired() == 0  # dropped once
    assert capture.request(old, "feedback") is False
    assert len(dropped_events()) == 1


def test_the_sender_drops_expired_captures_on_its_flush_and_reports_them_instead_of_uploading(no_events, monkeypatch):
    import beta_sender
    import capture
    recording_id = make_recording()
    real_now = capture._now
    at(monkeypatch, real_now() - dt.timedelta(days=8))
    capture.request(recording_id, "feedback")
    monkeypatch.setattr(capture, "_now", real_now)

    beta_sender.start()

    assert wait_for(lambda: no_events.batches())
    [batch] = no_events.batches()
    assert [(e["name"], e["payload"]) for e in batch["events"]] == [
        ("capture_dropped", {"recording_id": recording_id, "reason": "feedback"})]
    assert "/v1/recordings" not in [r["path"] for r in no_events.requests]


# ---- upload ------------------------------------------------------------------------

def uploads(receiver):
    return [r for r in receiver.requests if r["path"] == "/v1/recordings"]


def temp_archives():
    import paths
    return sorted(p.name for p in paths.DATA_DIR.glob(".capture-*"))


def test_a_rated_recording_is_uploaded_after_the_events_with_its_headers_and_archive(no_events):
    import beta_sender
    import capture
    import db
    import usage_events
    db.set_setting("beta_display_name", "Asha")
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})
    recording_id = make_recording()
    capture.request(recording_id, "feedback")
    usage_events.record("notes_viewed", {"recording_id": recording_id})

    beta_sender.start()

    assert wait_for(lambda: not capture.has_pending(recording_id))
    assert [r["path"] for r in no_events.requests] == ["/v1/config", "/v1/events", "/v1/recordings"]
    [upload] = uploads(no_events)
    headers = upload["headers"]
    assert headers["Authorization"] == f"Bearer {BEARER}"
    assert headers["Content-Type"] == "application/gzip"
    assert int(headers["Content-Length"]) == len(upload["body"])
    assert headers["X-Cora-Install"] == json.loads(no_events.requests[1]["body"])["install_id"]
    assert headers["X-Cora-Recording"] == recording_id
    assert headers["X-Cora-Reason"] == "feedback"
    assert headers["X-Cora-Version"] == "0.4.0-test"
    assert headers["X-Cora-Display-Name"] == "Asha"
    with tarfile.open(fileobj=io.BytesIO(upload["body"]), mode="r:gz") as tar:
        assert sorted(tar.getnames()) == ARCHIVED
    assert temp_archives() == []


def test_a_display_name_outside_latin_1_is_sent_percent_encoded(no_events):
    import beta_sender
    import capture
    import db
    db.set_setting("beta_display_name", "Zoë 李 100%\nX-Evil: 1")
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})
    recording_id = make_recording()
    capture.request(recording_id, "feedback")

    beta_sender.start()

    assert wait_for(lambda: uploads(no_events))
    headers = uploads(no_events)[0]["headers"]
    assert headers["X-Cora-Display-Name"] == "Zo%C3%AB %E6%9D%8E 100%25%0AX-Evil: 1"
    assert "X-Evil" not in headers
    assert wait_for(lambda: not capture.has_pending(recording_id))


def test_a_recording_the_receiver_already_holds_409_counts_as_uploaded(no_events):
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (409, {"error": "already stored"})
    recording_id = make_recording()
    capture.request(recording_id, "sample")

    beta_sender.start()

    assert wait_for(lambda: not capture.has_pending(recording_id))
    assert len(uploads(no_events)) == 1
    assert temp_archives() == []


def test_a_failed_upload_keeps_the_capture_pending_and_shows_in_the_beta_status(no_events, port):  # noqa: F811
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (500, {"error": "disk full"})
    recording_id = make_recording()
    capture.request(recording_id, "sample")

    beta_sender.start()

    assert wait_for(lambda: uploads(no_events))
    assert wait_for(lambda: api(port, "GET", "/api/beta/status")[1]["last_error"])
    body = api(port, "GET", "/api/beta/status")[1]
    assert "500" in body["last_error"] and body["pending_captures"] == 1
    assert capture.has_pending(recording_id)
    assert temp_archives() == []


def test_pending_captures_upload_one_at_a_time_oldest_first_until_none_are_left(no_events):
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})
    first, second, third = make_recording(), make_recording(), make_recording()
    capture.request(first, "sample")
    capture.request(second, "feedback")
    capture.request(third, "sample")

    beta_sender.start()

    assert wait_for(lambda: capture.pending_count() == 0)
    assert [u["headers"]["X-Cora-Recording"] for u in uploads(no_events)] == [first, second, third]


def test_the_uploads_of_a_flush_stop_at_the_first_failure(no_events):
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (500, {"error": "disk full"})
    first, second = make_recording(), make_recording()
    capture.request(first, "sample")
    capture.request(second, "feedback")

    beta_sender.start()
    assert wait_for(lambda: uploads(no_events))
    time.sleep(0.3)

    assert [u["headers"]["X-Cora-Recording"] for u in uploads(no_events)] == [first]
    assert capture.pending_count() == 2


def test_a_failed_upload_is_retried_on_the_interval_without_a_new_event(no_events, monkeypatch):
    import beta_sender
    import capture
    monkeypatch.setenv("CORA_TELEMETRY_FLUSH_SECONDS", "0.3")
    no_events.replies["/v1/recordings"] = (503, {"error": "busy"})
    recording_id = make_recording()
    capture.request(recording_id, "feedback")

    beta_sender.start()
    assert wait_for(lambda: uploads(no_events))
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})

    assert wait_for(lambda: not capture.has_pending(recording_id), timeout=5)
    assert no_events.batches() == []  # no event was needed to trigger the retry


@pytest.mark.parametrize("status", [400, 401, 413])
def test_a_capture_the_receiver_refuses_is_dropped_with_a_capture_dropped_event(no_events, port, status):  # noqa: F811
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (status, {"error": "refused"})
    recording_id = make_recording()
    capture.request(recording_id, "feedback")

    beta_sender.start()

    assert wait_for(lambda: not capture.has_pending(recording_id))
    assert len(uploads(no_events)) == 1
    assert dropped_events() == [{"recording_id": recording_id, "reason": "feedback"}]
    assert str(status) in api(port, "GET", "/api/beta/status")[1]["last_error"]
    assert temp_archives() == []


def test_a_capture_queued_before_lockdown_is_never_uploaded_under_it(no_events, monkeypatch):
    import beta_sender
    import capture
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})
    recording_id = make_recording()
    capture.request(recording_id, "feedback")
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")

    beta_sender.start()
    beta_sender.flush_now()
    time.sleep(0.5)
    beta_sender.stop()

    assert no_events.requests == []
    assert capture.has_pending(recording_id)


def test_a_capture_whose_recording_was_deleted_is_dropped_quietly_and_the_next_one_uploads(no_events, port):  # noqa: F811
    import beta_sender
    import capture
    import db
    import paths
    no_events.replies["/v1/recordings"] = (201, {"stored": "x/y"})
    gone, kept = make_recording(), make_recording()
    capture.request(gone, "feedback")
    capture.request(kept, "sample")
    shutil.rmtree(paths.RECORDINGS_DIR / gone)
    db.delete_recording(gone)

    beta_sender.start()

    assert wait_for(lambda: uploads(no_events))
    assert [u["headers"]["X-Cora-Recording"] for u in uploads(no_events)] == [kept]
    assert not capture.has_pending(gone)
    assert dropped_events() == []
    assert api(port, "GET", "/api/beta/status")[1]["last_error"] is None


def test_dropping_a_capture_takes_it_off_the_queue_without_an_event(no_events):
    import capture
    recording_id = make_recording()
    capture.request(recording_id, "feedback")

    capture.drop(recording_id)

    assert not capture.has_pending(recording_id) and capture.next_pending() is None
    assert dropped_events() == []
    assert capture.request(recording_id, "sample") is False  # asked for once, whatever became of it
