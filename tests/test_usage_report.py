"""tools/usage_report.py over a receiver root (layout: receiver/README.md "Disk layout").

The checked-in fixture tests/fixtures/receiver-root holds two versions:
  0.4.0  installs inst-aaaa "Mayank" (rec-1 local ok 90 s, rec-2 cloud ok 120 s) and inst-bbbb "Priya Shah"
         (rec-3 local error); corrections 3 + 1; feedback notes up/down, recording down, overall up;
         captures rec-1 and rec-3 (meta display name percent-encoded "Priya%20Shah").
  0.3.9  install inst-cccc, no name (rec-9 cloud ok 60 s); capture rec-9 as a sample.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "usage_report.py"
FIXTURE = REPO / "tests" / "fixtures" / "receiver-root"


def run_report(root, *args):
    out = subprocess.run([sys.executable, str(SCRIPT), str(root), *args], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout


def section(text, heading):
    """The body under a Markdown heading, up to the next heading of the same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines))
                if lines[i].startswith("#") and len(lines[i]) - len(lines[i].lstrip("#")) <= level), len(lines))
    return "\n".join(lines[start:end])


def row(text, label):
    """Cells of the first table row whose first cell is `label`."""
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == label:
            return cells
    raise AssertionError(f"no row {label!r} in:\n{text}")


def test_active_installs_per_version():
    report = run_report(FIXTURE)
    assert row(section(report, "## 0.4.0"), "Active installs")[1] == "2"
    assert row(section(report, "## 0.3.9"), "Active installs")[1] == "1"


def test_pipeline_health_per_version():
    v040 = section(run_report(FIXTURE), "## 0.4.0")
    assert row(v040, "Processing failure rate")[1] == "33% (1 of 3)"
    # rec-1 stop 10:00:00 -> ok 10:01:30 = 90 s; rec-2 11:00:00 -> 11:02:00 = 120 s; rec-3 failed, no notes
    assert row(v040, "Median stop to notes")[1] == "105 s (2 recordings)"
    # text providers: local_mlx, gemini, local
    assert row(v040, "Local vs cloud (text model)")[1] == "67% local, 33% cloud (3 jobs)"
    v039 = section(run_report(FIXTURE), "## 0.3.9")
    assert row(v039, "Processing failure rate")[1] == "0% (0 of 1)"
    assert row(v039, "Median stop to notes")[1] == "60 s (1 recordings)"
    assert row(v039, "Local vs cloud (text model)")[1] == "0% local, 100% cloud (1 jobs)"


def test_recordings_per_display_name_and_unnamed_install():
    report = run_report(FIXTURE)
    people = section(report, "### Recordings per person (0.4.0)")
    assert row(people, "Mayank")[1] == "2"
    assert row(people, "Priya Shah")[1] == "1"
    # No display name: the install id stands in
    assert row(section(report, "### Recordings per person (0.3.9)"), "(inst-cccc)")[1] == "1"


def test_corrections_and_thumbs_by_target():
    report = run_report(FIXTURE)
    # 3 + 1 corrections over the 2 transcripts that processed ok
    assert row(section(report, "## 0.4.0"), "Corrections per transcript")[1] == "2.0 (4 over 2 transcripts)"
    thumbs = section(report, "### Thumbs up by target (0.4.0)")
    assert row(thumbs, "notes")[1:] == ["1", "1", "50%"]
    assert row(thumbs, "recording")[1:] == ["0", "1", "0%"]
    assert row(thumbs, "overall")[1:] == ["1", "0", "100%"]
    assert "No feedback" in section(report, "### Thumbs up by target (0.3.9)")


def test_captured_recordings_from_meta_with_decoded_names():
    report = run_report(FIXTURE)
    assert row(section(report, "## 0.4.0"), "Captured recordings")[1] == "2 (feedback 2)"
    assert row(section(report, "## 0.3.9"), "Captured recordings")[1] == "1 (sample 1)"
    captures = section(report, "### Captured recordings (0.4.0)")
    assert row(captures, "Priya Shah")[1:] == ["rec-3", "feedback", "recordings/inst-bbbb/rec-3"]
    assert row(captures, "Mayank")[1:] == ["rec-1", "feedback", "recordings/inst-aaaa/rec-1"]
    assert "%20" not in report


def test_comment_list_escapes_markdown_and_skips_empty_comments():
    comments = section(run_report(FIXTURE), "## Comments")
    lines = [line for line in comments.splitlines() if line.startswith("| 0.")]
    assert len(lines) == 3  # the down-vote on rec-2 has no comment
    assert row(comments, "0.4.0")[:5] == ["0.4.0", "Mayank", "rec-1", "notes", "up"]
    assert "Great summary \\| crisp" in comments
    assert "| 0.4.0 | Priya Shah | rec-3 | recording | down | Wrong speakers<br>all over |" in comments
    assert "| 0.4.0 | Priya Shah | - | overall | up | Love it |" in comments


def write_events(root, lines, day="2026-11-09"):
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "events" / f"{day}.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def test_versions_newest_first_numerically(tmp_path):
    write_events(tmp_path, [{"id": 1, "name": "app_started", "ts": "2026-11-09T09:00:00Z", "payload": {},
                             "install_id": f"i-{v}", "display_name": None, "app_version": v,
                             "received_at": "2026-11-09T09:00:00Z"} for v in ("0.9.0", None, "0.10.0", "0.4.0")])
    headings = re.findall(r"^## (.+)$", run_report(tmp_path), re.M)
    assert headings == ["0.10.0", "0.9.0", "0.4.0", "unknown", "Comments"]


def test_comment_html_is_escaped(tmp_path):
    write_events(tmp_path, [{"id": 1, "name": "feedback", "ts": "2026-11-09T09:00:00Z", "install_id": "i-1",
                             "display_name": "<b>x</b>", "app_version": "0.4.0", "received_at": "2026-11-09T09:00:00Z",
                             "payload": {"recording_id": "r", "target": "notes", "rating": "up",
                                         "comment": "<script>a</script>"}}])
    comments = section(run_report(tmp_path), "## Comments")
    assert "<script>" not in comments and "&lt;script&gt;a&lt;/script&gt;" in comments
    assert "&lt;b&gt;x&lt;/b&gt;" in comments
