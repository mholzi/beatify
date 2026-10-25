"""#3266: admin reveal must not show an emotion banner when nobody guessed."""

from __future__ import annotations

from pathlib import Path

ADMIN_JS = (
    Path(__file__).parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "js"
    / "admin.js"
)


def test_zero_guessers_skip_emotion_banner() -> None:
    src = ADMIN_JS.read_text(encoding="utf-8")
    start = src.index("var emotionText, emotionClass;")
    block = src[start : src.index("// Round info", start)]
    # The zero-guesser branch must come before the avgOff chain.
    assert block.index("guessers.length === 0") < block.index("avgOff <= 3")
    assert "emotionEl.classList.add('hidden')" in block
