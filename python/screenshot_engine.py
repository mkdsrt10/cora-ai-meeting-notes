#!/usr/bin/env python3
"""Screenshot & Slide OCR Engine for Cora.

Takes timestamped screenshots during meetings and automatically applies
Apple Vision native OCR (bin/mac-ocr) to index whiteboard notes, slides,
and shared screens for local structuring.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import paths

BIN_OCR = paths.BIN_DIR / "mac-ocr"
RECORDINGS_DIR = paths.RECORDINGS_DIR


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    m = s // 60
    sec = s % 60
    return f"{m:02d}:{sec:02d}"


def capture_and_ocr(folder: Path, elapsed_sec: Optional[float] = None) -> dict[str, Any]:
    """Capture a screen/slide image, save it with timestamp, and run local Apple Vision OCR."""
    screenshots_dir = folder / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    sec = elapsed_sec if elapsed_sec is not None else 0.0
    ts_label = format_timestamp(sec).replace(":", "m") + "s"
    image_path = screenshots_dir / f"slide_{ts_label}.png"
    text_path = screenshots_dir / f"slide_{ts_label}.txt"

    # Capture screen silently
    cmd_cap = ["/usr/sbin/screencapture", "-x", "-C", str(image_path)]
    subprocess.run(cmd_cap, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Run native Apple Vision OCR
    ocr_text = ""
    if BIN_OCR.exists() and image_path.exists():
        try:
            import ai_trace
            with ai_trace.span("ocr", "apple_vision.screenshot", provider="apple_vision", model="VNRecognizeTextRequest",
                               input={"image": ai_trace.file_fingerprint(image_path)},
                               recording_id=folder.name) as trace:
                res = subprocess.run([str(BIN_OCR), str(image_path)], capture_output=True, text=True, check=True)
                ocr_text = res.stdout.strip()
                trace.set_output(ocr_text, words=len(ocr_text.split()))
            text_path.write_text(ocr_text, encoding="utf-8")
        except Exception as e:
            ocr_text = f"[OCR Error: {e}]"

    entry = {
        "timestamp": format_timestamp(sec),
        "timestamp_seconds": round(sec, 1),
        "image_file": str(image_path.relative_to(folder)),
        "ocr_file": str(text_path.relative_to(folder)),
        "text": ocr_text,
        "word_count": len(ocr_text.split()),
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Append to slides_ocr.json index in the folder
    index_file = folder / "slides_ocr.json"
    existing = []
    if index_file.exists():
        try:
            existing = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    existing.append(entry)
    tmp_file = index_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_file.replace(index_file)

    return entry


class ScreenshotDaemon:
    """Background daemon taking periodic screenshots during active recording."""

    def __init__(self, folder: Path, start_time: Optional[float] = None, interval_seconds: float = 60.0):
        self.folder = folder
        self.start_time = start_time or time.time()
        self.interval = interval_seconds
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def _loop(self):
        while not self.stop_event.is_set():
            # Wait for interval or stop event
            if self.stop_event.wait(self.interval):
                break
            try:
                elapsed = time.time() - self.start_time
                capture_and_ocr(self.folder, elapsed_sec=elapsed)
            except Exception as e:
                print(f"[ScreenshotDaemon] capture failed: {e}", flush=True)

    def start(self):
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3.0)


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (RECORDINGS_DIR / "test_snapshot")
    target.mkdir(parents=True, exist_ok=True)
    print(f"Testing capture_and_ocr in: {target}")
    result = capture_and_ocr(target, elapsed_sec=15.0)
    print(f"Captured: {result['image_file']} at {result['timestamp']}")
    print(f"OCR Extracted ({result['word_count']} words):\n{result['text'][:300]}...")
