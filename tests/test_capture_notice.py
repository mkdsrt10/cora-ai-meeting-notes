"""A Call recorded with no Participants while Accessibility was not granted:
Electron posts a capture notice for the live id at stop; the Recording shows
it (recording-notices.js) with a button to the Accessibility pane."""
import pytest

import db
import paths
from api import views
from api.routes import recordings as routes


class Req:
    def send_json(self, body, status=200):
        self.reply = (status, body)


@pytest.fixture
def archived():
    paths.ensure_data_dir()
    db.init_db()
    folder = paths.RECORDINGS_DIR / "ax-call"
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording("ax-call", str(folder), "ax-call", "2026-11-13T10:00:00+00:00", 1.0, 1,
                        {"live_recording_id": "meeting_ax"})
    return folder


def test_a_notice_posted_for_the_live_id_shows_on_the_archived_recording(archived):
    req = Req()
    routes.post_api_recording_capture_notice(req, "", {"id": "meeting_ax", "notice": "ax_untrusted"})
    assert req.reply == (200, {"ok": True})
    assert views.recording_item(archived)["capture_notice"] == "ax_untrusted"


def test_an_unknown_notice_or_recording_is_refused(archived):
    with pytest.raises(ValueError):
        routes.post_api_recording_capture_notice(Req(), "", {"id": "ax-call", "notice": "anything"})
    with pytest.raises(FileNotFoundError):
        routes.post_api_recording_capture_notice(Req(), "", {"id": "nope", "notice": "ax_untrusted"})


def test_archiving_carries_the_notice_from_the_live_row():
    import inspect
    import voice_memo_pipeline
    source = inspect.getsource(voice_memo_pipeline.process)
    assert 'metadata["capture_notice"] = pending_capture_notice' in source
