"""Audio pruning (python/audio_pruning.py): a pass deletes the audio of
Recordings older than the retention, then the oldest remaining audio while
the total is over the cap, and never touches a Recording that is live,
processing, failed or waiting to be captured. Observations are what a
teammate would see: the files left in each Recording folder, the Recording
as the API shows it, and the notifications list."""
import datetime as dt
import shutil
import uuid

import pytest
from test_beta_sender import api, port, stub, team_build, wait_for  # noqa: F401 - fixtures

MB = 1024 * 1024
AUDIO = ("audio.mov", "playback.m4a", "audio_transcribed.wav")
KEPT = ("transcript_diarized.md", "enhanced_notes.md", "speakers_timeline.json", "participants.json",
        "diarization.json", "call_summary.json", "metadata.json", "screenshots/slide_1.png")


@pytest.fixture
def library(monkeypatch):
    """An empty Recording library with default retention settings."""
    import db
    monkeypatch.delenv("CORA_AUDIO_PRUNING_DISABLED", raising=False)
    with db.get_db() as conn:
        for table in ("recordings", "captures", "notifications"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM settings WHERE key IN ('audio_retention_days', 'audio_cap_mb')")
        conn.commit()
    yield
    with db.get_db() as conn:
        conn.execute("DELETE FROM settings WHERE key IN ('audio_retention_days', 'audio_cap_mb')")
        conn.commit()


def make_recording(days_old, audio_mb=1, status=None, recording_id=None, metadata=None, processed=True):
    """An archived Recording folder as the pipeline leaves it, recorded
    `days_old` days ago, whose original audio is `audio_mb` MB (sparse);
    processed (diarized) unless `processed` is False."""
    import db
    import paths
    recording_id = recording_id or f"rec_{uuid.uuid4().hex[:10]}"
    folder = paths.RECORDINGS_DIR / recording_id
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "screenshots").mkdir(parents=True)
    (folder / "versions" / "20261001T100000").mkdir(parents=True)
    for name in KEPT:
        (folder / name).write_bytes(b"kept")
    (folder / "versions" / "20261001T100000" / "enhanced_notes.md").write_bytes(b"old notes")
    with open(folder / "audio.mov", "wb") as f:
        f.truncate(int(audio_mb * MB))
    (folder / "playback.m4a").write_bytes(b"mix")
    (folder / "audio_transcribed.wav").write_bytes(b"16k mono")
    (folder / "versions" / "20261001T100000" / "audio_transcribed.wav").write_bytes(b"older 16k mono")
    recorded_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_old)).isoformat()
    db.create_recording(recording_id, str(folder), "Standup", recorded_at, 600, 100, metadata or {})
    if processed:
        db.update_recording_data(recording_id, "diarization", {"model": "test", "segments": []})
    if status:
        db.set_pending_recording_status(recording_id, status)
    return recording_id


def audio_left(recording_id):
    import paths
    folder = paths.RECORDINGS_DIR / recording_id
    return sorted(p.name for p in folder.rglob("*")
                  if p.name.startswith(("audio.", "audio_transcribed.")) or p.name == "playback.m4a")


def item(recording_id):
    import db
    from api import views
    return views.recording_item(db.get_recording(recording_id), detailed=True)


def test_audio_older_than_the_retention_is_removed_and_everything_else_is_kept(library):
    import audio_pruning
    import paths
    old = make_recording(days_old=40)
    recent = make_recording(days_old=3)

    counts = audio_pruning.run_pass()

    assert audio_left(old) == []
    assert audio_left(recent) == ["audio.mov", "audio_transcribed.wav", "audio_transcribed.wav", "playback.m4a"]
    for name in KEPT:
        assert (paths.RECORDINGS_DIR / old / name).is_file(), name
    assert counts["by_age"] == 1 and counts["by_cap"] == 0 and counts["removed"] == 1
    assert item(old)["audio_url"] is None
    assert item(old)["audio_pruned"]["reason"] == "retention"
    assert item(old)["audio_pruned"]["limit"] == 30
    assert dt.datetime.fromisoformat(item(old)["audio_pruned"]["at"])
    assert item(recent)["audio_pruned"] is None


def test_over_the_cap_the_oldest_audio_goes_first_until_the_rest_fits(library):
    import audio_pruning
    import db
    db.set_setting("audio_cap_mb", 50)
    oldest = make_recording(days_old=20, audio_mb=20)
    middle = make_recording(days_old=10, audio_mb=20)
    newer = make_recording(days_old=5, audio_mb=20)
    newest = make_recording(days_old=1, audio_mb=20)

    counts = audio_pruning.run_pass()

    # 80 MB over a 50 MB cap: dropping the two oldest leaves 40 MB.
    assert audio_left(oldest) == [] and audio_left(middle) == []
    assert "audio.mov" in audio_left(newer) and "audio.mov" in audio_left(newest)
    assert counts["by_cap"] == 2 and counts["by_age"] == 0
    assert item(oldest)["audio_pruned"]["reason"] == "cap"
    assert item(oldest)["audio_pruned"]["limit"] == 50
    assert audio_pruning.run_pass()["removed"] == 0


def test_live_processing_failed_continued_and_capture_pending_recordings_are_never_touched(library, team_build):
    import audio_pruning
    import capture
    import db
    db.set_setting("audio_cap_mb", 50)
    live = make_recording(days_old=40, status="recording")
    paused = make_recording(days_old=40, status="paused")
    processing = make_recording(days_old=40, status="processing")
    failed = make_recording(days_old=40)
    db.set_processing_failure(failed, {"code": "internal", "message": "boom", "at": "2026-10-01T10:00:00Z"})
    continued = make_recording(days_old=40, metadata={"continuation_status": "processing"})
    captured = make_recording(days_old=40, audio_mb=60)
    assert capture.request(captured, "feedback")
    # Never processed: its audio is all there is of it.
    unprocessed = make_recording(days_old=40, processed=False)
    eligible = make_recording(days_old=1, audio_mb=5)

    counts = audio_pruning.run_pass()

    for recording_id in (live, paused, processing, failed, continued, captured, unprocessed):
        assert "audio.mov" in audio_left(recording_id), recording_id
        assert not (db.get_recording(recording_id)["metadata"] or {}).get("audio_pruned_at"), recording_id
    # The untouchable audio still counts toward the cap, so the one Recording
    # pruning may touch goes even though it is a day old.
    assert audio_left(eligible) == []
    assert counts["skipped"] == 7 and counts["by_cap"] == 1 and counts["by_age"] == 0


def test_a_pass_that_removed_audio_says_so_once_and_a_pass_that_removed_nothing_is_silent(library):
    import audio_pruning
    import db
    make_recording(days_old=40)
    make_recording(days_old=35)
    make_recording(days_old=2)

    audio_pruning.run_pass()
    audio_pruning.run_pass()

    notes = db.get_notifications()
    assert len(notes) == 1
    assert notes[0]["body"] == "Audio removed from 2 recordings to save space. Transcripts and notes are kept."
    assert notes[0]["recording_id"] is None


def test_a_pass_runs_when_a_processing_job_ends_even_one_that_failed(library, port):
    old = make_recording(days_old=40)

    status, body = api(port, "POST", "/api/process-recording", {"id": "no-such-recording"})

    assert status >= 400 and body["code"]
    assert wait_for(lambda: audio_left(old) == [])


def test_the_server_start_pass_runs_on_its_own_thread(library):
    import audio_pruning
    old = make_recording(days_old=40)
    try:
        audio_pruning.start()
        assert wait_for(lambda: audio_left(old) == [])
    finally:
        audio_pruning.stop()


def test_automatic_passes_are_off_while_the_suite_disables_them(library, monkeypatch):
    import audio_pruning
    monkeypatch.setenv("CORA_AUDIO_PRUNING_DISABLED", "1")
    old = make_recording(days_old=40)

    audio_pruning.trigger()
    audio_pruning.start()

    assert not wait_for(lambda: audio_left(old) == [], timeout=0.5)


def test_once_the_capture_is_uploaded_the_recording_can_be_pruned(library, team_build):
    import audio_pruning
    import capture
    recording_id = make_recording(days_old=40)
    capture.request(recording_id, "sample")
    assert audio_pruning.run_pass()["removed"] == 0

    capture.mark_uploaded(recording_id)

    assert audio_pruning.run_pass()["removed"] == 1
    assert audio_left(recording_id) == []
