"""Beta sender (python/beta_sender.py): Usage events and the remote config
travel between the API server and a stub receiver started by the test, over
real sockets. Observations are what a teammate or the Cora team would see:
what reached the receiver, rows in the "Show what Cora shares" export, the
cached remote config, and the API's status and remote-config routes."""
import http.client
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_TOKEN = "beta-sender-api-token"
BEARER = "beta-sender-receiver-token"
BETA_KEYS = ("install_id", "beta_display_name", "share_usage")
DEFAULTS = {"telemetry_enabled": True, "capture_sample_rate": 0.25, "capture_max_minutes": 60,
            "min_app_version": None}


class StubReceiver:
    """A receiver that records every request and answers from `replies`
    (path -> (status, json body)); unknown paths get 404."""

    def __init__(self):
        self.requests = []
        self.replies = {"/v1/events": None, "/v1/config": (200, DEFAULTS)}
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                stub.requests.append({"method": self.command, "path": self.path,
                                      "headers": dict(self.headers), "body": body})
                reply = stub.replies.get(self.path, (404, {"error": "not found"}))
                if reply is None:  # default events reply: accept everything
                    reply = (202, {"accepted": len(json.loads(body)["events"])})
                status, payload = reply
                raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            do_GET = do_POST = answer

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def batches(self):
        return [json.loads(r["body"]) for r in self.requests if r["path"] == "/v1/events"]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stub():
    s = StubReceiver()
    yield s
    s.close()


@pytest.fixture(scope="module")
def port():
    import server
    from api import auth
    auth.API_TOKEN = API_TOKEN
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1]
    httpd.shutdown()


@pytest.fixture
def team_build(monkeypatch, stub):
    """A team build pointed at the stub receiver, sharing on, no events, no
    cached remote config. The sender is stopped (without a final flush)
    after the test."""
    import beta_sender
    import db
    import paths
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.execute(f"DELETE FROM settings WHERE key IN ({','.join('?' * len(BETA_KEYS))})", BETA_KEYS)
        conn.commit()
    (paths.DATA_DIR / "remote_config.json").unlink(missing_ok=True)
    monkeypatch.delenv("VOICECOACH_ENTERPRISE_LOCKDOWN", raising=False)
    monkeypatch.delenv("CORA_TELEMETRY_FLUSH_SECONDS", raising=False)
    monkeypatch.setenv("CORA_BUILD_VARIANT", "team")
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", stub.url)
    monkeypatch.setenv("CORA_BETA_TOKEN", BEARER)
    monkeypatch.setenv("CORA_APP_VERSION", "0.4.0-test")
    monkeypatch.setenv("CORA_GIT_COMMIT", "abc1234")
    import ai_trace
    ai_trace.app_versions.cache_clear()  # versions are read once per process
    import usage_emitters  # today's people_snapshot counts as taken, so batches hold only the test's events
    monkeypatch.setattr(usage_emitters, "people_snapshot_if_due", lambda: False)
    yield stub
    beta_sender.stop(final_flush=False)
    ai_trace.app_versions.cache_clear()


def record(name, payload):
    import usage_events
    return usage_events.record(name, payload)


def exported():
    import paths
    import usage_events
    path = usage_events.export_jsonl(paths.DATA_DIR / "test-export.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---- event batches ---------------------------------------------------------------

def test_start_sends_unsent_events_as_one_batch_with_the_bearer_token_and_marks_them_sent(team_build):
    import beta_sender
    import db
    db.set_setting("beta_display_name", "Asha")
    first = record("notes_viewed", {"recording_id": "r1"})
    second = record("person_added", {"source": "people_page"})

    beta_sender.start()

    assert wait_for(lambda: team_build.batches())
    [request] = [r for r in team_build.requests if r["path"] == "/v1/events"]
    assert request["method"] == "POST"
    assert request["headers"]["Authorization"] == f"Bearer {BEARER}"
    assert request["headers"]["Content-Type"] == "application/json"
    batch = json.loads(request["body"])
    assert batch["display_name"] == "Asha"
    assert batch["app_version"] == "0.4.0-test" and batch["git_commit"] == "abc1234"
    assert batch["build_variant"] == "team" and batch["install_id"]
    assert [(e["id"], e["name"], e["payload"]) for e in batch["events"]] == [
        (first, "notes_viewed", {"recording_id": "r1"}), (second, "person_added", {"source": "people_page"})]
    assert wait_for(lambda: all(row["sent_at"] for row in exported()))


def api(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Host": f"127.0.0.1:{port}", "X-VC-Token": API_TOKEN}
    if body is not None:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def test_a_receiver_error_keeps_the_rows_unsent_and_shows_in_the_beta_status(team_build, port):
    import beta_sender
    team_build.replies["/v1/events"] = (500, {"error": "internal error"})
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()

    assert wait_for(lambda: team_build.batches())
    assert wait_for(lambda: api(port, "GET", "/api/beta/status")[1]["last_error"])
    status, body = api(port, "GET", "/api/beta/status")
    assert status == 200
    assert "500" in body["last_error"]
    assert body["last_flush_at"] is None
    assert body["unsent_events"] == 1 and body["sharing_enabled"] is True
    assert [row["sent_at"] for row in exported()] == [None]


def test_an_unreachable_receiver_keeps_the_rows_unsent(team_build, port, monkeypatch):
    import beta_sender
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", f"http://127.0.0.1:{dead}")
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()

    assert wait_for(lambda: api(port, "GET", "/api/beta/status")[1]["last_error"])
    assert [row["sent_at"] for row in exported()] == [None]


def test_a_successful_flush_sets_last_flush_at_and_clears_the_error(team_build, port):
    import beta_sender
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()

    assert wait_for(lambda: api(port, "GET", "/api/beta/status")[1]["last_flush_at"])
    body = api(port, "GET", "/api/beta/status")[1]
    assert body["last_error"] is None and body["unsent_events"] == 0


def test_after_a_failed_flush_rows_older_than_7_days_are_dropped_with_one_events_dropped(team_build):
    import beta_sender
    import db
    team_build.replies["/v1/events"] = (500, {"error": "internal error"})
    with db.get_db() as conn:  # two rows queued long ago, while the receiver was unreachable
        conn.executemany("INSERT INTO usage_events (created_at, name, payload) VALUES (?, ?, ?)",
                         [("2026-01-01T00:00:00Z", "notes_viewed", '{"recording_id": "old1"}'),
                          ("2026-01-01T00:00:01Z", "notes_viewed", '{"recording_id": "old2"}')])
        conn.commit()
    record("notes_viewed", {"recording_id": "fresh"})

    beta_sender.start()

    assert wait_for(lambda: any(r["name"] == "events_dropped" for r in exported()))
    rows = exported()
    assert [(r["name"], r["payload"]) for r in rows] == [
        ("notes_viewed", {"recording_id": "fresh"}), ("events_dropped", {"count": 2})]
    assert all(r["sent_at"] is None for r in rows)


def days_ago(days):
    import datetime as dt
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert_rows(rows):
    """(created_at, name, payload json, sent_at) rows written straight into the queue."""
    import db
    with db.get_db() as conn:
        conn.executemany("INSERT INTO usage_events (created_at, name, payload, sent_at) VALUES (?, ?, ?, ?)", rows)
        conn.commit()


def test_rows_older_than_7_days_are_dropped_before_a_flush_so_they_never_ship(team_build):
    import beta_sender
    insert_rows([(days_ago(8), "notes_viewed", '{"recording_id": "stale"}', None)])
    record("notes_viewed", {"recording_id": "fresh"})

    beta_sender.start()

    assert wait_for(lambda: team_build.batches())
    [batch] = team_build.batches()
    assert [(e["name"], e["payload"]) for e in batch["events"]] == [
        ("notes_viewed", {"recording_id": "fresh"}), ("events_dropped", {"count": 1})]


def test_with_sharing_off_the_queue_limits_and_local_pruning_still_run_on_the_interval(team_build, monkeypatch):
    import beta_sender
    import db
    db.set_setting("share_usage", False)
    monkeypatch.setenv("CORA_TELEMETRY_FLUSH_SECONDS", "0.2")
    insert_rows([(days_ago(31), "notes_viewed", '{"recording_id": "sent-long-ago"}', days_ago(31)),
                 (days_ago(8), "notes_viewed", '{"recording_id": "stale-1"}', None)])
    record("notes_viewed", {"recording_id": "fresh"})

    beta_sender.start()
    assert wait_for(lambda: [r["payload"] for r in exported()] == [
        {"recording_id": "fresh"}, {"count": 1}])

    # More rows go stale while sharing stays off: still one events_dropped, with the running total.
    insert_rows([(days_ago(8), "notes_viewed", '{"recording_id": "stale-2"}', None)])
    assert wait_for(lambda: [(r["name"], r["payload"]) for r in exported()] == [
        ("notes_viewed", {"recording_id": "fresh"}), ("events_dropped", {"count": 2})])
    assert team_build.requests == []


# ---- when nothing may leave the Mac ----------------------------------------------

def opened_sockets(monkeypatch):
    """Every outbound socket connection attempted from this process."""
    attempts = []
    real = socket.create_connection

    def spy(address, *args, **kwargs):
        attempts.append(address)
        return real(address, *args, **kwargs)
    monkeypatch.setattr(socket, "create_connection", spy)
    return attempts


@pytest.mark.parametrize("veto", ["lockdown", "share_off", "no_token"])
def test_with_sharing_vetoed_the_sender_opens_no_socket_at_all(team_build, monkeypatch, veto):
    import beta_sender
    import db
    if veto == "lockdown":
        monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    elif veto == "share_off":
        db.set_setting("share_usage", False)
    else:
        monkeypatch.setenv("CORA_BETA_TOKEN", "")
    attempts = opened_sockets(monkeypatch)
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()
    beta_sender.flush_now()
    time.sleep(0.5)
    beta_sender.stop()  # includes the final flush

    assert team_build.requests == []
    assert attempts == []
    assert [row["sent_at"] for row in exported()] == [None]


def test_a_remote_config_with_telemetry_off_stops_events_after_the_config_fetch(team_build):
    import beta_sender
    team_build.replies["/v1/config"] = (200, {**DEFAULTS, "telemetry_enabled": False})
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()
    assert wait_for(lambda: team_build.requests)
    beta_sender.flush_now()
    time.sleep(0.5)
    beta_sender.stop()

    assert [r["path"] for r in team_build.requests] == ["/v1/config"]
    assert [row["sent_at"] for row in exported()] == [None]


# ---- when flushes happen ---------------------------------------------------------

def test_flush_now_sends_events_recorded_after_the_start_flush_without_waiting_for_the_interval(team_build):
    import beta_sender
    beta_sender.start()
    assert wait_for(lambda: any(r["path"] == "/v1/config" for r in team_build.requests))
    time.sleep(0.2)  # the start flush found nothing to send
    record("feedback", {"recording_id": "r1", "target": "notes", "rating": "down", "comment": "missed a decision"})

    beta_sender.flush_now()

    assert wait_for(lambda: team_build.batches(), timeout=5)
    [batch] = team_build.batches()
    assert [e["name"] for e in batch["events"]] == ["feedback"]


def test_events_are_flushed_on_the_interval_set_by_the_environment(team_build, monkeypatch):
    import beta_sender
    monkeypatch.setenv("CORA_TELEMETRY_FLUSH_SECONDS", "0.3")
    beta_sender.start()
    assert wait_for(lambda: any(r["path"] == "/v1/config" for r in team_build.requests))

    record("notes_viewed", {"recording_id": "r1"})
    assert wait_for(lambda: len(team_build.batches()) == 1, timeout=5)
    record("notes_viewed", {"recording_id": "r2"})
    assert wait_for(lambda: len(team_build.batches()) == 2, timeout=5)

    time.sleep(1.0)  # nothing unsent: the timer sends no empty batches
    assert [[e["payload"]["recording_id"] for e in b["events"]] for b in team_build.batches()] == [["r1"], ["r2"]]


def test_without_the_override_the_interval_is_ten_minutes(monkeypatch):
    import beta_sender
    monkeypatch.delenv("CORA_TELEMETRY_FLUSH_SECONDS", raising=False)
    assert beta_sender.flush_interval() == 600


def test_stop_sends_whatever_is_still_unsent(team_build, monkeypatch):
    import beta_sender
    beta_sender.start()
    assert wait_for(lambda: any(r["path"] == "/v1/config" for r in team_build.requests))
    time.sleep(0.2)
    record("recording_stopped", {"recording_id": "r1", "ended_by": "stop"})

    beta_sender.stop()

    [batch] = team_build.batches()
    assert [e["name"] for e in batch["events"]] == ["recording_stopped"]


# ---- remote config ---------------------------------------------------------------

def cached_config():
    import paths
    path = paths.DATA_DIR / "remote_config.json"
    return json.loads(path.read_text()) if path.exists() else None


def test_the_remote_config_is_fetched_at_start_cached_and_served_with_version_and_lockdown(team_build, port):
    import beta_sender
    served = {"telemetry_enabled": True, "capture_sample_rate": 0.5, "capture_max_minutes": 45,
              "min_app_version": "0.4.0"}
    team_build.replies["/v1/config"] = (200, served)

    beta_sender.start()

    assert wait_for(lambda: cached_config() == served)
    status, body = api(port, "GET", "/api/remote-config")
    assert status == 200
    assert body == {**served, "app_version": "0.4.0-test", "build_variant": "team", "lockdown": False}
    [config_request] = [r for r in team_build.requests if r["path"] == "/v1/config"]
    assert config_request["method"] == "GET"


def test_without_a_cache_or_a_receiver_the_remote_config_is_the_defaults(team_build, port, monkeypatch):
    monkeypatch.setenv("CORA_BETA_RECEIVER_URL", "")
    status, body = api(port, "GET", "/api/remote-config")
    assert status == 200
    assert body == {**DEFAULTS, "app_version": "0.4.0-test", "build_variant": "team", "lockdown": False}


@pytest.mark.parametrize("failure", ["500", "unreachable"])
def test_a_failed_fetch_keeps_the_cached_remote_config(team_build, port, monkeypatch, failure):
    import beta_sender
    import paths
    cached = {**DEFAULTS, "capture_sample_rate": 0.1, "min_app_version": "0.3.9"}
    (paths.DATA_DIR / "remote_config.json").write_text(json.dumps(cached))
    if failure == "500":  # the receiver's answer to a hand-edited config.json it cannot parse
        team_build.replies["/v1/config"] = (500, {"error": "internal error"})
    else:
        monkeypatch.setenv("CORA_BETA_RECEIVER_URL", "http://127.0.0.1:9")
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()

    def start_flush_done():
        body = api(port, "GET", "/api/beta/status")[1]
        return body["last_flush_at"] or body["last_error"]
    assert wait_for(start_flush_done)
    beta_sender.stop(final_flush=False)
    assert cached_config() == cached
    body = api(port, "GET", "/api/remote-config")[1]
    assert body["capture_sample_rate"] == 0.1 and body["min_app_version"] == "0.3.9"


def test_under_lockdown_the_remote_config_route_reports_it_and_nothing_is_fetched(team_build, port, monkeypatch):
    import beta_sender
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    beta_sender.start()
    time.sleep(0.3)
    body = api(port, "GET", "/api/remote-config")[1]
    assert body["lockdown"] is True
    assert team_build.requests == []


# ---- Captured Recording upload hook ----------------------------------------------

def test_after_the_events_one_pending_captured_recording_is_uploaded(team_build, monkeypatch, tmp_path):
    """python/capture.py lands with T6; this stands in for it at its contract
    (next_pending, build_archive, mark_uploaded)."""
    import types

    import beta_sender
    import db
    db.set_setting("beta_display_name", "Asha")
    archive = tmp_path / "r9.tar.gz"
    archive.write_bytes(b"\x1f\x8b fake archive")
    uploaded = []
    fake = types.SimpleNamespace(
        next_pending=lambda: None if uploaded else {"recording_id": "r9", "reason": "feedback"},
        build_archive=lambda recording_id: archive,
        mark_uploaded=uploaded.append)
    monkeypatch.setitem(sys.modules, "capture", fake)
    team_build.replies["/v1/recordings"] = (201, {"stored": "x/r9"})
    record("notes_viewed", {"recording_id": "r9"})

    beta_sender.start()

    assert wait_for(lambda: uploaded == ["r9"])
    paths_sent = [r["path"] for r in team_build.requests]
    assert paths_sent == ["/v1/config", "/v1/events", "/v1/recordings"]
    upload = team_build.requests[-1]
    assert upload["body"] == b"\x1f\x8b fake archive"
    assert upload["headers"]["Authorization"] == f"Bearer {BEARER}"
    assert upload["headers"]["X-Cora-Recording"] == "r9"
    assert upload["headers"]["X-Cora-Reason"] == "feedback"
    assert upload["headers"]["X-Cora-Version"] == "0.4.0-test"
    assert upload["headers"]["X-Cora-Display-Name"] == "Asha"
    assert upload["headers"]["X-Cora-Install"] == json.loads(team_build.requests[1]["body"])["install_id"]


def test_without_the_capture_module_only_events_are_sent(team_build, port, monkeypatch):
    import beta_sender
    monkeypatch.setitem(sys.modules, "capture", None)  # import capture -> ImportError
    record("notes_viewed", {"recording_id": "r1"})

    beta_sender.start()

    assert wait_for(lambda: api(port, "GET", "/api/beta/status")[1]["last_flush_at"])
    assert [r["path"] for r in team_build.requests] == ["/v1/config", "/v1/events"]
    assert api(port, "GET", "/api/beta/status")[1]["last_error"] is None


# ---- the server process ----------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(data_dir, receiver_url, extra_env=None):
    port = free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CORA_", "VOICECOACH_"))}
    env.update(VOICECOACH_DATA_DIR=str(data_dir), CORA_BUILD_VARIANT="team", CORA_BETA_RECEIVER_URL=receiver_url,
               CORA_BETA_TOKEN=BEARER, CORA_APP_VERSION="0.4.0-test", CORA_GIT_COMMIT="abc1234",
               **(extra_env or {}))
    proc = subprocess.Popen([sys.executable, str(ROOT / "python" / "server.py"), "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.monotonic() + 30
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc, port
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                raise RuntimeError(proc.communicate()[1].decode()) from None
            time.sleep(0.05)


def seed_events(data_dir, rows):
    """Usage events already queued in an Install's DB before the server starts."""
    import db
    conn = sqlite3.connect(data_dir / db.DB_PATH.name)
    conn.executescript("CREATE TABLE IF NOT EXISTS usage_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                       " created_at TEXT NOT NULL, name TEXT NOT NULL, payload TEXT NOT NULL, sent_at TEXT)")
    conn.executemany("INSERT INTO usage_events (created_at, name, payload) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_the_server_flushes_at_start_and_again_when_terminated(stub, tmp_path):
    seed_events(tmp_path, [("2099-01-01T00:00:00Z", "notes_viewed", '{"recording_id": "queued"}')])
    proc, port = run_server(tmp_path, stub.url)
    try:
        assert wait_for(lambda: len(stub.batches()) == 1, timeout=15)
        token = (tmp_path / ".api_token").read_text().strip()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        conn.request("POST", "/api/events", body=json.dumps({"name": "person_added", "payload": {}}),
                     headers={"Host": f"127.0.0.1:{port}", "X-VC-Token": token, "Content-Type": "application/json"})
        assert conn.getresponse().status == 200
    finally:
        proc.terminate()  # what Electron's pythonProcess.kill() sends
        proc.wait(timeout=30)
    # The server's start-up people_snapshot (usage_emitters) rides in the first batch.
    assert [[e["name"] for e in b["events"]] for b in stub.batches()] == [
        ["notes_viewed", "people_snapshot"], ["person_added"]]


def test_a_locked_down_server_makes_no_request_from_start_to_shutdown(stub, tmp_path):
    seed_events(tmp_path, [("2099-01-01T00:00:00Z", "notes_viewed", '{"recording_id": "queued"}')])
    proc, _ = run_server(tmp_path, stub.url, {"VOICECOACH_ENTERPRISE_LOCKDOWN": "1",
                                              "CORA_TELEMETRY_FLUSH_SECONDS": "0.2"})
    time.sleep(1.0)
    proc.terminate()
    proc.wait(timeout=30)
    assert stub.requests == []
    assert not (tmp_path / "remote_config.json").exists()


def test_an_unreachable_receiver_does_not_delay_the_server_port(tmp_path):
    """The receiver address blackholes (no answer): the API still comes up at once."""
    blackhole = socket.socket()
    blackhole.bind(("127.0.0.1", 0))
    blackhole.listen(0)  # accepts nothing; connections hang in the backlog
    try:
        started = time.monotonic()
        proc, _ = run_server(tmp_path, f"http://127.0.0.1:{blackhole.getsockname()[1]}")
        elapsed = time.monotonic() - started
        proc.kill()
        proc.wait(timeout=10)
    finally:
        blackhole.close()
    assert elapsed < 10
