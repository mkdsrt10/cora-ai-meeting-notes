"""Export (GET /api/recording/export): one Recording as a Markdown file.
Driven over HTTP the way the renderer calls it; observations are the
response and its Markdown."""
import pytest
from test_beta_sender import api, port  # noqa: F401 - fixtures

RECORDING = "2026-11-12_13-15-57_meeting_export1"


@pytest.fixture
def recording():
    import db
    import paths
    folder = paths.RECORDINGS_DIR / RECORDING
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "enhanced_notes.md").write_text(
        "## Template: Standup\n\n## Overview\nShipping the export.\n\n## Action Items\n- Asha: write the docs\n")
    db.create_recording(RECORDING, str(folder), "Weekly sync: plan/review", "2026-11-12T13:15:57+05:30",
                        185.3, 0, {})
    db.update_recording_data(RECORDING, "diarization", {
        "speakers": [{"speaker_id": "You"}, {"speaker_id": "speaker_2"}],
        "segments": [{"start": "00:01", "end": "00:03", "speaker_id": "You", "text": "Hello."},
                     {"start": "00:04", "end": "00:06", "speaker_id": "speaker_2", "text": "Hi there."}]})
    db.update_recording_data(RECORDING, "speaker_labels", {"speakers": {"speaker_2": {"name": "Asha Rao"}}})
    db.update_recording_data(RECORDING, "identity", {"speaker_id": "You", "identity": "Mayank"})
    db.update_notes(RECORDING, "")
    yield RECORDING
    with db.get_db() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (RECORDING,))
        conn.commit()


def export(port, rec_id, transcript=False):
    return api(port, "GET", f"/api/recording/export?id={rec_id}&transcript={'1' if transcript else '0'}")


def test_notes_export_has_header_and_notes_without_internal_lines(recording, port):
    status, reply = export(port, recording)
    assert status == 200
    md = reply["markdown"]
    assert md.startswith("# Weekly sync: plan/review\n")
    assert "**Duration:** 3 min" in md
    assert "**Participants:** Mayank (Self), Asha Rao" in md
    assert "## Overview\nShipping the export." in md and "- Asha: write the docs" in md
    assert "Template:" not in md
    assert "## Transcript" not in md and "Hi there." not in md
    assert "## My notes" not in md and reply["notepad"] is False
    assert reply["filename"].endswith(" Weekly sync plan review.md")
    assert reply["filename"][:10].count("-") == 2


def test_notepad_text_is_added_as_my_notes(recording, port):
    import db
    db.update_notes(recording, "  Follow up on pricing.  ")
    status, reply = export(port, recording)
    assert status == 200 and reply["notepad"] is True
    assert reply["markdown"].rstrip().endswith("## My notes\n\nFollow up on pricing.")


def test_transcript_only_when_asked(recording, port):
    status, reply = export(port, recording, transcript=True)
    assert status == 200
    assert "## Transcript\n\n**[00:01] Mayank (Self):** Hello.\n\n**[00:04] Asha Rao:** Hi there." in reply["markdown"]


def test_transcript_refused_under_lockdown_notes_still_allowed(recording, port, monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    status, reply = export(port, recording, transcript=True)
    assert status == 403 and "lockdown" in reply["error"]
    status, reply = export(port, recording)
    assert status == 200 and "## Overview" in reply["markdown"]


def test_unknown_and_unsafe_ids(port):
    assert export(port, "no_such_recording")[0] == 404
    assert export(port, "..%2F..%2Fetc")[0] == 404


def test_recording_with_nothing_to_export_is_a_conflict(recording, port):
    import paths
    (paths.RECORDINGS_DIR / recording / "enhanced_notes.md").unlink()
    status, reply = export(port, recording)
    assert status == 409 and "no notes" in reply["error"]
