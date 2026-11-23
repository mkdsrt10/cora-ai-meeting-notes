#!/usr/bin/env python3
"""On-device Whisper live engine (MLX): Hinglish-capable live captions with a
local Whisper model such as Tara or Whisper Turbo Hinglish. Experimental.

dual-capture runs this in place of capture/live-engine, one process per track,
with the same contract as python/live_cloud.py: 16 kHz mono Float32 LE on stdin
until EOF (or --wav), LIVE_* lines on stdout (see capture/LiveEngine.swift).

    python live_whisper.py --track mic|sys --model <hf-repo-or-path> [--wav FILE [--realtime]]

How it works:
- An energy VAD opens a segment on speech and closes it after CLOSE_SILENCE_S of
  silence, or at MAX_SEGMENT_S.
- While a segment is open, the whole segment is decoded again every STEP_S of new
  audio (or as soon as the previous decode finishes, when decoding is slower);
  the hypotheses go through the same stabilizer as the other engines, so stable
  words are never retracted. Closing a segment decodes it once more for the final.
- Decode settings match the batch path (pipeline/transcribe.py): language "en",
  capped temperature ladder, explicit thresholds, then collapse_repetition_loops
  and Devanagari -> Roman (pipeline/romanize.transliterate).

Never leaves this Mac: the Hugging Face hub is put offline before the model
loads, so a model that is not already downloaded is LIVE_ERROR model_missing
(exit 3), never a download.
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_cloud import Stabilizer, emit_line  # noqa: E402

SAMPLE_RATE = 16000
CHUNK = 1600                 # 100 ms
STEP_S = 1.0                 # re-decode the open segment after this much new audio
CLOSE_SILENCE_S = 0.6
MAX_SEGMENT_S = 12.0
PRE_ROLL_S = 0.3
MIN_SPEECH_S = 0.3           # shorter blips are dropped, not decoded
ENGINE = "mlx_whisper"


def _rms(chunk) -> float:
    import numpy as np
    return float(np.sqrt(np.mean(np.square(chunk)))) if len(chunk) else 0.0


class Vad:
    """Energy VAD with an adaptive noise floor (enough for a close mic and a
    clean system track; the batch path keeps its own VAD)."""

    def __init__(self, min_threshold: float = 0.006, ratio: float = 3.0):
        self.floor = min_threshold / ratio
        self.min_threshold, self.ratio = min_threshold, ratio

    def speech(self, chunk) -> bool:
        level = _rms(chunk)
        is_speech = level > max(self.min_threshold, self.floor * self.ratio)
        if not is_speech:
            self.floor = 0.95 * self.floor + 0.05 * level
        return is_speech


def mlx_recognizer(model: str) -> Callable:
    """audio (float32 numpy) -> text, with the batch path's decode settings."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    import mlx_whisper
    from mlx_whisper.transcribe import ModelHolder
    from pipeline.romanize import transliterate
    from pipeline.transcribe import collapse_repetition_loops
    import mlx.core as mx
    try:
        ModelHolder.get_model(model, mx.float16)
    except Exception as exc:
        raise FileNotFoundError(model) from exc

    def recognize(audio) -> str:
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=model, language="en", condition_on_previous_text=False,
            temperature=(0.0, 0.2, 0.4), compression_ratio_threshold=2.4, logprob_threshold=-1.0,
            no_speech_threshold=0.5, verbose=None)
        text = " ".join(s.get("text", "").strip() for s in result.get("segments") or [])
        return transliterate(collapse_repetition_loops(text))
    return recognize


class WhisperLive:
    def __init__(self, track: str, recognize: Callable, emit: Callable[[str, dict], None] = emit_line,
                 clock: Callable[[], float] = time.monotonic, vad: Optional[Vad] = None):
        import numpy as np
        self.np = np
        self.track, self.recognize, self.emit, self.clock = track, recognize, emit, clock
        self.vad = vad or Vad()
        self.samples = 0                      # track samples seen
        self.arrival: dict[int, float] = {}   # chunk index -> wall time it reached us
        self.pre: list = []                   # pre-roll chunks while idle
        self.open: Optional[list] = None      # chunks of the open segment
        self.open_start = 0.0
        self.silence_s = 0.0
        self.speech_chunks = 0                # chunks the VAD called speech in the open segment
        self.decoded_at = 0.0                 # segment length at the last decode
        self.seg = 0
        self.last_final_end = 0.0
        self.stabilizer = Stabilizer()
        self.decodes = 0

    # --- helpers
    def _now_s(self) -> float:
        return self.samples / SAMPLE_RATE

    def _lag_ms(self, end_s: float) -> int:
        index = max(0, int(round(end_s * SAMPLE_RATE / CHUNK)) - 1)
        at = self.arrival.get(index)
        return int(max(0.0, self.clock() - at) * 1000) if at is not None else 0

    def _audio(self):
        return self.np.concatenate(self.open).astype(self.np.float32)

    def _decode(self) -> str:
        self.decodes += 1
        return self.recognize(self._audio()).strip()

    # --- input
    def feed(self, chunk, arrived: Optional[float] = None, decode: bool = True) -> None:
        """One 100 ms chunk. decode=False defers decoding (the caller is behind
        real time and more audio is already waiting)."""
        index = self.samples // CHUNK
        self.arrival[index] = arrived if arrived is not None else self.clock()
        self.arrival.pop(index - 3000, None)
        self.samples += len(chunk)
        speech = self.vad.speech(chunk)
        if self.open is None:
            self.pre = (self.pre + [chunk])[-int(PRE_ROLL_S * 10):]
            if speech:
                self.open, self.pre = self.pre, []
                self.open_start = max(self.last_final_end, self._now_s() - len(self.open) * CHUNK / SAMPLE_RATE)
                self.silence_s, self.decoded_at, self.speech_chunks = 0.0, 0.0, 1
                self.stabilizer.reset()
            return
        self.open.append(chunk)
        self.speech_chunks += speech
        self.silence_s = 0.0 if speech else self.silence_s + CHUNK / SAMPLE_RATE
        length = len(self.open) * CHUNK / SAMPLE_RATE
        if self.silence_s >= CLOSE_SILENCE_S or length >= MAX_SEGMENT_S:
            self.close()
        elif decode and length - self.decoded_at >= STEP_S:
            self.partial()

    def partial(self) -> None:
        length = len(self.open) * CHUNK / SAMPLE_RATE
        self.decoded_at = length
        if self.stabilizer.accept(self._decode()):
            end = self._now_s()
            self.emit("LIVE_PARTIAL", {"track": self.track, "seg": self.seg, "start": round(self.open_start, 3),
                                       "end": round(end, 3), "text": " ".join(self.stabilizer.stable),
                                       "lag_ms": self._lag_ms(end)})

    def close(self) -> None:
        if self.open is None:
            return
        speech_s = self.speech_chunks * CHUNK / SAMPLE_RATE
        end = round(self._now_s() - self.silence_s, 3)
        if speech_s >= MIN_SPEECH_S:
            text = self.stabilizer.finalize(self._decode())
            if text:
                self.emit("LIVE_FINAL", {"track": self.track, "seg": self.seg, "start": round(self.open_start, 3),
                                         "end": end, "text": text, "lag_ms": self._lag_ms(end)})
                self.seg += 1
        self.last_final_end = max(self.last_final_end, end)
        self.open, self.pre = None, []
        self.stabilizer.reset()

    def finish(self) -> None:
        self.close()


def _wav_chunks(path: str):
    import numpy as np
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    for i in range(0, len(audio), CHUNK):
        yield audio[i:i + CHUNK]


def _stdin_chunks(stdin):
    import numpy as np
    while True:
        data = stdin.read(CHUNK * 4)
        if not data:
            return
        yield np.frombuffer(data[:len(data) // 4 * 4], dtype=np.float32)


def run(track: str, chunks, recognize_factory: Callable[[], Callable], model: str,
        emit: Callable[[str, dict], None] = emit_line, realtime: bool = False) -> int:
    try:
        recognize = recognize_factory()
    except FileNotFoundError:
        emit("LIVE_ERROR", {"track": track, "code": "model_missing"})
        return 3
    except Exception as exc:
        emit("LIVE_ERROR", {"track": track, "code": "model_load_failed_" + type(exc).__name__.lower()[:40]})
        return 3
    emit("LIVE_ENGINE", {"track": track, "engine": ENGINE, "model": model})
    engine = WhisperLive(track, recognize, emit)
    # A reader thread stamps each chunk's arrival (paced at real time for --wav
    # --realtime), so a decode slower than real time shows up as lag_ms and the
    # engine skips partials to catch up instead of falling further behind.
    inbox: "queue.Queue" = queue.Queue()

    def reader():
        started = time.monotonic()
        for i, chunk in enumerate(chunks):
            if realtime:
                time.sleep(max(0.0, started + (i + 1) * CHUNK / SAMPLE_RATE - time.monotonic()))
            inbox.put((chunk, time.monotonic()))
        inbox.put(None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        while (item := inbox.get()) is not None:
            engine.feed(*item, decode=inbox.empty())
        engine.finish()
    except Exception as exc:
        emit("LIVE_ERROR", {"track": track, "code": "decode_failed_" + type(exc).__name__.lower()[:40]})
        return 4
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--track", choices=("mic", "sys"), required=True)
    parser.add_argument("--model", required=True, help="Hugging Face repo id or local MLX model folder")
    parser.add_argument("--wav", help="read this file instead of stdin (test and eval seam)")
    parser.add_argument("--realtime", action="store_true", help="pace --wav at real time")
    args = parser.parse_args()
    chunks = _wav_chunks(args.wav) if args.wav else _stdin_chunks(sys.stdin.buffer)
    return run(args.track, chunks, lambda: mlx_recognizer(args.model), args.model, realtime=args.realtime)


if __name__ == "__main__":
    raise SystemExit(main())
