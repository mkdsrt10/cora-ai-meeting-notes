import json
import sqlite3

import pytest

import ai_trace
import db
import paths
import transcript_edit


@pytest.fixture
def recording(tmp_path):
    paths.ensure_data_dir()
    db.init_db()
    rec_id = f"rec_{tmp_path.name}"
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True)
    db.create_recording(rec_id, str(folder), "Test", "2026-09-25T10:00:00", 60, 1, {})
    db.update_recording_data(rec_id, "diarization", {
        "summary": "Overview.",
        "model": "whisper-test",
        "segments": [
            {"speaker_id": "You", "speaker_name": "You", "start": "00:00", "end": "00:10", "text": "hello there"},
            {"speaker_id": "You", "speaker_name": "You", "start": "00:10", "end": "00:20", "text": "hi, thanks for joining"},
            {"speaker_id": "Participant", "speaker_name": "Participant", "start": "00:20", "end": "00:30", "text": "sure"},
            {"speaker_id": "Participant", "speaker_name": "Participant", "start": "00:30", "end": "00:40", "text": "next"},
        ],
    })
    return rec_id, folder


def corrections(rec_id):
    with sqlite3.connect(ai_trace.TRACE_DB) as conn:
        return conn.execute("SELECT field, before, after FROM corrections WHERE recording_id=?", (rec_id,)).fetchall()


def test_reassign_one_turn_and_rename_all(recording):
    rec_id, folder = recording
    transcript_edit.apply_edits(rec_id, folder, [
        {"index": 1, "speaker": "Priya", "role": "participant"},
        {"rename_from": "Participant", "speaker": "Rahul", "role": "participant"},
        {"index": 0, "text": "Hello there."},
    ], self_name="Jane")
    segs = db.get_recording_data(rec_id, "diarization")["segments"]
    assert [s["speaker_name"] for s in segs] == ["You", "Priya", "Rahul", "Rahul"]
    assert segs[1]["original_speaker_id"] == "You" and segs[1]["speaker_source"] == "manual"
    assert segs[0]["text"] == "Hello there." and segs[0]["original_text"] == "hello there"
    md = (folder / "transcript_diarized.md").read_text()
    assert "**00:10–00:20 · Priya**" in md
    on_disk = json.loads((folder / "diarization.json").read_text())
    assert on_disk["segments"][2]["speaker_name"] == "Rahul"
    assert len(corrections(rec_id)) == 4  # 1 reassign + 2 renamed + 1 text


def test_mark_turn_as_self(recording):
    rec_id, folder = recording
    transcript_edit.apply_edits(rec_id, folder, [{"index": 2, "speaker": "", "role": "self"}], self_name="Jane")
    seg = db.get_recording_data(rec_id, "diarization")["segments"][2]
    assert seg["speaker_id"] == "You" and seg["speaker_name"] == "Jane"


@pytest.mark.parametrize("bad", [[{"index": 99, "text": "x"}], [{"index": 0, "speaker": "", "role": "participant"}],
                                 [{"index": 0, "speaker": "X", "role": "admin"}]])
def test_rejects_invalid_edits(recording, bad):
    rec_id, folder = recording
    with pytest.raises(ValueError):
        transcript_edit.apply_edits(rec_id, folder, bad)


def test_transcribed_recording_without_audio_stays_listed(recording):
    from api import views
    rec_id, _folder = recording
    assert rec_id in {item["id"] for item in views.all_recordings()}
