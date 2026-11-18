"""The Electron-side telemetry keys (permission snapshot, the app's own
costs while recording) are in the CATALOG, so POST /api/events accepts them."""
import usage_events

PERMS = {"perm_mic": "granted", "perm_screen": "denied", "perm_accessibility": "denied", "perm_automation": "unknown"}


def test_app_started_and_recording_started_carry_the_permission_snapshot():
    usage_events.validate("app_started", {"macos": "15.1", "lockdown": False, **PERMS})
    usage_events.validate("recording_started", {"recording_id": "meeting_1", "started_from": "tray", **PERMS})


def test_recording_stopped_carries_the_apps_own_costs():
    usage_events.validate("recording_stopped", {
        "recording_id": "meeting_1", "duration_s": 60, "app_cpu_avg": 12.5, "app_cpu_max": 40.0,
        "app_rss_max_mb": 600, "helpers_cpu_avg": 9.0, "helpers_rss_max_mb": 80, "python_rss_max_mb": None})
