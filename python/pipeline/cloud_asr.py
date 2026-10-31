"""Which speech engine is selected (Settings > Transcription engine).

"local" (default) is on-device MLX Whisper. "gemini" sends speech audio to
Google Gemini in multi-minute windows (pipeline/windowed.py), so it is off
under enterprise lockdown no matter what Settings says, and the recording's
privacy note says so (runner._provenance).
"""
from __future__ import annotations


ENGINES = ("local", "gemini")


def engine() -> str:
    import policy
    import processing
    options = processing.CURRENT.get()
    value = options["transcription"] if options else processing.resolve()["transcription"]
    if value not in ENGINES or policy.lockdown_enabled():
        return "local"  # lockdown overrides whatever Settings says
    return value
