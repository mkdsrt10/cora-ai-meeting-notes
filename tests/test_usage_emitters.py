"""Usage events written by the Python side: processing_finished once per
processing run, built from the trace run row and the resource-usage entry,
and the daily people_snapshot at server start."""
import datetime as dt
import json

import pytest

import db
import paths
import usage_events
import usage_emitters
from pipeline import errors

PROFILE = {"mode": "cloud", "provider": "openai", "transcription": "gemini"}


def _events(tmp_path, name):
    out = usage_events.export_jsonl(tmp_path / "export.jsonl")
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    return [r["payload"] for r in rows if r["name"] == name]


@pytest.fixture(autouse=True)
def _clean_events():
    db.init_db()
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.commit()


def _recording(name, monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    paths.ensure_data_dir()
    folder = paths.RECORDINGS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    db.delete_recording(name)
    db.create_recording(name, str(folder), name, "2026-11-10T15:50:00+00:00", 1.0, 1, {})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "You")
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "Send the deck by Friday."},
                                 {"start": 5.0, "end": 9.0, "text": "And the budget.", "engine": "local",
                                  "reason": "the cloud engine refused this stretch"}]
    fake_text.reply = lambda prompt, trace, **kw: "general" if trace == "template.select" else json.dumps(dict(
        title="Sync", overview="Deck.", action_items_md="- Send the deck", decisions_md="- None noted.",
        timeline_md="- Deck", open_questions_md="- None noted.", key_entities_md="- Deck"))
    return folder


def test_a_finished_run_records_one_processing_finished_from_the_run_and_resource_usage(
        tmp_path, monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("beta-ok", monkeypatch, fake_text, fake_transcriber)
    runner.process_recording_local(folder, PROFILE)

    [event] = _events(tmp_path, "processing_finished")
    assert set(event) == usage_events.CATALOG["processing_finished"]
    assert event["recording_id"] == "beta-ok"
    assert (event["status"], event["error_code"]) == ("ok", None)
    assert (event["transcriber_provider"], event["transcriber_model"]) == ("gemini", "fake")
    assert (event["text_provider"], event["text_model"]) == ("openai", "saved-openai")
    assert (event["duration_s"], event["speech_s"], event["silence_s"]) == (9.0, 9.0, 0.0)
    assert event["window_fallbacks"] == 1
    assert event["retries"] == 0
    assert event["total_s"] >= event["transcription_s"] >= 0
    assert event["summarization_s"] >= 0
    assert event["peak_rss_mb"] > 0
    assert event["tokens_in"] is None or event["tokens_in"] >= 0


def test_a_failed_run_records_one_processing_finished_with_the_error_code(
        tmp_path, monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner, transcriber
    folder = _recording("beta-failed", monkeypatch, fake_text, fake_transcriber)

    class Failing(transcriber.FakeTranscriber):
        def transcribe(self, audio_path, **kwargs):
            raise errors.ProviderAuthError("gemini")
    monkeypatch.setattr(transcriber, "_make", lambda profile: Failing([]))
    with pytest.raises(errors.ProcessingError):
        runner.process_recording_local(folder, PROFILE)

    [event] = _events(tmp_path, "processing_finished")
    assert (event["recording_id"], event["status"], event["error_code"]) == ("beta-failed", "error", "provider_auth")
    assert event["transcriber_provider"] == "gemini" and event["text_provider"] == "openai"
    assert event["total_s"] >= 0 and event["speech_s"] is None


def test_processing_finished_never_breaks_processing(tmp_path, monkeypatch, fake_text, fake_transcriber):
    from pipeline import runner
    folder = _recording("beta-store-down", monkeypatch, fake_text, fake_transcriber)

    def broken(name, payload):
        raise ValueError("unknown usage event")
    monkeypatch.setattr(usage_events, "record", broken)
    result = runner.process_recording_local(folder, PROFILE)
    assert result["recording_id"] == "beta-store-down"


# ---- people_snapshot ---------------------------------------------------------

def test_people_snapshot_is_recorded_at_start_when_none_was_taken(tmp_path):
    db.upsert_person("p-asha", "Asha Rao", "", "", [], 0, None, None, None, 0)
    paths.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    (paths.RECORDINGS_DIR / "blob.bin").write_bytes(b"x" * 3 * 1024 * 1024)
    assert usage_emitters.people_snapshot_if_due() is True
    [event] = _events(tmp_path, "people_snapshot")
    assert event["people"] == len(db.get_all_people()) >= 1
    assert event["recordings"] == len(db.get_all_recordings())
    assert event["disk_mb"] >= 3


def test_the_server_takes_the_snapshot_when_it_starts(tmp_path, monkeypatch):
    import server

    class FakeServer:
        def __init__(self, *args):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass
    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr("sys.argv", ["server.py", "--port", "0"])
    server.main()
    assert len(_events(tmp_path, "people_snapshot")) == 1


def test_people_snapshot_waits_24_hours_between_snapshots(tmp_path, monkeypatch):
    now = dt.datetime(2026, 11, 11, 9, 0, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(usage_events, "_now", lambda: now)
    assert usage_emitters.people_snapshot_if_due() is True
    monkeypatch.setattr(usage_events, "_now", lambda: now + dt.timedelta(hours=23))
    assert usage_emitters.people_snapshot_if_due() is False
    monkeypatch.setattr(usage_events, "_now", lambda: now + dt.timedelta(hours=24, minutes=1))
    assert usage_emitters.people_snapshot_if_due() is True
    assert len(_events(tmp_path, "people_snapshot")) == 2


def test_the_snapshot_is_taken_off_the_main_thread_after_the_port_is_bound(tmp_path, monkeypatch):
    import threading

    import server
    order = []

    class FakeServer:
        def __init__(self, *args):
            order.append("bound")

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass
    real = usage_emitters.people_snapshot_if_due

    def spy():
        order.append(("snapshot", threading.current_thread() is threading.main_thread()))
        return real()
    monkeypatch.setattr(usage_emitters, "people_snapshot_if_due", spy)
    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr("sys.argv", ["server.py", "--port", "0"])
    server.main()
    assert order == ["bound", ("snapshot", False)]
    assert len(_events(tmp_path, "people_snapshot")) == 1
