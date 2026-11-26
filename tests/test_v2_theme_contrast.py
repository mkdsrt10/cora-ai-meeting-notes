"""UI shell v2 theme tokens stay readable (WCAG AA, 4.5:1 for body text).

Checks the light and dark token sets in src/ui/web/v2/shell.css: muted text on
every surface, and text on solid fills (primary button, record button, avatars,
ticked checkbox) via --onFill.
"""
import re
from pathlib import Path

import pytest

CSS = (Path(__file__).resolve().parents[1] / "src/ui/web/v2/shell.css").read_text()


def _tokens(block_start: str) -> dict[str, str]:
    start = CSS.index(block_start)
    body = CSS[start:CSS.index("}", start)]
    return dict(re.findall(r"--([A-Za-z0-9]+):(#[0-9a-fA-F]{6})", body))


def _lum(hex_color: str) -> float:
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


DARK_BLOCKS = ['@media (prefers-color-scheme:dark)', ':root[data-theme="dark"]']


@pytest.mark.parametrize("block", DARK_BLOCKS)
def test_dark_muted_text_is_readable_on_every_surface(block):
    t = _tokens(block)
    for surface in ("bg", "bg2", "side", "hover"):
        assert _ratio(t["ink3"], t[surface]) >= 4.5, (surface, t["ink3"], t[surface])


@pytest.mark.parametrize("block", DARK_BLOCKS + [":root{"])
def test_text_on_solid_fills_is_readable(block):
    t = _tokens(block)
    for fill in ("accent", "red", "green"):
        assert _ratio(t["onFill"], t[fill]) >= 4.5, (fill, t["onFill"], t[fill])


def test_both_dark_blocks_match():
    assert _tokens(DARK_BLOCKS[0]) == _tokens(DARK_BLOCKS[1])
