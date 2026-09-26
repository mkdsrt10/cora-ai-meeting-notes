#!/usr/bin/env python3
"""Restore two-track (mic + system) audio for recordings whose archive was
flattened to a single mixed stream, and build the playback mix.

Why: for a while the archive step mixed both tracks into one stream, which
destroys what speaker attribution needs (mic vs. system loudness per
segment) — every speaker came out as "You". The untouched originals are
still in inbox/, so this rebuilds audio.* from them.

Safe by default: prints what it would do. With --apply, each replaced file
is first moved to <recording>/versions/<stamp>-flattened-audio/.

    python tools/repair_audio_tracks.py            # dry run
    python tools/repair_audio_tracks.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paths  # noqa: E402
import voice_memo_pipeline as vmp  # noqa: E402

DURATION_TOLERANCE_S = 2.0


def source_for(folder: Path) -> Path | None:
    try:
        meta = json.loads((folder / "metadata.json").read_text())
    except (OSError, ValueError):
        return None
    candidates = [meta.get("source_file"), str(paths.INBOX_DIR / f"{meta.get('live_recording_id', '')}.mov")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually rewrite files (default: dry run)")
    parser.add_argument("--only", help="only recordings whose folder name contains this text")
    args = parser.parse_args()
    paths.ensure_data_dir()  # owner-only umask for everything this writes
    stamp = time.strftime("%Y%m%dT%H%M%S")
    restored = playback_built = skipped = 0

    for folder in sorted(p for p in paths.RECORDINGS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if args.only and args.only not in folder.name:
            continue
        audio = next((p for p in folder.iterdir() if p.is_file() and p.name.startswith("audio.")), None)
        if audio is None:
            continue
        streams = vmp.audio_stream_count(audio)
        if streams == 1:
            source = source_for(folder)
            if source is None or vmp.audio_stream_count(source) < 2:
                skipped += 1
                continue
            if abs(vmp.probe_audio(source) - vmp.probe_audio(audio)) > DURATION_TOLERANCE_S:
                print(f"SKIP  {folder.name}: inbox source duration differs; not the same recording")
                skipped += 1
                continue
            print(f"{'FIX ' if args.apply else 'WOULD FIX'} {folder.name}: restore 2 tracks from {source.name}")
            if args.apply:
                backup = folder / "versions" / f"{stamp}-flattened-audio"
                backup.mkdir(parents=True, exist_ok=True)
                rebuilt = folder / f".{audio.name}.repair"
                if not vmp.clean_track_audio(source, rebuilt):
                    shutil.copy2(source, rebuilt)
                shutil.move(str(audio), backup / audio.name)
                rebuilt.replace(folder / f"audio{source.suffix.lower()}")
                audio = folder / f"audio{source.suffix.lower()}"
            restored += 1
            streams = 2
        playback = folder / vmp.PLAYBACK_NAME
        if streams >= 2 and not playback.exists():
            if args.apply:
                if vmp.build_playback_mix(audio, playback):
                    playback_built += 1
            else:
                playback_built += 1

    verb = "" if args.apply else "would be "
    print(f"\n{restored} recording(s) {verb}restored to two tracks, {playback_built} playback mix(es) {verb}built, "
          f"{skipped} single-track recording(s) left as-is (no two-track source).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
