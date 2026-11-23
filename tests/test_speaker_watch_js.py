"""The browser snapshot script embedded in capture/SpeakerWatcher.swift is
flattened onto one line before AppleScript hands it to the browser, so a `//`
line comment would comment out everything after it. Participant names were
silently empty for ten days because of exactly that. Check the flattened
script still parses (node is a dev dependency of this repo)."""
import shutil
import subprocess

import pytest
from swift_snapshot_js import snapshot_js


def test_snapshot_js_has_no_line_comments():
    code_lines = [line for line in snapshot_js().splitlines() if "//" in line and "://" not in line]
    assert code_lines == [], f"`//` comments break the flattened script: {code_lines[:2]}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_flattened_snapshot_js_parses(tmp_path):
    flat = snapshot_js().replace("\n", " ")
    script = tmp_path / "snapshot.flat.js"
    script.write_text(flat)
    result = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-400:]


ZOOM_PAGE = r"""
const all = (els) => els.flatMap((e) => [e, ...all(e.children || [])]);
const doc = (els, title) => ({ title, querySelector: (g) => doc(els).querySelectorAll(g)[0] || null,
  querySelectorAll: (g) => { const want = g.split(/,\s*/); return all(els).filter((e) => e.sel.some((s) => want.includes(s))); } });
const el = (sel, text = '', children = []) => ({ sel, innerText: text, children, getAttribute: () => null,
  querySelector: (g) => doc(children).querySelector(g), querySelectorAll: (g) => doc(children).querySelectorAll(g) });
const tiles = ['Asha Verma', 'Ravi Kumar (Host)', 'Meera Iyer'].map((n) => el(['.video-avatar__avatar-footer'], n));
const leave = el(['.footer__leave-btn-container button', 'button'], 'Leave');
const inner = doc([leave, ...tiles], 'Zoom Meeting');
const frame = { sel: ['iframe'], children: [], contentDocument: inner, getAttribute: () => null };
const document = doc([frame], 'Zoom');
const location = { hostname: 'app.zoom.us' };
console.log(SNAPSHOT);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_zoom_web_names_are_read_inside_the_client_iframe(tmp_path):
    import json
    script = tmp_path / "zoom.js"
    script.write_text(ZOOM_PAGE.replace("SNAPSHOT", snapshot_js()))
    result = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-400:]
    answer = json.loads(result.stdout)
    assert answer["active"] is True
    assert sorted(answer["participants"]) == ["Asha Verma", "Meera Iyer", "Ravi Kumar"]
