"""A Recording offers to be processed in the cloud, once, never by itself:
when a stretch was left untranscribed (gap), or when a local run on a Mac
where that mode is only `warn` (processing.recommend: under 16 GB) failed or
took longer than the call. Not under enterprise lockdown; "Not now" sticks."""
import pytest

import processing
from api import views

HW_8GB = {"memory_gb": 8.0, "architecture": "arm64", "cpu_count": 8}
HW_32GB = {"memory_gb": 32.0, "architecture": "arm64", "cpu_count": 8}


@pytest.fixture
def mac(monkeypatch):
    def use(hw):
        monkeypatch.setattr(processing, "hardware", lambda: hw)
    return use


def meta(**kw):
    return {"duration_seconds": 600.0, **kw}


@pytest.mark.parametrize("last_run, offer", [
    ({"mode": "local_light", "status": "failed", "total_s": 30}, "failed"),
    ({"mode": "local_light", "status": "ok", "total_s": 900}, "slow"),
    ({"mode": "local_light", "status": "ok", "total_s": 300}, None),
    ({"mode": "cloud", "status": "failed", "total_s": 900}, None),
])
def test_a_local_run_on_an_8_gb_mac_that_failed_or_was_slower_than_the_call(mac, last_run, offer):
    mac(HW_8GB)
    assert views.cloud_offer(meta(last_run=last_run)) == offer


def test_the_same_slow_run_on_a_32_gb_mac_offers_nothing(mac):
    mac(HW_32GB)
    assert views.cloud_offer(meta(last_run={"mode": "local_light", "status": "ok", "total_s": 900})) is None


def test_a_gap_offers_a_cloud_retry_on_any_mac(mac):
    mac(HW_32GB)
    assert views.cloud_offer(meta(transcription_engines={"local_s": 0, "gap_s": 42.0, "windows": []})) == "gap"


def test_dismissed_or_under_lockdown_offers_nothing(mac, monkeypatch):
    mac(HW_8GB)
    failed = {"mode": "local_light", "status": "failed"}
    assert views.cloud_offer(meta(last_run=failed, cloud_offer_dismissed=True)) is None
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert views.cloud_offer(meta(last_run=failed)) is None


def test_a_run_records_its_mode_status_and_time(monkeypatch, fake_text, fake_transcriber):
    import json
    import db
    import paths
    from pipeline import runner
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "last-run"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audio.wav").write_bytes(b"")
    db.create_recording("last-run", str(folder), "last-run", "2026-11-13T10:00:00+00:00", 1.0, 1, {})
    monkeypatch.setattr(runner, "guess_speaker_from_tracks", lambda *a: "You")
    monkeypatch.setattr(runner, "audio_stream_count", lambda p: 2)
    fake_transcriber.segments = [{"start": 0.0, "end": 3.0, "text": "Ship it."}]
    fake_text.reply = lambda prompt, trace, **kw: "general" if trace == "template.select" else json.dumps(dict(
        title="Sync", overview="x", action_items_md="- a", decisions_md="- b", timeline_md="- c",
        open_questions_md="- d", key_entities_md="- e"))
    runner.process_recording_local(folder, {"mode": "local_light"})
    last = db.get_recording("last-run")["metadata"]["last_run"]
    assert last["mode"] == "local_light" and last["status"] == "ok" and last["total_s"] >= 0


def test_not_now_dismisses_the_offer(monkeypatch):
    import db
    import paths
    from api.routes import recordings as routes
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "offer-dismiss"
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording("offer-dismiss", str(folder), "t", "2026-11-13T10:00:00+00:00", 1.0, 1, {})

    class Req:
        def send_json(self, body, status=200):
            self.reply = (status, body)
    routes.post_api_recording_cloud_offer_dismiss(Req(), "", {"id": "offer-dismiss"})
    assert db.get_recording("offer-dismiss")["metadata"]["cloud_offer_dismissed"] is True
