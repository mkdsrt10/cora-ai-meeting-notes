"""Hosted transcription is opt-in: default stays local, lockdown forces local,
and runaway cloud output is dropped rather than becoming a transcript."""
import db
import pipeline.config as pcfg
from pipeline import cloud_asr, transcribe


def test_defaults_to_local():
    assert cloud_asr.engine() == "local"


def test_selected_engine_and_lockdown_override(monkeypatch):
    db.set_setting("transcription_engine", "gemini")
    try:
        assert cloud_asr.engine() == "gemini"
        monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
        assert cloud_asr.engine() == "local"
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


def test_runaway_output_is_dropped():
    assert cloud_asr._clip_result(" ".join(f"w{i}" for i in range(400)), duration=5.0)["segments"] == []


def test_repetition_loop_is_collapsed_not_kept():
    assert cloud_asr._clip_result("the " * 50, duration=10.0)["text"] == "the"


def test_normal_output_becomes_one_segment():
    result = cloud_asr._clip_result("haan toh we can ship it", duration=4.0)
    assert result["segments"] == [{"start": 0.0, "end": 4.0, "text": "haan toh we can ship it"}]


def test_chunk_dispatch_uses_selected_engine(monkeypatch, tmp_path):
    clip = tmp_path / "c.wav"
    clip.write_bytes(b"x")
    monkeypatch.setattr(transcribe, "transcribe_local_mlx", lambda c, prompt="": {"text": "local", "segments": []})
    monkeypatch.setattr(cloud_asr, "transcribe_clip", lambda c, prompt="": {"text": "cloud", "segments": []})
    assert transcribe._transcribe_clip(clip, "")["text"] == "local"
    monkeypatch.setattr(cloud_asr, "engine", lambda: "gemini")
    assert transcribe._transcribe_clip(clip, "")["text"] == "cloud"
