"""What happens once a Recording's artifacts are saved, whichever engine
processed it: the after_meeting Hook, then source-audio cleanup.

Callers run this after releasing the processing lock and after leaving the
pipeline's trace run, so a Plugin may read the audio, start its own processing
(its Text model calls get their own spans) and never deadlocks on the lock.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import db


def finish(recording_id: str, source_audio: Iterable[Path] = ()) -> dict[str, bool]:
    """Store the Recording's core Action items, run the after_meeting Hook for `recording_id` (the Recording that now
    holds the result, e.g. a merged Continuation's parent), then delete
    `source_audio` when retain_audio is off. Cleanup runs even if the Hook
    host itself fails. Returns the Hook's {plugin_id: succeeded}."""
    import action_items
    import plugin_host
    try:
        try:
            action_items.sync(recording_id)  # core records first: Hooks read them
        except Exception as exc:  # noqa: BLE001 - never blocks the Hooks or cleanup
            print(f"[Post-processing] Action items sync failed for {recording_id} ({type(exc).__name__})", flush=True)
        return plugin_host.run_hook("after_meeting", recording_id)
    finally:
        # Audio retention is an explicit opt-out (default: keep it) set during
        # onboarding. Deleting the source audio also removes playback/seek for
        # this Recording in the UI, not just the processing dependency.
        if not db.get_setting("retain_audio", True):
            for path in source_audio:
                path.unlink(missing_ok=True)
            print(f"[Post-processing] Deleted source audio for {recording_id} (retain_audio is off)", flush=True)
