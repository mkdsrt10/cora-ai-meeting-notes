"""Transcriber: one interface for every speech-to-text call.

transcriber(profile).transcribe(audio, ...) -> (segments, duration, speech_s).
The engine comes from the Processing profile; hosted engines share the
windowed retry/split/validate ladder (see test_gemini_asr.py for that)."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import credentials
import policy
from pipeline import transcriber as asr


def test_engines_come_from_the_module():
    import processing
    assert asr.ENGINES == ("local", "gemini", "openai_compatible")
    for engine in asr.ENGINES:
        assert processing.validate({"transcription": engine})["transcription"] == engine
    with pytest.raises(ValueError):
        processing.validate({"transcription": "whisper.cpp"})


def test_engine_and_model_come_from_the_profile(monkeypatch):
    import db
    monkeypatch.setattr(db, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(credentials, "get_public_status", lambda: {"provider": "ai_studio"})
    monkeypatch.setattr(credentials, "provider_settings", lambda name: {"api_key": "k", "base_url": "", "model": ""})
    assert asr.transcriber({"transcription": "local"}).engine == "local"
    gemini = asr.transcriber({"transcription": "gemini", "provider": "anthropic"})
    assert gemini.engine == "gemini" and gemini.model.startswith("gemini-")
    # Audio goes to the profile's own OpenAI-compatible endpoint, never a second provider.
    groq = asr.transcriber({"transcription": "openai_compatible", "provider": "groq"})
    assert (groq.engine, groq.model) == ("openai_compatible", "whisper-large-v3")
    assert asr.transcriber({"transcription": "openai_compatible", "provider": "gemini"}).model == "whisper-1"


def test_lockdown_blocks_hosted_audio_but_allows_a_local_endpoint(monkeypatch):
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    urls = {"openai": "", "custom": "http://127.0.0.1:8080/v1"}
    monkeypatch.setattr(credentials, "provider_settings", lambda name: {"api_key": "", "base_url": urls.get(name, ""), "model": ""})
    for profile in ({"transcription": "gemini"}, {"transcription": "openai_compatible", "provider": "openai"}):
        with pytest.raises(policy.LockdownError):
            asr.transcriber(profile)
    assert asr.transcriber({"transcription": "openai_compatible", "provider": "custom"}).engine == "openai_compatible"
    assert asr.transcriber({"transcription": "local"}).engine == "local"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_openai_compatible_audio_request_shape(tmp_path, monkeypatch):
    import requests
    audio = tmp_path / "audio.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=20",
                    "-ac", "1", "-ar", "16000", str(audio)], check=True)
    monkeypatch.setattr(credentials, "provider_settings",
                        lambda name: {"api_key": "sk-test", "base_url": "https://api.example.com/v1", "model": ""})
    calls = []

    def post(url, headers=None, data=None, files=None, timeout=None, **kwargs):
        calls.append(dict(url=url, headers=headers, data=data, files=files))
        payload = {"text": "hello there", "segments": [{"start": 0.0, "end": 19.0, "text": " hello there team"}]}
        return SimpleNamespace(status_code=200, json=lambda: payload, raise_for_status=lambda: None)
    monkeypatch.setattr(requests, "post", post)
    from pipeline.context import MeetingContext
    segments, duration, speech = asr.transcriber({"transcription": "openai_compatible", "provider": "openai"}).transcribe(
        audio, context=MeetingContext(title="Weekly sync", attendees=["Priya Shah"]))
    assert round(duration) == 20 and speech > 0
    assert [s["text"] for s in segments] == ["hello there team"]
    call = calls[0]
    assert call["url"] == "https://api.example.com/v1/audio/transcriptions"
    assert call["headers"] == {"Authorization": "Bearer sk-test"}
    assert call["data"]["model"] == "whisper-1" and call["data"]["response_format"] == "verbose_json"
    assert "Priya Shah" in call["data"]["prompt"] and "<context>" not in call["data"]["prompt"]
    assert call["files"]["file"][0].endswith(".flac")


def test_openai_compatible_audio_errors_split_retryable_from_fatal(tmp_path, monkeypatch):
    import requests
    from pipeline.gemini_asr import AsrCallError
    clip = tmp_path / "c.flac"
    clip.write_bytes(b"fLaC")
    replies = []

    def post(url, **kwargs):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(requests, "post", post)
    call = asr.OpenAICompatibleAudio("https://api.example.com/v1", "k", "whisper-1").window

    def status(code):
        def raise_for_status():
            raise requests.HTTPError(f"{code}", response=SimpleNamespace(status_code=code))
        return SimpleNamespace(status_code=code, raise_for_status=raise_for_status)
    replies.extend([status(429), requests.ConnectionError("reset"), status(401)])
    with pytest.raises(AsrCallError):
        call(clip, 3.0, "ctx")
    with pytest.raises(AsrCallError):
        call(clip, 3.0, "ctx")
    with pytest.raises(requests.HTTPError):
        call(clip, 3.0, "ctx")


def test_runner_runs_one_profile_through_fake_models(fake_text, fake_transcriber, monkeypatch):
    """The whole local pipeline with fake adapters: one profile decides the
    transcription engine and the single text provider for every text pass."""
    import db
    import paths
    from pipeline import runner
    folder = paths.RECORDINGS_DIR / "fake-run"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    (folder / "participants.json").write_text(json.dumps(["Jane Doe", "Priya Shah", "Rahul Mehta"]))
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "Participant")
    db.set_setting("pending_self_name", "Jane Doe")
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "ठीक है, शुरू करते हैं"},
                                 {"start": 3.0, "end": 6.0, "text": "Hi everyone, this is Rahul from finance."}]

    def reply(prompt, trace, **kwargs):
        if trace == "romanize":
            return "[0] theek hai, shuru karte hain"
        if trace == "template.select":
            return "general"
        return json.dumps(dict(title="Kickoff", overview="Rahul joined.", action_items_md="- None noted.",
                               decisions_md="- None noted.", timeline_md="- Intro", open_questions_md="- None noted.",
                               key_entities_md="- Rahul"))
    fake_text.reply = reply
    try:
        result = runner.process_recording_local(folder, {"mode": "cloud", "provider": "openai", "transcription": "gemini"})
    finally:
        db.set_setting("pending_self_name", "")
    segments = result["diarization"]["segments"]
    assert segments[0]["text"] == "theek hai, shuru karte hain"
    assert segments[1]["speaker_name"] == "Rahul Mehta"
    assert {c["trace"] for c in fake_text.calls} >= {"romanize", "template.select", "notes.chunk.0"}
    assert result["call_summary"]["model"] == "saved-openai"
    assert result["diarization"]["model"].startswith("cloud-asr:gemini")
    assert "sent to openai" in result["diarization"]["privacy_note"]
    assert fake_transcriber.profiles and all(p["transcription"] == "gemini" and p["provider"] == "openai"
                                             for p in fake_transcriber.profiles)
