"""Live transcript, seam 3 (MCP): cora_get_live_transcript returns only the
lines after the caller's cursor, defaults to the meeting being recorded, and
answers bad or unknown ids like the other read tools (docs/specs/live-transcript.md, T4)."""
import asyncio
import json

import pytest

import db
import live_transcript
import mcp_server
import paths


@pytest.fixture(autouse=True)
def data():
    paths.ensure_data_dir()
    db.init_db()


def write(key, *texts, start=0):
    path = live_transcript.inbox_path(key)
    with path.open("a") as fh:
        for i, text in enumerate(texts):
            fh.write(json.dumps({"recording_id": key, "track": "mic" if i % 2 == 0 else "sys", "speaker": None,
                                 "start": start + i, "end": start + i + 1, "text": text, "final": True,
                                 "engine": "speech_transcriber", "seg": i}) + "\n")


def tool(**kwargs):
    return mcp_server.cora_get_live_transcript(**kwargs)


def test_delta_reads_return_only_new_lines_and_empty_when_nothing_new():
    key = "meeting_2026-11-20T16-00-00-000Z"
    db.create_pending_recording(key, source_stem=key, recorded_at="2026-11-20T16:00:00", status="recording")
    write(key, "Morning all.", "Morning.")
    first = tool()  # defaults to the meeting being recorded
    assert first["recording_id"] == key and first["recording"] is True
    assert [(x["speaker"], x["text"]) for x in first["lines"]] == [("You", "Morning all."), ("Them", "Morning.")]
    again = tool(since_cursor=first["cursor"])
    assert again["lines"] == [] and again["cursor"] == first["cursor"]
    write(key, "Let us start.", start=2)
    delta = tool(recording_id=key, since_cursor=first["cursor"])
    assert [x["text"] for x in delta["lines"]] == ["Let us start."]
    # a cursor from another recording reads from the start
    assert len(tool(recording_id=key, since_cursor="other_meeting@999")["lines"]) == 3


def test_no_active_recording_and_unknown_ids_are_refused_like_other_tools():
    for rec in db.get_all_recordings():
        if rec.get("status") in ("recording", "paused"):
            db.set_pending_recording_status(rec["id"], "processing")
    with pytest.raises(ValueError, match="No meeting is being recorded"):
        tool()
    with pytest.raises(ValueError, match="Recording not found"):
        tool(recording_id="meeting_that_never_was")
    with pytest.raises(ValueError, match="Recording not found"):
        tool(recording_id="../../etc/passwd")
    with pytest.raises(ValueError, match="Recording not found"):
        mcp_server.cora_get_transcript("meeting_that_never_was")


def test_a_recording_without_live_text_says_so():
    key = "meeting_2026-11-20T17-00-00-000Z"
    db.create_pending_recording(key, source_stem=key, recorded_at="2026-11-20T17:00:00", status="processing")
    out = tool(recording_id=key)
    assert out["lines"] == [] and out["recording"] is False and "No Live transcript" in out["note"]


def test_registered_on_the_mcp_server_next_to_the_other_reads():
    names = [t.name for t in asyncio.run(mcp_server.mcp.list_tools())]
    assert "cora_get_live_transcript" in names and "cora_get_transcript" in names
    key = "meeting_2026-11-20T18-00-00-000Z"
    db.create_pending_recording(key, source_stem=key, recorded_at="2026-11-20T18:00:00", status="recording")
    write(key, "Through the protocol.")
    result = asyncio.run(mcp_server.mcp.call_tool("cora_get_live_transcript", {"recording_id": key}))
    assert "Through the protocol." in json.dumps(result, default=str)
