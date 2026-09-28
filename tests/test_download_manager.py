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
