"""Hosted transcription is opt-in: default stays local, lockdown forces local,
and the recording says honestly where its audio went."""
import db
import processing
import pipeline.config as pcfg


def engine():
    return processing.resolve()["transcription"]


def test_defaults_to_local():
    assert engine() == "local"


def test_selected_engine_and_lockdown_override(monkeypatch):
    db.set_setting("transcription_engine", "gemini")
    try:
        assert engine() == "gemini"
        monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
        assert engine() == "local"
        assert pcfg.whisper_model_status()["engine"] == "local"
    finally:
        db.set_setting("transcription_engine", "local")


def test_cloud_engine_needs_no_local_weights():
    db.set_setting("transcription_engine", "gemini")
    try:
        status = pcfg.whisper_model_status()
        assert status["ready"] and status["engine"] == "gemini"
    finally:
        db.set_setting("transcription_engine", "local")


class _Req:
    def send_json(self, payload, status=200):
        self.payload, self.status = payload, status


def _route_with(monkeypatch, tmp_path, setting, engine_param=""):
    """Which path does POST /api/process-recording take for a given setting?"""
    import sys
    import types
    import paths
    from api.routes import recordings
    folder = paths.RECORDINGS_DIR / f"route_{setting}_{engine_param or 'none'}"
    folder.mkdir(parents=True, exist_ok=True)
    calls = []
    fake_local = types.SimpleNamespace(process_recording_local=lambda f: calls.append("local") or {
        "diarization": {}, "speaker_profiles": [], "call_summary": {}})
    monkeypatch.setitem(sys.modules, "local_meeting_pipeline", fake_local)
    monkeypatch.setattr(recordings, "gemini_diarize", lambda f, model=None: calls.append("whole_file_gemini") or {})
    monkeypatch.setattr(recordings, "speaker_profiles", lambda r: [])
    db.set_setting("transcription_engine", setting)
    try:
        recordings.post_api_process_recording(_Req(), "/api/process-recording", {"id": folder.name, "engine": engine_param})
    finally:
        db.set_setting("transcription_engine", "local")
    return calls


def test_private_setting_never_uploads(monkeypatch, tmp_path):
    # Regression: "On this Mac" saves "local", which used to route to whole-file Gemini.
    assert _route_with(monkeypatch, tmp_path, "local") == ["local"]


def test_gemini_setting_uses_chunked_pipeline_not_legacy_upload(monkeypatch, tmp_path):
    assert _route_with(monkeypatch, tmp_path, "gemini") == ["local"]


def test_explicit_legacy_request_still_reaches_whole_file_path(monkeypatch, tmp_path):
    assert _route_with(monkeypatch, tmp_path, "local", engine_param="gemini") == ["whole_file_gemini"]


def test_provenance_labels_are_honest(monkeypatch):
    import credentials
    from pipeline import runner
    monkeypatch.setattr(credentials, "get_public_status", lambda: {"provider": "ai_studio"})
    model, note = runner._provenance(processing.validate({}))
    assert model.startswith("local-mlx:") and "transcribed locally" in note and "generated locally" in note
    model, note = runner._provenance(processing.validate({"mode": "cloud"}))
    assert model.startswith("cloud-asr:gemini:gemini-") and "sent to Google Gemini" in note
    model, note = runner._provenance(processing.validate({"transcription": "openai_compatible", "provider": "openai"}))
    assert model == "cloud-asr:openai_compatible:whisper-1" and "OpenAI-compatible endpoint" in note
