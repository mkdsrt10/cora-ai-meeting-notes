"""Plan multi-minute transcription windows for hosted (LLM) speech models.

Local Whisper wants ~12-25 s clips; a hosted model does better with minutes of
context (it hears whole sentences and names introduced earlier) and needs far
fewer calls. Windows are contiguous spans of the *original* timeline, cut at
pauses, so a model timestamp relative to the window start plus the window
start is the absolute time — no mapping table.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WINDOW_TARGET_S = 240.0   # aim for about this long
WINDOW_MAX_S = 360.0      # never longer (one continuous stretch is split)
BREAK_GAP_S = 8.0         # a pause this long always starts a new window
MIN_SPLIT_S = 60.0        # don't split a retry window shorter than this


@dataclass
class Window:
    start: float
    end: float
    stretches: list[tuple[float, float]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def _make(stretches: list[tuple[float, float]]) -> Window:
    return Window(stretches[0][0], stretches[-1][1], list(stretches))


def plan_windows(speech: list[tuple[float, float]], target: float = WINDOW_TARGET_S,
                 max_len: float = WINDOW_MAX_S, break_gap: float = BREAK_GAP_S) -> list[Window]:
    """Group speech stretches (start, end) into windows cut at the longest
    pause near the target length."""
    pieces: list[tuple[float, float]] = []
    for start, end in sorted(speech):
        while end - start > max_len:  # one unbroken stretch longer than a window
            pieces.append((start, start + max_len))
            start += max_len
        if end - start > 0.05:
            pieces.append((start, end))

    windows: list[Window] = []
    cur: list[tuple[float, float]] = []
    for piece in pieces:
        if cur and piece[0] - cur[-1][1] > break_gap:
            windows.append(_make(cur))
            cur = []
        if cur and piece[1] - cur[0][0] > target:
            cut = _best_cut(cur, target)
            if cut is None:  # no usable pause: close the window here
                windows.append(_make(cur))
                cur = []
            else:
                windows.append(_make(cur[:cut + 1]))
                cur = cur[cut + 1:]
        cur.append(piece)
        # a carried-over tail plus the new piece can itself exceed max_len
        while len(cur) > 1 and cur[-1][1] - cur[0][0] > max_len:
            cut = _best_cut(cur, max_len)
            if cut is None:
                break
            windows.append(_make(cur[:cut + 1]))
            cur = cur[cut + 1:]
    if cur:
        windows.append(_make(cur))
    return windows


def _best_cut(stretches: list[tuple[float, float]], target: float) -> int | None:
    """Index i such that cutting after stretches[i] uses the longest pause in
    the back half of the window; None when there is only one stretch."""
    if len(stretches) < 2:
        return None
    begin = stretches[0][0]
    best, best_gap = None, -1.0
    for i in range(len(stretches) - 1):
        gap = stretches[i + 1][0] - stretches[i][1]
        if stretches[i][1] - begin >= target * 0.5 and gap > best_gap:
            best, best_gap = i, gap
    if best is None:  # nothing in the back half: take the longest pause anywhere
        gaps = [(stretches[i + 1][0] - stretches[i][1], i) for i in range(len(stretches) - 1)]
        best = max(gaps)[1]
    return best


def split_window(window: Window) -> list[Window] | None:
    """Split a window in two at its longest internal pause (for the retry
    ladder). None if it is too short or has no pause to cut at."""
    if window.duration < MIN_SPLIT_S or len(window.stretches) < 2:
        return None
    gaps = [(window.stretches[i + 1][0] - window.stretches[i][1], i) for i in range(len(window.stretches) - 1)]
    cut = max(gaps)[1]
    return [_make(window.stretches[:cut + 1]), _make(window.stretches[cut + 1:])]
