"""The Processing queue posts /api/process-recording with the live recording
id it captured under; the route resolves it to the archived Recording."""
import sys
import types

import db
import paths
from api.routes import recordings


class _Req:
    def send_json(self, payload, status=200):
        self.payload, self.status = payload, status


def test_live_id_resolves_to_archived_folder(monkeypatch):
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "2026-11-01_09-00-00_meeting_live_1234abcd"
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording(folder.name, str(folder), "t", "2026-11-01T09:00:00+00:00", 1.0, 1,
                        {"live_recording_id": "meeting_live"})
    seen = []
    fake_local = types.SimpleNamespace(process_recording_local=lambda f: seen.append(f.name) or {
        "diarization": {}, "speaker_profiles": [], "call_summary": {}})
    monkeypatch.setitem(sys.modules, "local_meeting_pipeline", fake_local)
    req = _Req()
    recordings.post_api_process_recording(req, "/api/process-recording", {"id": "meeting_live"})
    assert req.status == 200
    assert seen == [folder.name]
