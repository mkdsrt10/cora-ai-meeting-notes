"""What one processing run cost and what the Mac was doing meanwhile, for the
processing_finished Usage event (python/usage_emitters.py). Metadata only:
seconds, megabytes and levels; never names, paths, titles or text.

    meter = run_meter.start(queue_wait_s=..., call_live=...)
    ...                      # pipeline/common._write_progress marks stages
    meter.stop(); payload = meter.payload()

- CPU: user and system seconds of this process and its waited-for children
  (ffmpeg) during the run, as deltas: the server process lives across runs,
  so getrusage alone is cumulative.
- Stages: wall seconds in each _write_progress stage (STAGES), one flat key
  per stage (CATALOG values must be scalars).
- System state: one snapshot at the start, then a sample every
  SAMPLE_INTERVAL_S on a daemon thread: free memory (free + inactive +
  speculative pages, what macOS hands out without swapping), swap used,
  memory pressure (kern.memorystatus_vm_pressure_level), thermal state
  (pmset -g therm), power source (pmset -g batt; every THERMAL_EVERY-th
  sample), and this process's RSS so the sample at the run's memory peak is
  kept. A Call being live comes from Electron (POST /api/call-state).
  Sampling never raises into processing; a failed probe leaves its key null.
"""
from __future__ import annotations

import os
import re
import resource
import subprocess
import threading
import time
from typing import Any, Callable, Optional

STAGES = ("starting", "transcribing", "aligning_speakers", "romanizing", "identifying_speakers",
          "loading_notes_model", "generating_notes", "persisting")
SAMPLE_INTERVAL_S = 2.0
THERMAL_EVERY = 5  # pmset is the slowest probe: every 10 s
PRESSURE_LEVELS = {1: "normal", 2: "warn", 4: "critical"}
PRESSURE_ORDER = ("normal", "warn", "critical")
THERMAL_ORDER = ("nominal", "warning", "throttled")

KEYS = ("cpu_user_s", "cpu_sys_s", *(f"stage_{s}_s" for s in STAGES), "queue_wait_s",
        "sys_free_mb_start", "sys_free_mb_min", "sys_free_mb_at_peak", "swap_mb_start", "swap_mb_max",
        "pressure_max", "thermal_max", "on_battery", "call_live", "peak_rss_mb")

_call_live = False
_current: Optional["RunMeter"] = None


def set_call_live(live: bool) -> None:
    """Electron says whether a Call is live (any running meter notes it)."""
    global _call_live
    _call_live = bool(live)
    meter = _current
    if meter is not None and _call_live:
        meter.call_live = True


def mark_stage(stage: str) -> None:
    """Called by pipeline/common._write_progress at each stage boundary."""
    meter = _current
    if meter is not None:
        meter.mark(stage)


# ---- probes (each returns None when it cannot tell) --------------------------------

def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout


def free_mb(vm_stat: Optional[str] = None) -> Optional[int]:
    text = vm_stat if vm_stat is not None else _run(["vm_stat"])
    page = re.search(r"page size of (\d+) bytes", text)
    pages = 0
    found = False
    for label in ("Pages free", "Pages inactive", "Pages speculative"):
        m = re.search(rf"{label}:\s+(\d+)", text)
        if m:
            pages += int(m.group(1))
            found = True
    if not (page and found):
        return None
    return round(pages * int(page.group(1)) / 1024**2)


def swap_mb(text: Optional[str] = None) -> Optional[int]:
    text = text if text is not None else _run(["sysctl", "-n", "vm.swapusage"])
    m = re.search(r"used = ([\d.]+)([MG])", text)
    if not m:
        return None
    value = float(m.group(1))
    return round(value * 1024 if m.group(2) == "G" else value)


def pressure(text: Optional[str] = None) -> Optional[str]:
    text = text if text is not None else _run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
    try:
        return PRESSURE_LEVELS.get(int(text.strip()))
    except ValueError:
        return None


def thermal(text: Optional[str] = None) -> Optional[str]:
    text = text if text is not None else _run(["pmset", "-g", "therm"])
    if not text.strip():
        return None
    limit = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", text)
    if limit and int(limit.group(1)) < 100:
        return "throttled"
    level = re.search(r"(?:Thermal|Performance) Warning Level\s*=\s*(\d+)", text, re.I)
    if level and int(level.group(1)) > 0:
        return "warning"
    return "nominal"


def on_battery(text: Optional[str] = None) -> Optional[bool]:
    text = text if text is not None else _run(["pmset", "-g", "batt"])
    if "Battery Power" in text:
        return True
    if "AC Power" in text:
        return False
    return None


def rss_mb() -> Optional[float]:
    out = _run(["ps", "-o", "rss=", "-p", str(os.getpid())]).strip()
    return round(int(out) / 1024, 1) if out.isdigit() else None


def _safe(probe: Callable[[], Any]) -> Any:
    try:
        return probe()
    except Exception:  # noqa: BLE001 - a probe never breaks processing
        return None


def _higher(order: tuple[str, ...], a: Optional[str], b: Optional[str]) -> Optional[str]:
    if a is None or b is None:
        return a or b
    return a if order.index(a) >= order.index(b) else b


class RunMeter:
    def __init__(self, *, queue_wait_s: Optional[float] = None, call_live: bool = False,
                 interval: float = SAMPLE_INTERVAL_S, sample: Optional[bool] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.queue_wait_s = None if queue_wait_s is None else round(max(0.0, float(queue_wait_s)), 1)
        self.call_live = bool(call_live)
        self.stages: dict[str, float] = {}
        self._stage: Optional[str] = None
        self._stage_at = clock()
        self._self0 = resource.getrusage(resource.RUSAGE_SELF)
        self._kids0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.cpu: dict[str, Optional[float]] = {"cpu_user_s": None, "cpu_sys_s": None}
        self.sys: dict[str, Any] = dict.fromkeys(("sys_free_mb_start", "sys_free_mb_min", "sys_free_mb_at_peak",
                                                  "swap_mb_start", "swap_mb_max", "pressure_max", "thermal_max",
                                                  "on_battery"))
        self._peak_rss = -1.0
        self._samples = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if sample is None:
            sample = os.environ.get("CORA_RUN_METER_SAMPLING", "1") != "0"
        if sample:
            self.take_sample(first=True)
            self._thread = threading.Thread(target=self._loop, args=(interval,), name="run-meter", daemon=True)
            self._thread.start()

    # stages
    def mark(self, stage: str) -> None:
        now = self.clock()
        with self._lock:
            if self._stage in STAGES:
                self.stages[self._stage] = self.stages.get(self._stage, 0.0) + (now - self._stage_at)
            self._stage, self._stage_at = stage, now

    # system samples
    def _loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            self.take_sample()

    def take_sample(self, first: bool = False, probes: Optional[dict[str, Callable[[], Any]]] = None) -> None:
        p = probes or {}
        get = lambda name, default: _safe(p.get(name, default))  # noqa: E731
        slow = first or self._samples % THERMAL_EVERY == 0
        free, swap, level, rss = get("free", free_mb), get("swap", swap_mb), get("pressure", pressure), get("rss", rss_mb)
        therm = get("thermal", thermal) if slow else None
        batt = get("battery", on_battery) if slow else None
        with self._lock:
            self._samples += 1
            s = self.sys
            if first:
                s["sys_free_mb_start"], s["swap_mb_start"] = free, swap
            if free is not None:
                s["sys_free_mb_min"] = free if s["sys_free_mb_min"] is None else min(s["sys_free_mb_min"], free)
            if swap is not None:
                s["swap_mb_max"] = swap if s["swap_mb_max"] is None else max(s["swap_mb_max"], swap)
            s["pressure_max"] = _higher(PRESSURE_ORDER, s["pressure_max"], level)
            s["thermal_max"] = _higher(THERMAL_ORDER, s["thermal_max"], therm)
            if batt is not None:
                s["on_battery"] = bool(s["on_battery"]) or batt
            if rss is not None and rss > self._peak_rss:
                self._peak_rss = rss
                s["sys_free_mb_at_peak"] = free
            if _call_live:
                self.call_live = True

    def stop(self) -> None:
        self.mark("done")
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            _safe(self.take_sample)  # one last sample so a peak right at the end is not missed
        self_now = resource.getrusage(resource.RUSAGE_SELF)
        kids_now = resource.getrusage(resource.RUSAGE_CHILDREN)
        self.cpu = {
            "cpu_user_s": round((self_now.ru_utime - self._self0.ru_utime) + (kids_now.ru_utime - self._kids0.ru_utime), 1),
            "cpu_sys_s": round((self_now.ru_stime - self._self0.ru_stime) + (kids_now.ru_stime - self._kids0.ru_stime), 1),
        }

    def payload(self) -> dict[str, Any]:
        with self._lock:
            out: dict[str, Any] = {**self.cpu, **self.sys}
            for stage in STAGES:
                out[f"stage_{stage}_s"] = round(self.stages[stage], 1) if stage in self.stages else None
        out["queue_wait_s"] = self.queue_wait_s
        out["call_live"] = self.call_live
        out["peak_rss_mb"] = self._peak_rss if self._peak_rss >= 0 else None
        return {k: out.get(k) for k in KEYS}


def start(**kwargs: Any) -> RunMeter:
    """A meter for the run starting now; stages are marked into it until stopped."""
    global _current
    meter = RunMeter(call_live=_call_live or bool(kwargs.pop("call_live", False)), **kwargs)
    _current = meter
    return meter


def finish(meter: RunMeter) -> dict[str, Any]:
    """Stop the run's meter and return its flat payload. Never raises."""
    global _current
    try:
        meter.stop()
    except Exception as exc:  # noqa: BLE001
        print(f"[run_meter] stop failed: {exc}", flush=True)
    if _current is meter:
        _current = None
    return meter.payload()
