"""Design-system leftovers after #3387 (#3395).

The admin end screen's "Start New Game" button was neon green with a glow next
to the magenta Rematch button, and the steal target picker was a white card on
top of the dark game UI. Both must read from the shared tokens (dark surface,
no neon-green fill).
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "css"
    / "styles.css"
).read_text()
_CSS = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)

_LIGHT_SURFACES = {
    "--color-bg-card",
    "--color-bg-card-alt",
    "--color-bg-white",
    "--color-bg-light",
}


def _rules(selector: str) -> list[str]:
    """Return the declaration blocks of every rule whose selector list ends in ``selector``."""
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _CSS):
        sels = [s.strip() for s in m.group(1).split(",")]
        if selector in sels:
            out.append(m.group(2))
    return out


def test_new_game_button_is_not_neon_green():
    blocks = _rules(".new-game-btn") + _rules("body.theme-dark .new-game-btn")
    assert blocks
    for body in blocks:
        assert "color-success-neon" not in body
        assert "glow-success" not in body
        assert "#39ff14" not in body.lower()
        assert "#4dff1f" not in body.lower()


def test_steal_picker_uses_dark_surface():
    for sel in (".steal-modal-content", "body.theme-dark .steal-modal-content"):
        blocks = _rules(sel)
        assert blocks, sel
        for body in blocks:
            for bg in re.findall(r"background:\s*var\((--[\w-]+)", body):
                assert bg not in _LIGHT_SURFACES, (sel, bg)
    # Text on that dark surface must not be the dark-on-light admin text token.
    for sel in (".steal-modal-title", ".steal-target-btn"):
        for body in _rules(sel):
            assert "color: var(--color-text-primary)" not in body, sel
