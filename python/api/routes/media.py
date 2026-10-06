"""Audio/screenshot media and the static web UI."""
from __future__ import annotations
import re
import urllib.parse

from api.router import route
import re
import db
import paths
from api.core import INBOX, RECORDINGS, STATIC, safe_folder, safe_id


@route("GET", '/media/', prefix=True)
def get_media_prefix(req, path: str, query: dict) -> None:
    parts = [urllib.parse.unquote(p) for p in path.split("/")[2:]]
    if len(parts) != 2 or not re.fullmatch(r"audio\.[A-Za-z0-9]+|playback\.m4a", parts[1]):
        raise ValueError("Invalid media path")
    media = safe_folder(parts[0]) / parts[1]
    return req.serve_file(media)


LIVE_PREVIEW_DIR = paths.DATA_DIR / "exports" / "live-preview"


@route("GET", '/api/recording/live-audio')
def get_api_recording_live_audio(req, path: str, query: dict) -> None:
    """Lets you listen to a recording that's been stopped but not yet
    archived — the gap (often several minutes) between hitting Stop on a
    pause/resume or "Continue this meeting" segment and the pipeline
    finishing, where the audio otherwise isn't reachable from the UI at
    all. Only once capture has actually stopped: the raw .mov's container
    index isn't finalized while dual-capture still has it open, so it
    isn't reliably playable (or even fully probable) before then."""
    recording_id = safe_id((query.get("id") or [""])[0])
    row = db.get_recording(recording_id)
    if not row:
        raise FileNotFoundError(recording_id)
    if row.get("status") == "recording":
        return req.send_json({"error": "Still recording — available once recording stops."}, 409)

    source = INBOX / f"{recording_id}.mov"
    if not source.is_file():
        raise FileNotFoundError(f"No audio found for {recording_id}")

    LIVE_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    cached = LIVE_PREVIEW_DIR / f"{recording_id}.m4a"
    if not cached.is_file() or cached.stat().st_mtime < source.stat().st_mtime:
        import voice_memo_pipeline as vmp
        if not vmp.build_playback_mix(source, cached):
            # Single-track source (or ffmpeg failed) — fall back to the raw
            # file; a browser will at least play the mic track.
            return req.serve_file(source, cache=False)
    return req.serve_file(cached, cache=False)


@route("GET", '/media-screenshot/', prefix=True)
def get_media_screenshot_prefix(req, path: str, query: dict) -> None:
    parts = [urllib.parse.unquote(p) for p in path.split("/")[2:]]
    if (
        len(parts) != 2
        or not re.fullmatch(r"[A-Za-z0-9._-]+", parts[0])
        or not re.fullmatch(r"[A-Za-z0-9._-]+\.png", parts[1])
    ):
        raise ValueError("Invalid media path")
    rec_id, filename = parts
    # A screenshot taken while still recording lives under
    # inbox/; once archived it's copied into the recording's
    # own folder — check both, since either can be current
    # depending on where this recording is in its lifecycle.
    for candidate in (INBOX / f"{rec_id}_screenshots" / filename, RECORDINGS / rec_id / "screenshots" / filename):
        resolved = candidate.resolve()
        if resolved.is_file() and (
            resolved.is_relative_to(INBOX.resolve()) or resolved.is_relative_to(RECORDINGS.resolve())
        ):
            return req.serve_file(resolved)
    raise FileNotFoundError(filename)


def serve_static(req, path: str, query: dict) -> None:
    """Fallback for GET: the web UI's own files."""
    target = STATIC / ("index.html" if path in {"/", ""} else path.lstrip("/"))
    target = target.resolve()
    target.relative_to(STATIC.resolve())
    return req.serve_file(target, cache=False)
