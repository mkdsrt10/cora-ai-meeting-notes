"""voice_memo_pipeline --recording-id: archive one live Recording by id, with
exit codes the Processing queue retries on (no age heuristic)."""
import os
import time

import pytest

import db
import paths
import voice_memo_pipeline as vmp


@pytest.fixture(autouse=True)
def database():
    paths.ensure_data_dir()
    db.init_db()


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(vmp, "INBOX", tmp_path)
    db.set_setting("state", {"processed": {}})
    return tmp_path


def test_missing_audio_is_no_input(inbox):
    assert vmp.archive_recording("meeting_missing") == vmp.EXIT_NO_INPUT


def test_fresh_file_is_archived_without_waiting(inbox, monkeypatch):
    audio = inbox / "meeting_2026-11-01T09-00-00-000Z.mov"
    audio.write_bytes(b"x")  # brand new: younger than minimum_age_seconds
    seen = []

    def fake_process(path, key, config):
        seen.append(path.name)
        _archived_row(path.stem)
        return inbox / "archived_folder"

    monkeypatch.setattr(vmp, "process", fake_process)
    assert vmp.archive_recording(audio.stem) == 0
    assert seen == [audio.name]
    # Already archived: a retry is a success, not a second import.
    assert vmp.archive_recording(audio.stem) == 0
    assert seen == [audio.name]


def _archived_row(live_id):
    db.create_recording(f"2026-11-01_{live_id}_0000abcd", "/tmp/x", "t", "2026-11-01T09:00:00+00:00", 1.0, 1,
                        {"live_recording_id": live_id})


def test_already_archived_but_row_missing_is_no_input(inbox, monkeypatch, capsys):
    (inbox / "meeting_gone.mov").write_bytes(b"g")
    monkeypatch.setattr(vmp, "process", lambda p, k, c: inbox / "f")  # archives, but the row is later deleted
    assert vmp.archive_recording("meeting_gone") == 0
    assert vmp.archive_recording("meeting_gone") == vmp.EXIT_NO_INPUT
    assert "no Recording" in capsys.readouterr().err


def test_archived_and_inbox_file_gone_is_success(inbox):
    _archived_row("meeting_moved")
    assert vmp.archive_recording("meeting_moved") == 0


def test_corrupted_audio_is_permanent_and_stays_so_on_retry(inbox, monkeypatch):
    (inbox / "meeting_bad.mov").write_bytes(b"bad")

    def corrupt(path, key, config):
        raise RuntimeError("Failed to probe audio: moov atom not found")

    monkeypatch.setattr(vmp, "process", corrupt)
    assert vmp.archive_recording("meeting_bad") == vmp.EXIT_CORRUPTED
    assert not (inbox / "meeting_bad.mov").exists()  # quarantined
    assert vmp.archive_recording("meeting_bad") == vmp.EXIT_CORRUPTED


def test_other_inbox_files_are_left_alone(inbox, monkeypatch):
    (inbox / "meeting_a.mov").write_bytes(b"a")
    old = inbox / "meeting_b.mov"
    old.write_bytes(b"b")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    seen = []
    monkeypatch.setattr(vmp, "process", lambda p, k, c: seen.append(p.name) or inbox / "f")
    assert vmp.archive_recording("meeting_a") == 0
    assert seen == ["meeting_a.mov"]


def test_source_still_changing_is_temporary_failure(inbox, monkeypatch):
    (inbox / "meeting_c.mov").write_bytes(b"c")

    def not_ready(path, key, config):
        raise vmp.SourceNotReady("changed")

    monkeypatch.setattr(vmp, "process", not_ready)
    assert vmp.archive_recording("meeting_c") == vmp.EXIT_TEMPFAIL


def test_other_error_is_failure(inbox, monkeypatch):
    (inbox / "meeting_d.mov").write_bytes(b"d")

    def boom(path, key, config):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(vmp, "process", boom)
    assert vmp.archive_recording("meeting_d") == 1


def test_unsafe_id_is_rejected(inbox):
    assert vmp.archive_recording("../etc/passwd") == vmp.EXIT_USAGE


def test_continuation_of_a_live_id_resolves_to_its_archived_recording():
    db.create_recording(
        recording_id="2026-11-01_09-00-00_meeting_root_abcd1234",
        folder_path="/tmp/x",
        title="t",
        recorded_at="2026-11-01T09:00:00+00:00",
        duration_seconds=1.0,
        size_bytes=1,
        metadata={"live_recording_id": "meeting_root"},
    )
    assert vmp.resolve_continues_id("meeting_root") == "2026-11-01_09-00-00_meeting_root_abcd1234"
    # An already-archived id (detail page "Continue meeting") passes through.
    assert vmp.resolve_continues_id("2026-10-30_rec_abc") == "2026-10-30_rec_abc"
