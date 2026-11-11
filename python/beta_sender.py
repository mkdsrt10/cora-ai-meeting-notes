"""Beta sender: delivers Usage events (and Captured Recordings) to the Cora
team's receiver, and holds the remote config.

One background thread, started by the server after its port is bound. It
fetches the remote config once, then flushes unsent events at start, every
CORA_TELEMETRY_FLUSH_SECONDS (600) while unsent rows exist, on `flush_now()`
(after Feedback), and once more when the server shuts down (`stop()`). After
each successful event batch it uploads at most one pending Captured Recording
(python/capture.py, when present). Standard library only (urllib).

Nothing here opens a socket unless `usage_events.sharing_enabled()` (share
toggle on, no enterprise lockdown, receiver URL and token present). Events and
captures additionally need the remote config's `telemetry_enabled`; the config
fetch itself is the one request made while that is off, so the Cora team can
switch telemetry back on without a release.
See docs/specs/beta-telemetry-and-updates.md ("Sender", "Remote config").
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import string
import urllib.error
import urllib.parse
import urllib.request

import paths
import usage_events

TIMEOUT_S = 15
SHUTDOWN_TIMEOUT_S = 5
DEFAULT_FLUSH_SECONDS = 600.0
CONFIG_NAME = "remote_config.json"
CONFIG_DEFAULTS: dict = {
    "telemetry_enabled": True,
    "capture_sample_rate": 0.25,
    "capture_max_minutes": 60,
    "min_app_version": None,
}

_lock = threading.Lock()  # one flush at a time (thread, flush_now, shutdown)
_thread: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()
_status: dict = {"last_flush_at": None, "last_error": None}


# ---- receiver access ---------------------------------------------------------------

def _receiver() -> tuple[str, str]:
    return (os.environ.get("CORA_BETA_RECEIVER_URL", "").strip().rstrip("/"),
            os.environ.get("CORA_BETA_TOKEN", "").strip())


def _request(method: str, path: str, body=None, headers: dict | None = None,
             timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    """One request to the receiver. Callers check `usage_events.sharing_enabled()`
    first; this re-checks so no code path can reach the network without it."""
    if not usage_events.sharing_enabled():
        raise PermissionError("sharing is off")
    base, token = _receiver()
    req = urllib.request.Request(base + path, data=body, method=method, headers=dict(headers or {}))
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- remote config ------------------------------------------------------------------

def _config_path():
    return paths.DATA_DIR / CONFIG_NAME


def _clean_config(raw) -> dict:
    """Known keys over the defaults; anything malformed falls back to its default."""
    config = dict(CONFIG_DEFAULTS)
    if not isinstance(raw, dict):
        return config
    if isinstance(raw.get("telemetry_enabled"), bool):
        config["telemetry_enabled"] = raw["telemetry_enabled"]
    rate = raw.get("capture_sample_rate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0 <= rate <= 1:
        config["capture_sample_rate"] = float(rate)
    minutes = raw.get("capture_max_minutes")
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes >= 0:
        config["capture_max_minutes"] = minutes
    if raw.get("min_app_version") is None or isinstance(raw.get("min_app_version"), str):
        config["min_app_version"] = raw.get("min_app_version")
    return config


def remote_config() -> dict:
    """The remote config in use: the copy cached at the last successful fetch
    (this start's, or an earlier one), else the defaults."""
    try:
        return _clean_config(json.loads(_config_path().read_text()))
    except (OSError, ValueError):
        return dict(CONFIG_DEFAULTS)


def _fetch_config() -> None:
    """GET /v1/config once; cache it on success. On any failure (unreachable,
    500 for a malformed receiver file, bad JSON) the cached copy stays."""
    try:
        status, raw = _request("GET", "/v1/config")
        if status != 200:
            raise RuntimeError(f"receiver answered {status} to /v1/config")
        fetched = json.loads(raw)
        if not isinstance(fetched, dict):
            raise ValueError("config is not an object")
    except Exception as e:  # noqa: BLE001 - keep the cached copy, report the error
        _status["last_error"] = f"remote config: {type(e).__name__}: {e}"
        return
    path = _config_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean_config(fetched), indent=2))
    tmp.replace(path)


# ---- flushing -----------------------------------------------------------------------

def _may_send() -> bool:
    return usage_events.sharing_enabled() and bool(remote_config()["telemetry_enabled"])


def _send_events(timeout: float) -> None:
    """Post batches until the queue is empty. Raises on the first failure;
    rows of a failed batch stay unsent."""
    while True:
        batch = usage_events.pending_batch()
        if not batch["events"]:
            return
        status, raw = _request("POST", "/v1/events", json.dumps(batch).encode(),
                               {"Content-Type": "application/json"}, timeout)
        if status != 202:
            raise RuntimeError(f"receiver answered {status} to /v1/events: "
                               f"{raw[:200].decode('utf-8', 'replace')}")
        usage_events.mark_sent(e["id"] for e in batch["events"])


def _capture_module():
    """python/capture.py (Captured Recordings), or None before it exists."""
    try:
        import capture
    except ImportError:
        return None
    return capture if hasattr(capture, "next_pending") and hasattr(capture, "mark_uploaded") else None


def _drop_expired_captures() -> None:
    capture = _capture_module()
    if capture is None or not hasattr(capture, "drop_expired"):
        return
    try:
        capture.drop_expired()
    except Exception as e:  # noqa: BLE001 - local bookkeeping, never fatal to a flush
        _status["last_error"] = f"capture expiry: {type(e).__name__}: {e}"


def _upload_one_capture() -> None:
    """Upload the oldest pending Captured Recording, if any. 201 and 409
    (already stored) both mark it uploaded; anything else leaves it pending."""
    capture = _capture_module()
    if capture is None:
        return
    pending = capture.next_pending()
    if not pending:
        return
    recording_id, reason = pending["recording_id"], pending["reason"]
    archive = capture.build_archive(recording_id)
    try:
        version, _commit = usage_events._versions()
        headers = {
            "Content-Type": "application/gzip",
            "Content-Length": str(archive.stat().st_size),
            "X-Cora-Install": usage_events.install_id(),
            "X-Cora-Recording": recording_id,
            "X-Cora-Reason": reason,
            "X-Cora-Version": version or "",
            "X-Cora-Display-Name": _display_name(),
        }
        with open(archive, "rb") as body:
            status, raw = _request("POST", "/v1/recordings", body, headers)
    finally:
        archive.unlink(missing_ok=True)
    if status not in (201, 409):
        raise RuntimeError(f"receiver answered {status} to /v1/recordings: "
                           f"{raw[:200].decode('utf-8', 'replace')}")
    capture.mark_uploaded(recording_id)


_HEADER_SAFE = "".join(c for c in string.printable if c not in "%\t\n\r\x0b\x0c")


def _display_name() -> str:
    """The display name for a header: printable ASCII as is, everything else
    (non-Latin-1 letters, control characters, '%') percent-encoded as UTF-8."""
    import db
    return urllib.parse.quote(db.get_setting("beta_display_name") or "", safe=_HEADER_SAFE)


def flush(*, captures: bool = True, timeout: float = TIMEOUT_S, wait: float | None = None) -> None:
    """Send unsent events now, then (with `captures`) at most one Captured
    Recording, on the calling thread. Never raises. Opens no socket unless
    sharing is enabled and the remote config allows telemetry. A failure keeps
    the rows, lands in status()["last_error"] and applies the queue limits
    (7 days / 5 MB, oldest dropped first, one `events_dropped`). `wait` bounds
    how long to wait for a flush already in progress (None: as long as it takes).
    Captures waiting more than 7 days are dropped first, whether or not
    anything can be sent, so their `capture_dropped` events go in this batch."""
    _drop_expired_captures()
    if not _may_send():
        return
    if not _lock.acquire(timeout=-1 if wait is None else wait):
        return
    try:
        try:
            _send_events(timeout)
        except Exception as e:  # noqa: BLE001 - any failure is reported, never fatal
            _status["last_error"] = f"{type(e).__name__}: {e}"
            try:
                usage_events.enforce_queue_limits()
            except Exception:  # noqa: BLE001
                pass
            return
        _status.update(last_flush_at=_now_iso(), last_error=None)
        if captures:
            try:
                _upload_one_capture()
            except Exception as e:  # noqa: BLE001
                _status["last_error"] = f"capture upload: {type(e).__name__}: {e}"
    finally:
        _lock.release()


def flush_now() -> None:
    """Ask the sender thread to flush right away (after a Feedback row).
    Returns immediately; without a running thread, flushes on a short-lived one."""
    if _thread and _thread.is_alive():
        _wake.set()
    else:
        threading.Thread(target=flush, name="beta-sender-flush", daemon=True).start()


def _pending_captures():
    capture = _capture_module()
    if capture is None or not hasattr(capture, "pending_count"):
        return None
    try:
        return capture.pending_count()
    except Exception:  # noqa: BLE001
        return None


def status() -> dict:
    """Sender fields for GET /api/beta/status."""
    return {"pending_captures": _pending_captures(), **_status}


# ---- the thread ---------------------------------------------------------------------

def flush_interval() -> float:
    try:
        seconds = float(os.environ.get("CORA_TELEMETRY_FLUSH_SECONDS", "") or DEFAULT_FLUSH_SECONDS)
    except ValueError:
        return DEFAULT_FLUSH_SECONDS
    return seconds if seconds > 0 else DEFAULT_FLUSH_SECONDS


def _run() -> None:
    if usage_events.sharing_enabled():
        _fetch_config()
    flush()
    interval = flush_interval()
    while not _stop.is_set():
        woken = _wake.wait(interval)
        _wake.clear()
        if _stop.is_set():
            return
        if woken or usage_events.unsent_count():
            flush()


def start() -> None:
    """Start the sender thread (idempotent). Does no I/O on the caller's thread."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _wake.clear()
    _status.update(last_flush_at=None, last_error=None)
    _thread = threading.Thread(target=_run, name="beta-sender", daemon=True)
    _thread.start()


def stop(final_flush: bool = True) -> None:
    """Stop the thread; with `final_flush`, send what is still unsent (the
    server's shutdown path). Bounded so quitting Cora never hangs on the
    receiver: no capture upload, short timeouts, skipped if a flush already
    in flight does not finish in time."""
    global _thread
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=SHUTDOWN_TIMEOUT_S)
        _thread = None
    if final_flush:
        flush(captures=False, timeout=SHUTDOWN_TIMEOUT_S, wait=SHUTDOWN_TIMEOUT_S)
    _status.update(last_flush_at=None, last_error=None)
