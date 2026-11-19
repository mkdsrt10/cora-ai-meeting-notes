"""tools/eval_live_transcript.py meetings mode: live vs full word overlap per
track, Hinglish apart, delay from lag_ms; counts only in its output."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import db
import live_transcript
import paths

spec = importlib.util.spec_from_file_location(
    "eval_live_transcript", Path(__file__).resolve().parents[1] / "tools" / "eval_live_transcript.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def make(rec_id, full, live):
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording(rec_id, str(folder), rec_id, "2026-11-20T09:00:00+00:00", 60, 1, {})
    db.update_recording_data(rec_id, "diarization", {"segments": [
        {"speaker_id": who, "text": text, "start": "00:00", "end": "00:01"} for who, text in full]})
    (folder / live_transcript.FILE_NAME).write_text("".join(json.dumps(
        {"recording_id": rec_id, "track": track, "text": text, "final": True, "start": i, "end": i + 1, "lag_ms": lag})
        + "\n" for i, (track, text, lag) in enumerate(live)))


def test_overlap_counts():
    assert tool.overlap("We ship Friday.", "we ship on friday") == {"live_words": 3, "ref_words": 4, "recall": 0.75, "precision": 1.0}


def test_meetings_mode_reports_per_track_and_hinglish_apart():
    paths.ensure_data_dir()
    db.init_db()
    make("eval-en", [("You", "ship the plan friday"), ("SPEAKER_1", "sounds good to me")],
         [("mic", "ship the plan friday", 800), ("sys", "sounds good", 1200)])
    make("eval-hi", [("You", "budget discuss karenge")], [("mic", "budget discuss", 1500)])
    out = tool.meetings_mode(SimpleNamespace(ids=["eval-en", "eval-hi"], hinglish=["eval-hi"]))
    assert out["other"]["recordings"] == 1 and out["hinglish"]["recordings"] == 1
    assert out["other"]["overlap_mic"]["recall"] == 1.0
    assert out["other"]["overlap_sys"]["recall"] == 0.5
    assert out["hinglish"]["overlap_mic"]["recall"] == 0.667
    assert out["other"]["lag_ms_p50"] == 800 and out["other"]["lag_ms_p95"] == 1200
    assert "ship" not in json.dumps(out)
