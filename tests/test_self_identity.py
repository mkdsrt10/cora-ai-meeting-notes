"""Who "You" is on a Recording. Cora captures your microphone as track 0 and
the call's audio as track 1, so on a dual-track Recording the pipeline knows
which speaker you are without asking: it writes `identity` with
confirmation_source "mic_track" and the Recording goes straight to Ready.
Only a single-track import still asks "Which speaker is you?". Existing
dual-track Recordings get the same identity once, at server start."""
import json

import pytest

import db
import paths
import recording_stage
from pipeline import speakers

PROFILE = {"mode": "cloud", "provider": "openai", "transcription": "gemini"}


@pytest.fixture(autouse=True)
def _fresh_db():
    paths.ensure_data_dir()
    db.init_db()
    with db.get_db() as conn:
        conn.execute("DELETE FROM recordings")
        conn.execute("DELETE FROM settings WHERE key IN ('pending_self_name', 'identity_backfill_mic_track_done')")
        conn.commit()


def _recording(name, monkeypatch, fake_text, fake_transcriber, *, tracks, turns):
    from pipeline import runner
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.mov").write_bytes(b"")
    db.create_recording(name, str(folder), name, "2026-11-13T10:00:00+00:00", 1.0, 1, {"live_recording_id": f"meeting_{name}"})
    monkeypatch.setattr(runner, "audio_stream_count", lambda path: tracks)
    who = iter(turns)
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: next(who))
    fake_transcriber.segments = [{"start": float(i * 3), "end": float(i * 3 + 2), "text": f"Line {i}."}
                                 for i in range(len(turns))]
    fake_text.reply = lambda prompt, trace, **kw: "general" if trace == "template.select" else json.dumps(dict(
        title="Sync", overview="Deck.", action_items_md="- Send the deck", decisions_md="- None noted.",
        timeline_md="- Deck", open_questions_md="- None noted.", key_entities_md="- Deck"))
    return folder


def test_a_dual_track_recording_reaches_ready_with_no_confirmation(monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("dual-1", monkeypatch, fake_text, fake_transcriber, tracks=2, turns=["You", "Participant", "You"])
    runner.process_recording_local(folder, PROFILE)

    rec = db.get_recording("dual-1")
    assert rec["identity"]["speaker_id"] == "You"
    assert rec["identity"]["confirmation_source"] == "mic_track"
    assert recording_stage.stage(rec) == "ready"
    assert rec["metadata"]["audio_tracks"] == 2


def test_the_self_speaker_is_found_under_your_onboarding_name(monkeypatch, fake_text, fake_transcriber):
    db.set_setting("pending_self_name", "Priya Shah")
    ids = ["Priya Shah", "Participant"]
    identity = speakers.mic_track_identity(ids, model="m")
    assert identity["speaker_id"] == "Priya Shah" and identity["identity"] == "Priya Shah"
    assert identity["confirmation_source"] == "mic_track"


def test_a_dual_track_recording_where_you_never_spoke_is_still_ready(monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("dual-silent", monkeypatch, fake_text, fake_transcriber, tracks=2, turns=["Participant"])
    runner.process_recording_local(folder, PROFILE)
    rec = db.get_recording("dual-silent")
    assert rec["identity"]["speaker_id"] is None
    assert recording_stage.stage(rec) == "ready"


def test_a_single_track_import_still_asks_which_speaker_is_you(monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("single-1", monkeypatch, fake_text, fake_transcriber, tracks=1, turns=["You", "You"])
    runner.process_recording_local(folder, PROFILE)
    rec = db.get_recording("single-1")
    assert not (rec["identity"] or {}).get("speaker_id")
    assert recording_stage.stage(rec) == "needs_speaker_confirmation"
    assert recording_stage.labels()["needs_speaker_confirmation"] == "Which speaker is you?"


def test_reprocessing_keeps_a_speaker_you_confirmed_yourself(monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("dual-manual", monkeypatch, fake_text, fake_transcriber, tracks=2, turns=["You", "Participant"])
    db.update_recording_data("dual-manual", "identity", {"identity": "Me", "speaker_id": "Participant",
                                                         "confirmation_source": "manual"})
    runner.process_recording_local(folder, PROFILE)
    assert db.get_recording("dual-manual")["identity"]["confirmation_source"] == "manual"


def _archived(name, *, speakers_, live_id, audio=True, identity=None):
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    if audio:
        (folder / "audio.mov").write_bytes(b"")
    db.create_recording(name, str(folder), name, "2026-11-01T10:00:00+00:00", 1.0, 1, {"live_recording_id": live_id})
    db.update_recording_data(name, "diarization", {"model": "m", "speakers": [{"speaker_id": s} for s in speakers_],
                                                   "segments": []})
    if identity:
        db.update_recording_data(name, "identity", identity)


def test_backfill_writes_identity_once_for_existing_dual_track_recordings(monkeypatch):
    tracks = {"old-dual": 2, "old-import": 1}
    monkeypatch.setattr(speakers, "audio_stream_count", lambda path: tracks[path.parent.name])
    _archived("old-dual", speakers_=["You", "Participant"], live_id="meeting_1")
    _archived("old-import", speakers_=["You"], live_id="Voice memo 3")
    _archived("old-pruned", speakers_=["You", "Asha"], live_id="meeting_2", audio=False)
    _archived("old-manual", speakers_=["You", "Asha"], live_id="meeting_3", audio=False,
              identity={"speaker_id": "Asha", "confirmation_source": "manual"})

    assert speakers.backfill_mic_track_identity() == 2
    assert db.get_recording("old-dual")["identity"]["speaker_id"] == "You"
    assert db.get_recording("old-pruned")["identity"]["confirmation_source"] == "mic_track"
    assert db.get_recording("old-manual")["identity"]["confirmation_source"] == "manual"
    assert recording_stage.stage(db.get_recording("old-import")) == "needs_speaker_confirmation"
    assert recording_stage.stage(db.get_recording("old-dual")) == "ready"

    db.update_recording_data("old-dual", "identity", {})
    assert speakers.backfill_mic_track_identity() == 0, "guarded by a settings flag: runs once"
    assert not db.get_recording("old-dual")["identity"]


def test_the_picker_route_confirms_which_speaker_is_you(monkeypatch):
    import diarization
    _archived("import-pick", speakers_=["You", "Speaker 2"], live_id="Voice memo 9")
    folder = paths.RECORDINGS_DIR / "import-pick"
    db.update_recording_data("import-pick", "diarization", {"model": "m", "speakers": [], "segments": [
        {"speaker_id": "Speaker 2", "start": "00:00", "end": "00:05", "text": "hello"}]})
    result = diarization.confirm_speaker(folder, "Speaker 2")
    assert result["speaker_id"] == "Speaker 2"
    assert recording_stage.stage(db.get_recording("import-pick")) == "ready"

