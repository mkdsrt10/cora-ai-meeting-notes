"""Cloud live (docs/specs/live-transcript.md, T5), against a fake stream: no
call to Google, no credentials, no audio leaves the test. Refused under
lockdown and off the Vertex backend, hidden on AI Studio and (by default) in
the Team build, never swapped for the on-device engine, and a stream rotated
with overlap keeps one clean record."""
import array
import http.client
import io
import json
import threading
from types import SimpleNamespace as NS

import pytest

import credentials
import db
import live_cloud
import paths
import server
from api import auth

TOKEN = "live-cloud-test-token"
VERTEX = {"provider": "vertex", "vertex_project": "fictional-project", "vertex_location": "us-central1",
          "vertex_auth_type": "adc"}
AI_STUDIO = {"provider": "ai_studio", "vertex_project": "", "vertex_location": "global", "vertex_auth_type": "adc"}


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


@pytest.fixture
def backend(monkeypatch):
    paths.ensure_data_dir()
    db.init_db()
    db.set_setting("processing_preferences", None)
    state = {"status": dict(VERTEX)}
    monkeypatch.setattr(credentials, "get_public_status", lambda: dict(state["status"]))
    monkeypatch.delenv("VOICECOACH_ENTERPRISE_LOCKDOWN", raising=False)
    monkeypatch.delenv("CORA_BUILD_VARIANT", raising=False)
    yield state
    db.set_setting("processing_preferences", None)


@pytest.fixture
def config():
    previous = paths.CONFIG_PATH.read_text() if paths.CONFIG_PATH.exists() else None

    def write(value):
        paths.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        paths.CONFIG_PATH.write_text(json.dumps(value))
    yield write
    if previous is None:
        paths.CONFIG_PATH.unlink(missing_ok=True)
    else:
        paths.CONFIG_PATH.write_text(previous)


def f32(seconds):
    return array.array("f", [0.01] * int(seconds * 16000)).tobytes()


# --- Gates ------------------------------------------------------------------------

def test_refused_under_lockdown_and_off_the_vertex_backend(backend, monkeypatch):
    assert live_cloud.refusal() is None
    backend["status"] = dict(AI_STUDIO)
    assert live_cloud.refusal() == "not_vertex"
    backend["status"] = dict(VERTEX, vertex_auth_type="api_key")
    assert live_cloud.refusal() == "auth_unsupported"
    backend["status"] = dict(VERTEX)
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert live_cloud.refusal() == "lockdown"


def test_lockdown_refusal_never_opens_a_stream(backend, monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    lines, opened = [], []
    code = live_cloud.run("mic", io.BytesIO(f32(1)), transport_factory=lambda: opened.append(1),
                          emit=lambda k, p: lines.append((k, p)))
    assert code == 5 and opened == []
    assert lines == [("LIVE_ERROR", {"track": "mic", "code": "lockdown"})]


def test_settings_offer_cloud_only_on_vertex_and_not_by_default_in_the_team_build(port, backend, monkeypatch, config):
    import processing
    monkeypatch.setattr(processing, "live_hinglish_refusal", lambda: "model_missing")   # independent of this Mac
    assert "cloud_vertex" in call(port, "GET", "/api/processing")[1]["live"]["offered"]
    backend["status"] = dict(AI_STUDIO)
    offered = call(port, "GET", "/api/processing")[1]["live"]
    assert offered["offered"] == ["off", "on_device"] and "Cloud" not in offered["note"]
    status, body = call(port, "POST", "/api/processing", {"mode": "local_light", "live": "cloud_vertex"})
    assert status == 400 and "Vertex" in body["error"]
    backend["status"] = dict(VERTEX)
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    assert "cloud_vertex" not in call(port, "GET", "/api/processing")[1]["live"]["offered"]
    config({"live_cloud_offered": True})
    assert "cloud_vertex" in call(port, "GET", "/api/processing")[1]["live"]["offered"]
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert call(port, "GET", "/api/processing")[1]["live"]["offered"] == ["off", "on_device"]
    assert call(port, "POST", "/api/processing", {"mode": "local_light", "live": "cloud_vertex"})[0] == 403


def test_live_settings_report_a_refused_cloud_engine_without_switching(port, backend, monkeypatch):
    assert call(port, "POST", "/api/processing", {"mode": "local_light", "live": "cloud_vertex"})[0] == 200
    assert call(port, "GET", "/api/live/settings")[1] == {"mode": "cloud_vertex", "refused": None}
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    # still cloud, refused: Electron pauses captions; it never runs on-device instead
    assert call(port, "GET", "/api/live/settings")[1] == {"mode": "cloud_vertex", "refused": "lockdown"}


# --- The stream ---------------------------------------------------------------------

def result(text, end, final):
    return NS(results=[NS(alternatives=[NS(transcript=text)], is_final=final, result_end_offset=end)])


class FakeStreams:
    """Each stream gets scripted responses, released once enough audio arrived
    (stream-relative seconds); records the bytes each stream received."""

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.received = []

    def __call__(self):
        script = self.scripts.pop(0) if self.scripts else []
        got = bytearray()
        self.received.append(got)
        cond = threading.Condition()
        closed = [False]

        def send(chunk):
            with cond:
                if chunk is None:
                    closed[0] = True
                else:
                    got.extend(chunk)
                cond.notify_all()

        def responses():
            for at, response in script:
                with cond:
                    cond.wait_for(lambda: len(got) / 2 / 16000 >= at or closed[0], timeout=5)
                yield response
        return send, responses()


def run_engine(streams, seconds, **kwargs):
    lines = []
    engine = live_cloud.CloudLive("sys", streams, lambda k, p: lines.append((k, p)), **kwargs)
    for _ in range(int(seconds * 10)):
        engine.feed(f32(0.1))
    engine.finish(timeout=5)
    return engine, lines


def test_partials_are_stabilized_and_finals_never_retract():
    streams = FakeStreams([[
        (0.5, result("we ship f", 0.5, False)),
        (0.7, result("we ship f", 0.7, False)),
        (0.9, result("we ship Friday", 0.9, False)),
        (1.0, result("We ship on Friday.", 1.0, True)),
        (1.4, result("blue lanterns", 1.4, False)),
        (1.6, result("blue lanterns arrive", 1.6, False)),
        (1.8, result("Green lamps arrived.", 1.8, True)),
    ]])
    engine, lines = run_engine(streams, 2.0)
    texts = [(k, p["text"]) for k, p in lines]
    assert texts == [("LIVE_PARTIAL", "we ship"), ("LIVE_FINAL", "We ship on Friday."),
                     ("LIVE_PARTIAL", "blue lanterns"), ("LIVE_FINAL", "blue lanterns arrived.")]
    finals = [p for k, p in lines if k == "LIVE_FINAL"]
    assert finals[1]["start"] >= finals[0]["end"] and all(p["track"] == "sys" for _, p in lines)


def test_stream_rotates_before_the_limit_with_overlap_and_no_duplicates():
    # stream 1 covers 0-1 s; stream 2 starts 0.5 s back (overlap) and repeats the last final
    streams = FakeStreams([
        [(0.9, result("First part.", 0.9, True))],
        [(0.4, result("First part.", 0.4, True)),      # 0.5 + 0.4 = 0.9: already final, dropped
         (0.8, result("Second part.", 0.8, True))],    # 0.5 + 0.8 = 1.3
    ])
    engine, lines = run_engine(streams, 1.4, stream_limit=1.0, overlap=0.5)
    assert engine.streams == 2 and not engine.failed
    finals = [(p["text"], p["end"]) for k, p in lines if k == "LIVE_FINAL"]
    assert finals == [("First part.", 0.9), ("Second part.", 1.3)]
    # the second stream began with the overlap audio again
    assert len(streams.received[1]) >= int(0.5 * 16000) * 2


def test_a_failed_stream_pauses_the_track_and_never_switches_engine():
    def broken():
        raise RuntimeError("network down")
    lines = []
    engine = live_cloud.CloudLive("mic", broken, lambda k, p: lines.append((k, p)))
    engine.feed(f32(0.1))
    engine.feed(f32(0.1))
    assert lines == [("LIVE_ERROR", {"track": "mic", "code": "stream_open_failed"})]
    assert engine.failed == "stream_open_failed"


def test_missing_sdk_or_credentials_is_an_error_line_not_a_fallback(backend):
    lines = []

    def no_sdk():
        raise ImportError("google.cloud.speech_v2")
    code = live_cloud.run("sys", io.BytesIO(f32(0.2)), transport_factory=no_sdk, emit=lambda k, p: lines.append((k, p)))
    assert code == 5
    assert lines == [("LIVE_ERROR", {"track": "sys", "code": "cloud_unavailable_importerror"})]


def test_google_transport_builds_a_chirp_stream_on_the_vertex_region(backend, monkeypatch, config):
    """The real adapter's requests, captured before anything is sent."""
    pytest.importorskip("google.cloud.speech_v2")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import speech_v2
    config({"live_cloud_languages": ["en-IN", "hi-IN"]})
    monkeypatch.setattr(live_cloud, "vertex_credentials", lambda: AnonymousCredentials())
    seen = {}

    def capture(self, requests, **kwargs):
        seen["endpoint"] = self._transport._host
        seen["requests"] = requests
        return iter(())
    monkeypatch.setattr(speech_v2.SpeechClient, "streaming_recognize", capture)
    send, _ = live_cloud.google_transport()()
    send(b"\0\0" * 1600)
    send(None)
    first, audio = list(seen["requests"])
    assert seen["endpoint"].startswith("us-central1-speech.googleapis.com")
    assert first.recognizer == "projects/fictional-project/locations/us-central1/recognizers/_"
    config_ = first.streaming_config.config
    assert config_.model == "chirp_2" and list(config_.language_codes) == ["en-IN", "hi-IN"]
    assert config_.explicit_decoding_config.sample_rate_hertz == 16000
    assert first.streaming_config.streaming_features.interim_results is True
    assert len(audio.audio) == 3200


def test_region_falls_back_from_global_to_a_chirp_region(config):
    assert live_cloud.region("europe-west4") == "europe-west4"
    assert live_cloud.region("global") == "us-central1"
    config({"live_cloud_location": "asia-southeast1"})
    assert live_cloud.region("global") == "asia-southeast1"
