"""Notification history (db.log_notification/get_notifications) and the
logs route's file-safety guard (api.routes.logs._safe_log_name) — the new
in-app way to see what happened and export it, added after flat log files
on disk turned out to be the only place any of this was visible."""
import zipfile
import io

import pytest

import db
from api.routes import logs as logs_routes


def test_log_notification_round_trips():
    db.log_notification("Cora", "Recording started", level="info", recording_id="meeting_1")
    db.log_notification("Cora", "Still processing", level="warning")
    items = db.get_notifications(limit=10)
    assert items[0]["body"] == "Still processing"
    assert items[0]["level"] == "warning"
    assert items[1]["recording_id"] == "meeting_1"


def test_safe_log_name_rejects_traversal():
    with pytest.raises(ValueError):
        logs_routes._safe_log_name("../../etc/passwd")
    with pytest.raises(ValueError):
        logs_routes._safe_log_name("sub/dir/file.log")


def test_safe_log_name_rejects_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_routes, "LOGS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError):
        logs_routes._safe_log_name("does-not-exist.log")


def test_safe_log_name_accepts_real_file(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_routes, "LOGS_DIR", tmp_path)
    (tmp_path / "cron-pipeline.log").write_text("hello\n")
    resolved = logs_routes._safe_log_name("cron-pipeline.log")
    assert resolved.read_text() == "hello\n"


def test_tail_bytes_truncates_to_the_end(tmp_path):
    f = tmp_path / "big.log"
    f.write_text("x" * 1000 + "TAIL")
    tail = logs_routes._tail_bytes(f, max_bytes=10)
    assert tail.endswith("TAIL")
    assert len(tail) == 10


def test_build_bundle_includes_notifications_and_known_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(logs_routes, "LOGS_DIR", tmp_path)
    (tmp_path / "cron-pipeline.log").write_text("cron scan ok\n")
    db.log_notification("Cora", "Bundle test", level="info")

    bundle = logs_routes._build_bundle()
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        names = zf.namelist()
        assert "notifications.json" in names
        assert "cron-pipeline.log" in names
        assert b"Bundle test" in zf.read("notifications.json")
