"""POST /api/process-recording tells the Processing queue whether a failure is
permanent or worth retrying: {"error", "code", "retryable"} with a plain
message that never carries meeting content or a provider's response body.
Every exception is mapped in one place (api.processing_errors.classify)."""
import sys
import types

import pytest

import db
import paths
import policy
import processing
from api import processing_errors
from api.routes import recordings
from pipeline import errors
from pipeline import text_model as tm

SECRET = "TRANSCRIPT: Priya said the merger closes Friday"


class _Req:
    def send_json(self, payload, status=200):
        self.payload, self.status = payload, status


class HttpError(Exception):
    """A requests-style HTTP error carrying a provider body."""

    def __init__(self, status):
        super().__init__(f"{status} {SECRET}")
        self.response = types.SimpleNamespace(status_code=status, text=SECRET)


def _caused(outer, inner):
    try:
        raise outer from inner
    except Exception as exc:
        return exc


@pytest.mark.parametrize("exc, code, retryable, status", [
    (errors.NoAudioError(), "no_audio", False, 404),
    (errors.CorruptedAudioError(), "corrupted_audio", False, 422),
    (errors.ProviderAuthError("openai"), "provider_auth", False, 502),
    (errors.ProviderNotConfiguredError("custom"), "provider_not_configured", False, 412),
    (policy.LockdownError(SECRET), "lockdown", False, 403),
    (ImportError("No module named 'mlx_whisper'", name="mlx_whisper"), "missing_dependency", False, 501),
    (errors.MissingDependencyError("ffprobe"), "missing_dependency", False, 501),
    (errors.ProviderUnavailableError("anthropic"), "provider_unavailable", True, 503),
    (processing.ProcessingBusyError(), "busy", True, 409),
    (RuntimeError(SECRET), "internal", True, 500),
    (HttpError(401), "provider_auth", False, 502),
    (HttpError(403), "provider_auth", False, 502),
    (HttpError(429), "provider_unavailable", True, 503),
    (HttpError(503), "provider_unavailable", True, 503),
    (_caused(RuntimeError(SECRET), errors.ProviderAuthError("gemini")), "provider_auth", False, 502),
    (errors.WindowedTranscriptionError("gemini"), "cloud_transcription_rejected", False, 422),
    (_caused(RuntimeError(SECRET), errors.WindowedTranscriptionError("gemini")), "cloud_transcription_rejected", False, 422),
])
def test_each_failure_maps_to_one_code(exc, code, retryable, status):
    got_status, body = processing_errors.classify(exc)
    assert (body["code"], body["retryable"], got_status) == (code, retryable, status)
    assert set(body) == {"error", "code", "retryable"}
    assert SECRET not in body["error"] and "Priya" not in body["error"]


def test_auth_message_names_the_provider_and_settings():
    _, body = processing_errors.classify(errors.ProviderAuthError("anthropic"))
    assert "Anthropic" in body["error"] and "Settings" in body["error"]


def test_windowed_failure_has_a_plain_message_and_keeps_its_old_name():
    from pipeline import windowed
    _, body = processing_errors.classify(windowed.WindowedASRError("gemini"))
    assert body["error"] == ("The cloud transcription engine rejected part of this recording "
                             "and no local model was available to fill in.")
    assert body["code"] == "cloud_transcription_rejected" and body["retryable"] is False


def _folder(name):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _route(monkeypatch, rec_id, process):
    monkeypatch.setitem(sys.modules, "local_meeting_pipeline", types.SimpleNamespace(process_recording_local=process))
    req = _Req()
    recordings.post_api_process_recording(req, "/api/process-recording", {"id": rec_id})
    return req


def test_route_reports_provider_auth_without_provider_body(monkeypatch):
    _folder("err-auth")

    def fail(folder):
        raise errors.ProviderAuthError("openai") from HttpError(401)
    req = _route(monkeypatch, "err-auth", fail)
    assert req.status == 502
    assert req.payload["code"] == "provider_auth" and req.payload["retryable"] is False
    assert SECRET not in req.payload["error"]


def test_route_reports_missing_recording_as_no_audio(monkeypatch):
    req = _route(monkeypatch, "err-no-such-recording", lambda f: pytest.fail("should not process"))
    assert (req.status, req.payload["code"], req.payload["retryable"]) == (404, "no_audio", False)


def test_route_reports_busy_lock_as_retryable(monkeypatch):
    _folder("err-busy")

    def busy(folder):
        raise processing.ProcessingBusyError()
    req = _route(monkeypatch, "err-busy", busy)
    assert (req.status, req.payload["code"], req.payload["retryable"]) == (409, "busy", True)


def test_success_names_the_recording_holding_the_result(monkeypatch):
    _folder("err-child")
    req = _route(monkeypatch, "err-child", lambda f: {"recording_id": "err-parent", "diarization": {},
                                                      "speaker_profiles": [], "call_summary": {}})
    assert req.status == 200
    assert req.payload["ok"] is True and req.payload["recording_id"] == "err-parent"


def test_success_without_merge_names_the_recording_itself(monkeypatch):
    _folder("err-plain")
    req = _route(monkeypatch, "err-plain", lambda f: {"diarization": {}, "speaker_profiles": [], "call_summary": {}})
    assert req.payload["recording_id"] == "err-plain"


def test_busy_lock_raises_typed_error():
    profile = processing.validate({})
    with processing.scope(profile):
        with pytest.raises(processing.ProcessingBusyError):
            with processing.scope(profile):
                pass


# ---- adapters raise typed provider errors, without response bodies --------------

@pytest.fixture
def posts(monkeypatch):
    import credentials
    import requests
    replies = []

    class Response:
        def __init__(self, status):
            self.status_code = status
            self.text = SECRET

        def raise_for_status(self):
            raise requests.HTTPError(f"{self.status_code} {SECRET}", response=self)

    def post(url, **kwargs):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Response(reply)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(tm, "_sleep", lambda s: None)
    monkeypatch.setattr(credentials, "provider_settings", lambda name: {"api_key": "k"})
    return replies


def test_text_model_401_is_provider_auth(posts):
    posts.append(401)
    with pytest.raises(errors.ProviderAuthError) as info:
        tm.text_model({"provider": "openai", "model": ""}).complete("x")
    assert SECRET not in str(info.value) and "OpenAI" in str(info.value)


def test_text_model_exhausted_retries_are_provider_unavailable(posts):
    import requests
    posts.extend([503, requests.ConnectionError(SECRET), 429])
    with pytest.raises(errors.ProviderUnavailableError) as info:
        tm.text_model({"provider": "groq", "model": ""}).complete("x")
    assert SECRET not in str(info.value)


def test_missing_key_is_provider_auth(monkeypatch):
    import credentials
    monkeypatch.setattr(credentials, "provider_settings", lambda name: {})
    with pytest.raises(errors.ProviderAuthError):
        tm.text_model({"provider": "anthropic", "model": ""}).complete("x")


def test_hosted_transcription_401_is_provider_auth(posts, tmp_path):
    from pipeline.transcriber import OpenAICompatibleAudio
    clip = tmp_path / "clip.flac"
    clip.write_bytes(b"")
    posts.append(401)
    with pytest.raises(errors.ProviderAuthError):
        OpenAICompatibleAudio("https://api.openai.com/v1", "k", "whisper-1").window(clip, 3.0, "")


def test_gemini_transcription_403_is_provider_auth_and_not_retried(tmp_path):
    pytest.importorskip("google.genai")
    from pipeline import gemini_asr
    calls = []

    class Denied(Exception):
        code = 403

    def generate(**kwargs):
        calls.append(1)
        raise Denied(SECRET)
    client = types.SimpleNamespace(models=types.SimpleNamespace(generate_content=generate))
    clip = tmp_path / "clip.flac"
    clip.write_bytes(b"")
    with pytest.raises(errors.ProviderAuthError):
        gemini_asr.transcribe_window(clip, 3.0, "c", client=client, model="m")
    assert len(calls) == 1


def test_recording_without_audio_is_no_audio():
    from pipeline import runner
    folder = _folder("err-empty-folder")
    with pytest.raises(errors.NoAudioError):
        runner.process_recording_local(folder, {"mode": "local_light"})


@pytest.mark.skipif(not __import__("shutil").which("ffprobe"), reason="needs ffprobe")
def test_unreadable_audio_is_corrupted(tmp_path):
    from pipeline import audio
    bad = tmp_path / "audio.mov"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(errors.CorruptedAudioError):
        audio.probe_duration(bad)
