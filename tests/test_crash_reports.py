"""crash_report Usage events from macOS .ips reports of Cora's own
processes: one per new report, only exception, signal, termination reason
and the top symbol names from our images; never a path or other report
content. Reports are written into a temp folder."""
import json
import os

import pytest

import crash_reports
import db
import usage_events

APP = "/Applications/Cora AI Meeting Notes.app/Contents"


def ips(proc, path, frames, images, exception=None, termination=None, triggered=True):
    header = {"app_name": proc, "bug_type": "309", "timestamp": "2026-11-11 10:10:10.00 +0530"}
    body = {"procName": proc, "procPath": path,
            "exception": exception or {"type": "EXC_CRASH", "signal": "SIGABRT"},
            "termination": termination or {"namespace": "SIGNAL", "code": 6, "indicator": "Abort trap: 6"},
            "usedImages": images,
            "threads": [{"name": "com.apple.main-thread /Users/priya/secret", "frames": []},
                        {"triggered": triggered, "frames": frames}],
            "faultingThread": 1}
    return json.dumps(header) + "\n" + json.dumps(body, indent=2)


HELPER_IMAGES = [{"name": "dual-capture", "path": f"{APP}/Resources/bin/dual-capture"},
                 {"name": "libsystem_kernel.dylib", "path": "/usr/lib/system/libsystem_kernel.dylib"}]
HELPER_FRAMES = [{"imageIndex": 1, "symbol": "__pthread_kill"},
                 {"imageIndex": 0, "symbol": "$s12dual_capture7RecorderC5startyyKF"},
                 {"imageIndex": 0, "symbol": "main"}] + [{"imageIndex": 0, "symbol": f"f{i}"} for i in range(6)]


@pytest.fixture
def reports(tmp_path):
    db.init_db()
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.execute("DELETE FROM settings WHERE key = ?", (crash_reports.SETTING,))
        conn.commit()

    def write(name, text, mtime):
        path = tmp_path / name
        path.write_text(text)
        os.utime(path, (mtime, mtime))
        return path
    write.dir = tmp_path
    return write


def events():
    with db.get_db() as conn:
        rows = conn.execute("SELECT payload FROM usage_events WHERE name = 'crash_report' ORDER BY id").fetchall()
    return [json.loads(r[0]) for r in rows]


def test_a_helper_crash_becomes_one_event_with_our_top_frames_and_no_paths(reports):
    now = 1_800_000_000.0
    reports("dual-capture-2026-11-11-101010.ips",
            ips("dual-capture", f"{APP}/Resources/bin/dual-capture", HELPER_FRAMES, HELPER_IMAGES), now - 60)
    assert crash_reports.scan(reports.dir, now=now) == 1
    [event] = events()
    assert event == {"process": "dual-capture", "exception_type": "EXC_CRASH", "signal": "SIGABRT",
                     "termination_reason": "Abort trap: 6",
                     "frames": "$s12dual_capture7RecorderC5startyyKF | main | f0 | f1 | f2"}
    assert "/" not in json.dumps(event)


def test_only_reports_newer_than_the_last_check_and_only_ours(reports):
    now = 1_800_000_000.0
    db.set_setting(crash_reports.SETTING, now - 3600)
    reports("speaker-watch-old.ips", ips("speaker-watch", f"{APP}/Resources/bin/speaker-watch", [], []), now - 7200)
    reports("speaker-watch-new.ips", ips("speaker-watch", f"{APP}/Resources/bin/speaker-watch", [], []), now - 60)
    reports("Safari-2026.ips", ips("Safari", "/Applications/Safari.app/Contents/MacOS/Safari", [], []), now - 60)
    reports("python3.11-user.ips", ips("python3.11", "/opt/homebrew/bin/python3.11", [], []), now - 60)
    reports("python3.11-ours.ips", ips("python3.11", f"{APP}/Resources/python/bin/python3.11", [], []), now - 60)
    reports("dual-capture-text.crash", "Process: dual-capture", now - 60)
    assert crash_reports.scan(reports.dir, now=now) == 2
    assert sorted(e["process"] for e in events()) == ["python3.11", "speaker-watch"]
    assert crash_reports.scan(reports.dir, now=now + 10) == 0, "the check time moved on"


def test_the_first_check_looks_back_a_week(reports):
    now = 1_800_000_000.0
    reports("mic-watch-recent.ips", ips("mic-watch", f"{APP}/Resources/bin/mic-watch", [], []), now - 2 * 86400)
    reports("mic-watch-ancient.ips", ips("mic-watch", f"{APP}/Resources/bin/mic-watch", [], []), now - 30 * 86400)
    assert crash_reports.scan(reports.dir, now=now) == 1


def test_a_dyld_termination_keeps_the_reason_but_drops_paths(reports):
    now = 1_800_000_000.0
    term = {"namespace": "DYLD", "code": 4, "indicator": "Symbol missing /System/Library/Frameworks/CoreMedia"}
    reports("dual-capture-dyld.ips", ips("dual-capture", f"{APP}/Resources/bin/dual-capture", [], HELPER_IMAGES,
                                         exception={"type": "EXC_CRASH", "signal": "SIGABRT"}, termination=term), now - 5)
    crash_reports.scan(reports.dir, now=now)
    [event] = events()
    assert event["termination_reason"] == "Symbol missing" and event["frames"] is None


def test_unreadable_reports_are_skipped(reports):
    now = 1_800_000_000.0
    reports("dual-capture-broken.ips", "not json at all", now - 5)
    assert crash_reports.scan(reports.dir, now=now) == 0


def test_crash_report_is_in_the_catalog():
    usage_events.validate("crash_report", {"process": "dual-capture", "exception_type": "EXC_CRASH",
                                           "signal": "SIGABRT", "termination_reason": "Abort trap: 6",
                                           "frames": "x | " * 100})
