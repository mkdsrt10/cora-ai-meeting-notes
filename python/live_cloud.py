#!/usr/bin/env python3
"""Cloud live engine: Google Cloud Speech-to-Text v2, Chirp streaming, on the
user's own Vertex project (docs/specs/live-transcript.md, T5; design §13.8 (a)).

dual-capture runs this in place of capture/live-engine, one process per track,
with the same contract: 16 kHz mono Float32 LE on stdin until EOF, LIVE_* lines
on stdout (see capture/LiveEngine.swift). So the session, the JSONL record, the
captions and the MCP read are the same for both engines.

    python live_cloud.py --track mic|sys

Rules (never relaxed here):
- Only on the Vertex backend, with its credentials (service account or ADC).
  The AI Studio key path has no Speech-to-Text: refused (code not_vertex).
- Through the outbound policy: refused under enterprise lockdown (code lockdown).
- Never falls back to the on-device engine, and the on-device engine never
  upgrades to this: on any failure the track reports LIVE_ERROR and captions pause.
- Data logging: Speech-to-Text data logging is a project-level opt-in that Cora
  never turns on; requests use the default recognizer with inline config.
- A stream is rotated before the API's per-stream limit and the new one starts
  with the last OVERLAP_S of audio again; lines from the overlap that were
  already final are dropped, so nothing is duplicated or lost at the seam.

Region: Chirp streaming needs a regional endpoint. The Vertex location is used
when it is one of CHIRP_REGIONS, else config.json `live_cloud_location`, else
us-central1. Languages: config.json `live_cloud_languages` (default ["en-US"]).
Checked against Google's docs (Nov 2026): v2 streams end at 5 min (409), 25 KB
of audio per request, Chirp 2 in us-central1 / europe-west4 / asia-southeast1;
Chirp 2's listed languages include en-IN but not hi-IN, so Hinglish quality is a
measured manual check, as is the project's Google Cloud agreement.
"""
from __future__ import annotations

import argparse
import array
import json
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

SAMPLE_RATE = 16000
MODEL = "chirp_2"
# Regions with Chirp 2 streaming as last checked; verify for the project (manual check).
CHIRP_REGIONS = ("us-central1", "europe-west4", "asia-southeast1")
DEFAULT_REGION = "us-central1"
STREAM_LIMIT_S = 290.0      # Speech-to-Text v2 ends a stream at ~5 min of audio; rotate before
OVERLAP_S = 1.5
ENGINE = "chirp_2"


# --- Policy -------------------------------------------------------------------

def refusal() -> Optional[str]:
    """None when cloud live may run now, else the code it is refused with."""
    import policy
    if policy.lockdown_enabled():
        return "lockdown"
    import credentials
    status = credentials.get_public_status()
    if status.get("provider") != "vertex":
        return "not_vertex"
    if not status.get("vertex_project"):
        return "no_project"
    if status.get("vertex_auth_type") == "api_key":
        return "auth_unsupported"
    return None


def team_build() -> bool:
    import os
    return os.environ.get("CORA_BUILD_VARIANT") == "team"


def _config() -> dict[str, Any]:
    import paths
    try:
        return json.loads(paths.CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def offered() -> bool:
    """Whether Settings offers Cloud live at all: Vertex backend, no lockdown,
    and in the Team build only when config.json says `live_cloud_offered`."""
    if refusal() in ("lockdown", "not_vertex"):
        return False
    return not team_build() or bool(_config().get("live_cloud_offered"))


def region(vertex_location: str) -> str:
    if vertex_location in CHIRP_REGIONS:
        return vertex_location
    configured = str(_config().get("live_cloud_location") or "")
    return configured if re.fullmatch(r"[a-z]+-[a-z]+\d", configured) else DEFAULT_REGION


def languages() -> list[str]:
    value = _config().get("live_cloud_languages")
    if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
        return value[:3]
    return ["en-US"]


# --- Stabilizer (same rule as capture/LiveEngine.swift) ------------------------

def _key(word: str) -> str:
    return re.sub(r"[^\w']", "", word.lower())


class Stabilizer:
    def __init__(self):
        self.stable: list[str] = []
        self._previous: list[str] = []

    def reset(self):
        self.stable, self._previous = [], []

    def accept(self, hypothesis: str) -> bool:
        current = hypothesis.split()
        previous, self._previous = self._previous, current
        if not current or not previous:
            return False
        agreed = 0
        while agreed < min(len(previous), len(current) - 1) and _key(previous[agreed]) == _key(current[agreed]):
            agreed += 1
        if agreed <= len(self.stable):
            return False
        if any(_key(a) != _key(b) for a, b in zip(self.stable, current)):
            return False
        self.stable += current[len(self.stable):agreed]
        return True

    def finalize(self, final: str) -> str:
        words = final.split()
        if len(words) >= len(self.stable) and all(_key(a) == _key(b) for a, b in zip(self.stable, words)):
            return " ".join(words)
        return " ".join(self.stable + words[len(self.stable):])


# --- Engine ---------------------------------------------------------------------

def _seconds(duration: Any) -> float:
    """A protobuf Duration, a datetime.timedelta (proto-plus) or a number."""
    if duration is None:
        return 0.0
    if hasattr(duration, "total_seconds"):
        return float(duration.total_seconds())
    if hasattr(duration, "seconds"):
        return float(duration.seconds) + float(getattr(duration, "nanos", 0)) / 1e9
    return float(duration)


Transport = Callable[[], tuple[Callable[[Optional[bytes]], None], Iterable[Any]]]


class CloudLive:
    """One track. `transport()` opens a stream: (send(int16 bytes | None to
    end), responses). Responses carry `.results`, each with `.alternatives[0]
    .transcript`, `.is_final` and `.result_end_offset` (stream-relative)."""

    def __init__(self, track: str, transport: Transport, emit: Callable[[str, dict], None],
                 *, stream_limit: float = STREAM_LIMIT_S, overlap: float = OVERLAP_S,
                 now: Callable[[], float] = time.monotonic):
        self.track, self.transport, self.emit = track, transport, emit
        self.stream_limit, self.overlap, self.now = stream_limit, overlap, now
        self.lock = threading.Lock()
        self.stabilizer = Stabilizer()
        self.seg = 0
        self.consumed = 0                 # samples received
        self.arrivals: list[tuple[int, float]] = []
        self.last_final_end = 0.0
        self.seg_start: Optional[float] = None
        self.tail = b""                   # last `overlap` seconds of int16 audio
        self.stream_base = 0.0            # track seconds where the current stream's audio starts
        self.stream_sent = 0              # samples sent on the current stream
        self.send: Optional[Callable[[Optional[bytes]], None]] = None
        self.readers: list[threading.Thread] = []
        self.failed: Optional[str] = None
        self.streams = 0

    # stdin side
    def feed(self, f32: bytes) -> None:
        if self.failed:
            return
        samples = array.array("f")
        samples.frombytes(f32[: len(f32) - len(f32) % 4])
        pcm = array.array("h", (max(-32768, min(32767, int(s * 32767))) for s in samples)).tobytes()
        if self.send is None or self.stream_sent >= int(self.stream_limit * SAMPLE_RATE):
            self._rotate()   # before counting this chunk: the new stream starts at the overlap
        with self.lock:
            self.consumed += len(samples)
            self.arrivals.append((self.consumed, self.now()))
            if len(self.arrivals) > 4000:
                del self.arrivals[:2000]
        if self.failed or self.send is None:
            return
        try:
            self.send(pcm)
        except Exception:
            self._fail("stream_send_failed")
            return
        self.stream_sent += len(samples)
        keep = int(self.overlap * SAMPLE_RATE) * 2
        self.tail = (self.tail + pcm)[-keep:] if keep else b""

    def _rotate(self) -> None:
        """Close the current stream (its last results still arrive) and open the
        next one, starting with the overlap audio."""
        old = self.send
        if old is not None:
            try:
                old(None)
            except Exception:
                pass
        try:
            send, responses = self.transport()
        except Exception:
            self._fail("stream_open_failed")
            return
        self.streams += 1
        overlap = len(self.tail) // 2
        base = (self.consumed - overlap) / SAMPLE_RATE
        self.stream_base, self.stream_sent, self.send = base, overlap, send
        previous = self.readers[-1] if self.readers else None
        reader = threading.Thread(target=self._read, args=(responses, base, previous), daemon=True)
        reader.start()
        self.readers.append(reader)
        if self.tail:
            try:
                send(self.tail)
            except Exception:
                self._fail("stream_send_failed")

    def _read(self, responses: Iterable[Any], base: float, previous: Optional[threading.Thread] = None) -> None:
        # The old stream's last results come first: a final it still owes
        # must be known before the overlap repeats it on this stream.
        if previous is not None:
            previous.join(timeout=10)
        try:
            for response in responses:
                for result in list(getattr(response, "results", []) or []):
                    alternatives = list(getattr(result, "alternatives", []) or [])
                    text = (alternatives[0].transcript if alternatives else "").strip()
                    end = base + _seconds(getattr(result, "result_end_offset", None))
                    self._handle(text, end, bool(getattr(result, "is_final", False)))
        except Exception as exc:
            # A stream we already rotated away from may end with an error; only the live one matters.
            if base == self.stream_base:
                self._fail("stream_error_" + type(exc).__name__.lower()[:40])

    def _lag_ms(self, t: float) -> int:
        sample = int(t * SAMPLE_RATE)
        hit = next((a for a in self.arrivals if a[0] >= sample), self.arrivals[-1] if self.arrivals else None)
        return max(0, int((self.now() - hit[1]) * 1000)) if hit else 0

    def _handle(self, text: str, end: float, final: bool) -> None:
        with self.lock:
            audio_end = self.consumed / SAMPLE_RATE
            if final and end <= self.last_final_end + 0.05:
                return  # already final before the stream rotated (overlap)
            start = max(self.seg_start if self.seg_start is not None else self.last_final_end, self.last_final_end)
            end = max(start, min(end, max(audio_end, start)))
            if final:
                out = self.stabilizer.finalize(text)
                if out.split():
                    self._line("LIVE_FINAL", start, end, out)
                    self.last_final_end = end
                    self.seg += 1
                self.stabilizer.reset()
                self.seg_start = None
            elif text and self.stabilizer.accept(text):
                if self.seg_start is None:
                    self.seg_start = start
                self._line("LIVE_PARTIAL", start, end, " ".join(self.stabilizer.stable))

    def _line(self, kind: str, start: float, end: float, text: str) -> None:
        self.emit(kind, {"track": self.track, "seg": self.seg, "start": round(start, 3), "end": round(end, 3),
                         "text": text, "lag_ms": self._lag_ms(end)})

    def _fail(self, code: str) -> None:
        if self.failed:
            return
        self.failed = code
        self.emit("LIVE_ERROR", {"track": self.track, "code": code})

    def finish(self, timeout: float = 10.0) -> None:
        if self.send is not None:
            try:
                self.send(None)
            except Exception:
                pass
        deadline = time.monotonic() + timeout
        for reader in self.readers:
            reader.join(max(0.0, deadline - time.monotonic()))


# --- Google transport -------------------------------------------------------------

def google_transport() -> Transport:
    """Speech-to-Text v2 streaming with Chirp, on the configured Vertex project.
    Raises RuntimeError when credentials or the SDK are missing."""
    import credentials
    from google.api_core.client_options import ClientOptions
    from google.cloud import speech_v2
    from google.cloud.speech_v2.types import cloud_speech as cs

    status = credentials.get_public_status()
    project = status.get("vertex_project")
    location = region(status.get("vertex_location") or "")
    creds = vertex_credentials()
    client = speech_v2.SpeechClient(credentials=creds,
                                    client_options=ClientOptions(api_endpoint=f"{location}-speech.googleapis.com"))
    recognizer = f"projects/{project}/locations/{location}/recognizers/_"
    config = cs.RecognitionConfig(
        explicit_decoding_config=cs.ExplicitDecodingConfig(
            encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16, sample_rate_hertz=SAMPLE_RATE,
            audio_channel_count=1),
        language_codes=languages(), model=MODEL,
        features=cs.RecognitionFeatures(enable_automatic_punctuation=True))
    streaming = cs.StreamingRecognitionConfig(
        config=config, streaming_features=cs.StreamingRecognitionFeatures(interim_results=True))

    def open_stream():
        chunks: "queue.Queue[Optional[bytes]]" = queue.Queue()

        def requests():
            yield cs.StreamingRecognizeRequest(recognizer=recognizer, streaming_config=streaming)
            while (chunk := chunks.get()) is not None:
                for i in range(0, len(chunk), 16000):   # 0.5 s per request: under the 25 KB audio cap
                    yield cs.StreamingRecognizeRequest(audio=chunk[i:i + 16000])
        return chunks.put, client.streaming_recognize(requests=requests())
    return open_stream


def vertex_credentials():
    """google.auth credentials for the Vertex backend: the saved service
    account, else Application Default Credentials (same order as Gemini)."""
    import credentials
    import google.auth
    from google.oauth2 import service_account
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    sa_json = credentials._keychain_get("vertex_service_account_json") or \
        credentials._read_secure_file().get("vertex_service_account_json")
    status = credentials.get_public_status()
    if status.get("vertex_auth_type") == "service_account" and sa_json:
        return service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
    creds, _ = google.auth.default(scopes=scopes)
    return creds


# --- Process entry ---------------------------------------------------------------

_out = threading.Lock()


def emit_line(kind: str, payload: dict) -> None:
    with _out:
        sys.stdout.write(f"{kind} {json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n")
        sys.stdout.flush()


def run(track: str, stdin, transport_factory: Callable[[], Transport] = google_transport,
        emit: Callable[[str, dict], None] = emit_line, **kwargs) -> int:
    code = refusal()
    if code:
        emit("LIVE_ERROR", {"track": track, "code": code})
        return 5
    try:
        transport = transport_factory()
    except Exception as exc:
        emit("LIVE_ERROR", {"track": track, "code": "cloud_unavailable_" + type(exc).__name__.lower()[:40]})
        return 5
    emit("LIVE_ENGINE", {"track": track, "engine": ENGINE})
    engine = CloudLive(track, transport, emit, **kwargs)
    while True:
        chunk = stdin.read(6400)   # 100 ms
        if not chunk:
            break
        engine.feed(chunk)
    engine.finish()
    return 0 if not engine.failed else 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--track", choices=("mic", "sys"), required=True)
    args = parser.parse_args()
    return run(args.track, sys.stdin.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
