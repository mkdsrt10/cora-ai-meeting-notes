"""The browser snapshot script embedded in capture/SpeakerWatcher.swift is
flattened onto one line before AppleScript hands it to the browser, so a `//`
line comment would comment out everything after it. Participant names were
silently empty for ten days because of exactly that. Check the flattened
script still parses (node is a dev dependency of this repo)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SWIFT = Path(__file__).resolve().parents[1] / "capture" / "SpeakerWatcher.swift"


def embedded_snapshot_js() -> str:
    source = SWIFT.read_text()
    match = re.search(r'let googleMeetSnapshotJS = #"""\n(.*?)\n"""#', source, re.S)
    assert match, "snapshot script literal not found"
    return match.group(1)


def test_snapshot_js_has_no_line_comments():
    code_lines = [line for line in embedded_snapshot_js().splitlines() if "//" in line and "://" not in line]
    assert code_lines == [], f"`//` comments break the flattened script: {code_lines[:2]}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_flattened_snapshot_js_parses(tmp_path):
    flat = embedded_snapshot_js().replace("\n", " ")
    script = tmp_path / "snapshot.flat.js"
    script.write_text(flat)
    result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-400:]
