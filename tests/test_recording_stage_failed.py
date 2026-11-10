"""A Recording whose last processing run ended in an error shows the
"Processing failed" Stage with the plain-language reason, on the dashboard
and the detail page, until a later run succeeds."""
import json

import pytest

import db
import paths
import recording_stage
from api import views
from pipeline import errors

PROFILE = {"mode": "cloud", "provider": "openai", "transcription": "gemini"}


def _recording(name, monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    db.create_recording(name, str(folder), name, "2026-11-10T15:50:00+00:00", 1.0, 1, {"live_recording_id": f"live-{name}"})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "You")
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."}]
    fake_text.reply = lambda prompt, trace, **kw: "general" if trace == "template.select" else json.dumps(dict(
        title="Sync", overview="Deck.", action_items_md="- Send the deck", decisions_md="- None noted.",
        timeline_md="- Deck", open_questions_md="- None noted.", key_entities_md="- Deck"))
    return folder


def _transcription_fails(monkeypatch, exc):
    from pipeline import transcriber

    class Failing(transcriber.FakeTranscriber):
        def transcribe(self, audio_path, **kwargs):
            raise exc
    monkeypatch.setattr(transcriber, "_make", lambda profile: Failing([]))


def _fail(name, monkeypatch, fake_text, fake_transcriber, exc=None):
    from pipeline import runner
    folder = _recording(name, monkeypatch, fake_text, fake_transcriber)
    _transcription_fails(monkeypatch, exc or errors.ProviderAuthError("gemini"))
    with pytest.raises(errors.ProcessingError):
        runner.process_recording_local(folder, PROFILE)
    return folder


def test_failed_run_shows_processing_failed_with_the_reason(monkeypatch, fake_text, fake_transcriber):
    _fail("failed-auth", monkeypatch, fake_text, fake_transcriber)
    rec = db.get_recording("failed-auth")
    assert recording_stage.stage(rec) == "failed"
    assert recording_stage.labels()["failed"] == "Processing failed"
    failure = rec["metadata"]["processing_failure"]
    assert failure["code"] == "provider_auth"
    assert failure["message"] == str(errors.ProviderAuthError("gemini"))
    assert failure["at"]


def test_a_later_successful_run_clears_the_failure(monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner, transcriber
    folder = _fail("failed-then-ok", monkeypatch, fake_text, fake_transcriber)
    monkeypatch.setattr(transcriber, "_make", lambda profile: transcriber.FakeTranscriber(
        [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."}]))
    runner.process_recording_local(folder, PROFILE)
    rec = db.get_recording("failed-then-ok")
    assert "processing_failure" not in rec["metadata"]
    assert recording_stage.stage(rec) != "failed"
    assert "failure" not in views.recording_item(rec)


def test_dashboard_lists_a_failed_recording_with_its_failure(monkeypatch, fake_text, fake_transcriber):
    folder = _fail("failed-listed", monkeypatch, fake_text, fake_transcriber)
    # Audio gone (e.g. never archived): an unprocessed Recording would be hidden,
    # a failed one must still be shown so it can be retried.
    (folder / "audio.wav").unlink()
    item = next((r for r in views.all_recordings() if r["id"] == "failed-listed"), None)
    assert item is not None
    assert item["analysis_stage"] == "failed"
    assert item["failure"] == {"code": "provider_auth", "message": str(errors.ProviderAuthError("gemini"))}
    assert views.recording_item(folder, detailed=True)["failure"]["code"] == "provider_auth"


def test_retry_reruns_processing_and_leaves_the_failed_stage(monkeypatch, fake_text, fake_transcriber):
    from api.routes import recordings
    from pipeline import transcriber
    _fail("failed-retry", monkeypatch, fake_text, fake_transcriber)
    monkeypatch.setattr(transcriber, "_make", lambda profile: transcriber.FakeTranscriber(
        [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."}]))

    class Req:
        def send_json(self, payload, status=200):
            self.payload, self.status = payload, status
    req = Req()
    recordings.post_api_process_recording(req, "/api/process-recording", {"id": "failed-retry"})
    assert req.status == 200, req.payload
    assert recording_stage.stage(db.get_recording("failed-retry")) != "failed"


def test_queue_retry_by_live_id_still_finds_a_failed_recording(monkeypatch, fake_text, fake_transcriber):
    _fail("failed-live", monkeypatch, fake_text, fake_transcriber, errors.ProviderUnavailableError("gemini"))
    assert db.get_recording("failed-live")["metadata"]["processing_failure"]["code"] == "provider_unavailable"
    assert db.get_recording_by_live_id("live-failed-live")["id"] == "failed-live"
