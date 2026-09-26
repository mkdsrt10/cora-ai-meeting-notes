"""Audio/screenshot media and the static web UI."""
from __future__ import annotations
import re
import urllib.parse

from api.router import route
import re
from api.core import INBOX, RECORDINGS, STATIC, safe_folder


@route("GET", '/media/', prefix=True)
def get_media_prefix(req, path: str, query: dict) -> None:
    parts = [urllib.parse.unquote(p) for p in path.split("/")[2:]]
    if len(parts) != 2 or not re.fullmatch(r"audio\.[A-Za-z0-9]+|playback\.m4a", parts[1]):
        raise ValueError("Invalid media path")
    media = safe_folder(parts[0]) / parts[1]
    return req.serve_file(media)


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
