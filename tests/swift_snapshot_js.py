"""The browser snapshot JS embedded in capture/SpeakerWatcher.swift, as the
browser receives it. The Swift literal interpolates the live-call snippet shared
with the Node detector (`\\#(liveCallSnippetJS)`, generated from
capture/live-call-snippet.js), so tests must substitute it the same way."""
import re
from pathlib import Path

SWIFT = Path(__file__).resolve().parents[1] / "capture" / "SpeakerWatcher.swift"


def snapshot_js() -> str:
    source = SWIFT.read_text()
    match = re.search(r'let googleMeetSnapshotJS = #"""\n(.*?)\n"""#', source, re.S)
    assert match, "snapshot script literal not found"
    snippet = re.search(r'let liveCallSnippetJS = #"""\n(.*?)\n"""#', source, re.S)
    assert snippet, "live-call snippet literal not found"
    return match.group(1).replace("\\#(liveCallSnippetJS)", snippet.group(1))
