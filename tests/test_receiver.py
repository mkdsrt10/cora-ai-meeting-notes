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


def request_log(rx):
    path = rx.root / "logs" / "receiver.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


DEFAULT_CONFIG = {"telemetry_enabled": True, "capture_sample_rate": 0.25,
                  "capture_max_minutes": 60, "min_app_version": None}


def test_config_without_a_file_serves_the_defaults_without_a_token(receiver):
    assert call(receiver, "GET", "/v1/config", token=None) == (200, DEFAULT_CONFIG)


def test_config_is_read_from_the_file_on_every_request_over_the_defaults(receiver):
    receiver.root.joinpath("config.json").write_text(json.dumps({"capture_sample_rate": 0}))
    assert call(receiver, "GET", "/v1/config") == (200, {**DEFAULT_CONFIG, "capture_sample_rate": 0})
    receiver.root.joinpath("config.json").write_text(json.dumps({"min_app_version": "0.3.1"}))
    assert call(receiver, "GET", "/v1/config") == (200, {**DEFAULT_CONFIG, "min_app_version": "0.3.1"})


def test_the_example_config_spells_out_exactly_the_defaults(receiver):
    example = RECEIVER.parent / "config.example.json"
    receiver.root.joinpath("config.json").write_text(example.read_text())
    assert call(receiver, "GET", "/v1/config") == (200, DEFAULT_CONFIG)
    assert set(json.loads(example.read_text())) == set(DEFAULT_CONFIG)


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


def test_every_request_is_logged_as_jsonl_without_the_token(receiver):
    post_events(receiver, BATCH)
    post_events(receiver, BATCH, token="wrong-token")
    call(receiver, "GET", "/v1/config", token=None)
    log = request_log(receiver)
    assert [(e["method"], e["path"], e["status"]) for e in log] == [
        ("POST", "/v1/events", 202), ("POST", "/v1/events", 401), ("GET", "/v1/config", 200)]
    assert log[0]["install_id"] == "inst-1" and log[0]["accepted"] == 2
    assert all("ms" in e and "ts" in e for e in log)
    raw = (receiver.root / "logs" / "receiver.jsonl").read_text()
    assert TOKEN not in raw and "wrong-token" not in raw


def test_an_empty_batch_is_accepted_and_writes_nothing(receiver):
    assert post_events(receiver, {**BATCH, "events": []}) == (202, {"accepted": 0})
    assert day_lines(receiver)[1] == []


# ---- captured recordings ----------------------------------------------------------

ARCHIVE = bytes(range(256)) * 4096  # 1 MiB of opaque bytes; the receiver never opens archives
UPLOAD_HEADERS = {"X-Cora-Install": "inst-1", "X-Cora-Recording": "20261111-0900-standup",
                  "X-Cora-Reason": "feedback", "X-Cora-Version": "0.3.1", "X-Cora-Display-Name": "Priya",
                  "Content-Type": "application/gzip"}


def upload(rx, body=ARCHIVE, token=TOKEN, **overrides):
    headers = {**UPLOAD_HEADERS, **overrides}
    return call(rx, "POST", "/v1/recordings", body, {k: v for k, v in headers.items() if v is not None},
                token=token)


def test_an_upload_lands_in_its_install_and_recording_folder_with_a_sidecar(receiver):
    assert upload(receiver) == (201, {"stored": "inst-1/20261111-0900-standup"})
    folder = receiver.root / "recordings" / "inst-1" / "20261111-0900-standup"
    assert sorted(p.name for p in folder.iterdir()) == ["archive.tar.gz", "meta.json"]
    assert folder.joinpath("archive.tar.gz").read_bytes() == ARCHIVE
    meta = json.loads(folder.joinpath("meta.json").read_text())
    assert {k: meta[k] for k in ("install_id", "recording_id", "reason", "app_version", "display_name", "size")} == {
        "install_id": "inst-1", "recording_id": "20261111-0900-standup", "reason": "feedback",
        "app_version": "0.3.1", "display_name": "Priya", "size": len(ARCHIVE)}
    assert meta["received_at"].endswith("Z")


def test_a_second_upload_of_the_same_recording_is_a_conflict_and_keeps_the_first(receiver):
    assert upload(receiver)[0] == 201
    assert upload(receiver, body=b"different")[0] == 409
    folder = receiver.root / "recordings" / "inst-1" / "20261111-0900-standup"
    assert folder.joinpath("archive.tar.gz").read_bytes() == ARCHIVE
    assert upload(receiver, **{"X-Cora-Install": "inst-2"}) == (201, {"stored": "inst-2/20261111-0900-standup"})


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_an_upload_without_the_right_token_is_refused_and_not_stored(receiver, token):
    assert upload(receiver, token=token)[0] == 401
    assert not (receiver.root / "recordings").exists()


def test_a_client_that_expects_100_continue_is_refused_before_it_sends_the_archive(receiver):
    conn = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=15)
    conn.putrequest("POST", "/v1/recordings")
    for k, v in {**UPLOAD_HEADERS, "Authorization": "Bearer wrong-token", "Expect": "100-continue",
                 "Content-Length": str(len(ARCHIVE))}.items():
        conn.putheader(k, v)
    conn.endheaders()
    assert conn.getresponse().status == 401
    assert not (receiver.root / "recordings").exists()


def test_an_upload_over_2_gb_is_refused_by_its_length_before_any_byte_is_read(receiver):
    conn = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=15)
    conn.putrequest("POST", "/v1/recordings")
    for k, v in {**UPLOAD_HEADERS, "Authorization": f"Bearer {TOKEN}",
                 "Content-Length": str(2 * 1024 ** 3 + 1)}.items():
        conn.putheader(k, v)
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 413
    assert not (receiver.root / "recordings").exists()


@pytest.mark.parametrize("override", [
    {"X-Cora-Install": None}, {"X-Cora-Recording": None}, {"X-Cora-Install": ".."},
    {"X-Cora-Recording": "../../events"}, {"X-Cora-Recording": "a/b"}, {"X-Cora-Install": "."},
    {"X-Cora-Reason": "because"}, {"X-Cora-Reason": None},
], ids=["no-install", "no-recording", "dotdot-install", "traversal", "slash", "dot", "bad-reason", "no-reason"])
def test_an_upload_with_missing_or_unsafe_ids_is_refused(receiver, override):
    status, payload = upload(receiver, **override)
    assert status == 400 and payload["error"]
    assert not any((receiver.root / "recordings").rglob("archive.tar.gz"))
    assert not (receiver.root / "events").exists()


def test_a_cut_off_upload_stores_nothing_and_can_be_retried(receiver):
    conn = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=15)
    conn.putrequest("POST", "/v1/recordings")
    for k, v in {**UPLOAD_HEADERS, "Authorization": f"Bearer {TOKEN}", "Content-Length": str(len(ARCHIVE))}.items():
        conn.putheader(k, v)
    conn.endheaders()
    conn.send(ARCHIVE[:1000])
    conn.close()
    deadline = time.monotonic() + 10
    while not [e for e in request_log(receiver) if e["path"] == "/v1/recordings"]:
        assert time.monotonic() < deadline, "the receiver never logged the cut-off upload"
        time.sleep(0.05)
    entry = request_log(receiver)[-1]
    assert entry["status"] == 400 and "cut off" in entry["error"]
    folder = receiver.root / "recordings" / "inst-1" / "20261111-0900-standup"
    assert not folder.exists()
    assert upload(receiver)[0] == 201
    assert folder.joinpath("archive.tar.gz").read_bytes() == ARCHIVE
