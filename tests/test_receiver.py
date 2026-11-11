"""Beta receiver (receiver/receiver.py), driven as its own process over HTTP,
the way team builds reach it through Tailscale Funnel."""
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

RECEIVER = Path(__file__).resolve().parent.parent / "receiver" / "receiver.py"
TOKEN = "receiver-test-token"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(root, token=TOKEN):
    port = free_port()
    env = {k: v for k, v in os.environ.items() if k != "CORA_RECEIVER_TOKEN"}
    if token is not None:
        env["CORA_RECEIVER_TOKEN"] = token
    proc = subprocess.Popen([sys.executable, str(RECEIVER), "--root", str(root), "--port", str(port)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc, port


@pytest.fixture
def receiver(tmp_path):
    root = tmp_path / "root"
    proc, port = start(root)
    deadline = time.monotonic() + 15
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(proc.communicate()[1].decode()) from None
            time.sleep(0.05)
    yield type("Receiver", (), {"root": root, "port": port})
    proc.terminate()
    proc.wait(timeout=10)


def call(rx, method, path, body=None, headers=None, token=TOKEN):
    conn = http.client.HTTPConnection("127.0.0.1", rx.port, timeout=15)
    hdrs = dict(headers or {})
    if token is not None:
        hdrs["Authorization"] = f"Bearer {token}"
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    return resp.status, json.loads(raw) if raw else None


DEFAULT_CONFIG = {"telemetry_enabled": True, "capture_sample_rate": 0.25,
                  "capture_max_minutes": 60, "min_app_version": None}


def test_config_without_a_file_serves_the_defaults_without_a_token(receiver):
    assert call(receiver, "GET", "/v1/config", token=None) == (200, DEFAULT_CONFIG)


def test_config_is_read_from_the_file_on_every_request_over_the_defaults(receiver):
    receiver.root.joinpath("config.json").write_text(json.dumps({"capture_sample_rate": 0}))
    assert call(receiver, "GET", "/v1/config") == (200, {**DEFAULT_CONFIG, "capture_sample_rate": 0})
    receiver.root.joinpath("config.json").write_text(json.dumps({"min_app_version": "0.3.1"}))
    assert call(receiver, "GET", "/v1/config") == (200, {**DEFAULT_CONFIG, "min_app_version": "0.3.1"})


def test_a_broken_config_file_is_a_server_error_not_silent_defaults(receiver):
    """Defaults would quietly turn sampling back on; a 500 keeps clients on their cached copy."""
    receiver.root.joinpath("config.json").write_text("{ capture_sample_rate: 0")
    assert call(receiver, "GET", "/v1/config")[0] == 500


# ---- events -----------------------------------------------------------------------

BATCH = {
    "install_id": "inst-1", "display_name": "Priya", "app_version": "0.3.1",
    "git_commit": "abc1234", "build_variant": "team",
    "events": [
        {"id": 7, "name": "app_started", "ts": "2026-11-11T09:00:00Z", "payload": {"lockdown": False}},
        {"id": 8, "name": "notes_viewed", "ts": "2026-11-11T09:05:00Z", "payload": {"recording_id": "r1"}},
    ],
}


def post_events(rx, batch, token=TOKEN):
    body = batch if isinstance(batch, bytes) else json.dumps(batch).encode()
    return call(rx, "POST", "/v1/events", body, {"Content-Type": "application/json"}, token=token)


def day_lines(rx):
    files = sorted((rx.root / "events").glob("*.jsonl"))
    return files, [json.loads(line) for f in files for line in f.read_text().splitlines()]


def test_a_batch_appends_one_line_per_event_to_the_utc_day_file(receiver):
    before = time.strftime("%Y-%m-%d", time.gmtime())
    assert post_events(receiver, BATCH) == (202, {"accepted": 2})
    assert post_events(receiver, {**BATCH, "events": BATCH["events"][:1]}) == (202, {"accepted": 1})
    after = time.strftime("%Y-%m-%d", time.gmtime())
    files, lines = day_lines(receiver)
    assert {f.name for f in files} <= {f"{before}.jsonl", f"{after}.jsonl"}
    assert [(e["id"], e["name"]) for e in lines] == [(7, "app_started"), (8, "notes_viewed"), (7, "app_started")]
    first = lines[0]
    assert first["payload"] == {"lockdown": False} and first["ts"] == "2026-11-11T09:00:00Z"
    assert {k: first[k] for k in ("install_id", "display_name", "app_version", "git_commit", "build_variant")} == {
        "install_id": "inst-1", "display_name": "Priya", "app_version": "0.3.1",
        "git_commit": "abc1234", "build_variant": "team"}
    assert first["received_at"][:10] in {before, after}


@pytest.mark.parametrize("token", [None, "wrong-token", ""])
def test_events_without_the_right_bearer_token_are_refused_and_not_written(receiver, token):
    assert post_events(receiver, BATCH, token=token)[0] == 401
    assert not (receiver.root / "events").exists()


def test_the_receiver_refuses_to_start_without_a_token(tmp_path):
    proc, _ = start(tmp_path / "root", token=None)
    assert proc.wait(timeout=15) != 0
    assert "CORA_RECEIVER_TOKEN" in proc.communicate()[1].decode()


@pytest.mark.parametrize("body", [
    b"{not json", b"[]", b'"x"', json.dumps({**BATCH, "events": "nope"}).encode(),
    json.dumps({k: v for k, v in BATCH.items() if k != "events"}).encode(),
    json.dumps({**BATCH, "events": [BATCH["events"][0], 5]}).encode(),
    json.dumps({**BATCH, "install_id": ""}).encode(),
    "é".encode("latin-1"),
], ids=["not-json", "array", "string", "events-not-list", "no-events", "event-not-object", "no-install",
        "not-utf8"])
def test_a_malformed_batch_is_refused_whole(receiver, body):
    status, payload = post_events(receiver, body)
    assert status == 400 and payload["error"]
    assert day_lines(receiver)[1] == []


def test_an_oversized_batch_is_refused_before_it_is_read(receiver):
    """The sender caps a batch at 5 MB; the receiver refuses anything past 16 MB by its length header."""
    conn = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=15)
    conn.putrequest("POST", "/v1/events")
    conn.putheader("Authorization", f"Bearer {TOKEN}")
    conn.putheader("Content-Length", str(16 * 1024 * 1024 + 1))
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    assert day_lines(receiver)[1] == []


def test_an_empty_batch_is_accepted_and_writes_nothing(receiver):
    assert post_events(receiver, {**BATCH, "events": []}) == (202, {"accepted": 0})
    assert day_lines(receiver)[1] == []
