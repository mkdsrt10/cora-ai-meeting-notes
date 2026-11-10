"""Input devices for the Microphone picker, listed by the capture helper
itself (`dual-capture --list-devices`) so the IDs are the ones capture opens."""
from __future__ import annotations

import json
import subprocess
import sys

import paths

HELPER = paths.CAPTURE_DIR / "dual-capture"
TIMEOUT_S = 5

_logged: set[str] = set()


def _log_once(reason: str) -> None:
    """One stderr line per distinct failure, so a re-list on every Settings
    visit doesn't repeat it. Device names never go in the log."""
    if reason in _logged:
        return
    _logged.add(reason)
    print(json.dumps({"event": "audio_devices_list_failed", "reason": reason}), file=sys.stderr, flush=True)


def list_devices() -> list[dict]:
    """[{name, unique_id, is_default}, ...] for the web UI; [] when the helper
    is missing, fails, or prints something other than the device array."""
    try:
        out = subprocess.run([str(HELPER), "--list-devices"], capture_output=True, text=True, check=True,
                             timeout=TIMEOUT_S)
        return [{"name": str(d["name"]), "unique_id": str(d["uniqueID"]), "is_default": bool(d["isDefault"])}
                for d in json.loads(out.stdout)]
    except subprocess.TimeoutExpired:
        _log_once("timeout")
    except OSError:
        _log_once("helper_missing")
    except subprocess.CalledProcessError as exc:
        _log_once(f"exit_{exc.returncode}")
    except (ValueError, KeyError, TypeError):
        _log_once("bad_output")
    return []
