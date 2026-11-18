"""Background model downloads (download_manager) — no real network calls;
huggingface_hub is monkeypatched so tests run offline and fast."""
import time

import download_manager as dm


def test_status_of_unknown_repo_is_idle():
    assert dm.status("never-started/repo") == {"state": "idle", "repo_id": "never-started/repo"}


def test_start_runs_download_to_completion(monkeypatch, tmp_path):
    calls = []

    def fake_snapshot_download(repo_id):
        calls.append(repo_id)
        (dm._cache_dir(repo_id) / "blobs").mkdir(parents=True, exist_ok=True)
        (dm._cache_dir(repo_id) / "blobs" / "abc").write_bytes(b"x" * 10)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(dm, "_repo_total_bytes", lambda repo_id: 10)
    monkeypatch.setattr(dm, "_cache_dir", lambda repo_id: (tmp_path / repo_id.replace("/", "--")))

    job = dm.start("some-org/some-model")
    assert job["state"] == "downloading"
    for _ in range(50):
        if dm.status("some-org/some-model")["state"] == "done":
            break
        time.sleep(0.05)
    final = dm.status("some-org/some-model")
    assert final["state"] == "done"
    assert final["downloaded_bytes"] == 10
    assert final["total_bytes"] == 10
    assert calls == ["some-org/some-model"]


def test_start_is_idempotent_while_in_flight(monkeypatch):
    started = []

    def slow_snapshot_download(repo_id):
        started.append(repo_id)
        time.sleep(0.3)

    monkeypatch.setattr("huggingface_hub.snapshot_download", slow_snapshot_download)
    monkeypatch.setattr(dm, "_repo_total_bytes", lambda repo_id: 0)
    monkeypatch.setattr(dm, "_downloaded_bytes", lambda repo_id: 0)

    dm.start("org/slow-model")
    dm.start("org/slow-model")  # second call while first is still running
    time.sleep(0.5)
    assert started == ["org/slow-model"]  # only one download actually kicked off


def test_failed_download_reports_error(monkeypatch):
    def boom(repo_id):
        raise RuntimeError("network is down")

    monkeypatch.setattr("huggingface_hub.snapshot_download", boom)
    monkeypatch.setattr(dm, "_repo_total_bytes", lambda repo_id: 0)

    dm.start("org/will-fail")
    for _ in range(50):
        if dm.status("org/will-fail")["state"] == "error":
            break
        time.sleep(0.05)
    final = dm.status("org/will-fail")
    assert final["state"] == "error"
    assert "network is down" in final["error"]


def _wait(repo_id, state):
    for _ in range(100):
        if dm.status(repo_id)["state"] == state:
            return
        time.sleep(0.02)


def test_each_finished_download_records_model_downloaded(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(dm, "_record", lambda name, payload: events.append((name, payload)))

    def fake(repo_id):
        (dm._cache_dir(repo_id) / "blobs").mkdir(parents=True, exist_ok=True)
        (dm._cache_dir(repo_id) / "blobs" / "w").write_bytes(b"x" * 3 * 1024 * 1024)
    monkeypatch.setattr("huggingface_hub.snapshot_download", fake)
    monkeypatch.setattr(dm, "_repo_total_bytes", lambda repo_id: 0)
    monkeypatch.setattr(dm, "_cache_dir", lambda repo_id: (tmp_path / repo_id.replace("/", "--")))
    dm.start("mlx-community/whisper-large-v3-turbo")
    _wait("mlx-community/whisper-large-v3-turbo", "done")
    [(name, payload)] = events
    assert name == "model_downloaded"
    assert payload["kind"] == "whisper" and payload["model"] == "mlx-community/whisper-large-v3-turbo"
    assert payload["size_mb"] == 3.0 and payload["outcome"] == "ok" and payload["seconds"] >= 0


def test_a_failed_download_records_outcome_error_for_a_text_model(monkeypatch):
    events = []
    monkeypatch.setattr(dm, "_record", lambda name, payload: events.append((name, payload)))
    monkeypatch.setattr("huggingface_hub.snapshot_download", lambda repo_id: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(dm, "_repo_total_bytes", lambda repo_id: 0)
    dm.start("mlx-community/Qwen3-4B-4bit")
    _wait("mlx-community/Qwen3-4B-4bit", "error")
    time.sleep(0.05)
    assert [(p["kind"], p["outcome"]) for _, p in events] == [("text", "error")]


def test_model_downloaded_is_in_the_catalog():
    import usage_events
    usage_events.validate("model_downloaded", {"kind": "whisper", "model": "m", "size_mb": 1.0,
                                               "seconds": 2.0, "outcome": "ok"})
