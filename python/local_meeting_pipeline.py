#!/usr/bin/env python3
"""Compatibility shim — the pipeline now lives in the `pipeline` package.

Existing imports (`import local_meeting_pipeline as lmp; lmp.process_recording_local(...)`)
keep working: every name from the package modules is re-exported here. New code
should import from `pipeline.<module>` directly; see pipeline/__init__.py for
the module map.
"""
from __future__ import annotations

from pipeline import audio, common, config, llm, notes, runner, speakers, transcribe, vocabulary

for _module in (config, common, audio, vocabulary, llm, transcribe, speakers, notes, runner):
    globals().update({k: v for k, v in vars(_module).items() if not k.startswith("__")})
del _module

if __name__ == "__main__":
    runner.main()
