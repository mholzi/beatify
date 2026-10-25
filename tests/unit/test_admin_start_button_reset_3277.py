"""#3277: the admin Start button is restored when the home view returns.

``startGameplay()`` disables ``#home-start-game`` and relabels it "Starting..."
on the websocket path, then returns; only the error path restored it. After a
rematch the home view came back with the stale disabled button until a reload.
admin.js cannot be imported in vitest (DOM globals), so this is a source guard.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).parents[2] / "custom_components/beatify/www/js"


def _enter_body(src: str) -> str:
    start = src.index("window.BeatifyHome = {")
    m = re.search(r"\n {8}enter\(\) \{", src[start:])
    assert m, "BeatifyHome.enter() not found"
    begin = start + m.end()
    end = src.index("\n        },", begin)
    return src[begin:end]


def test_home_enter_resets_start_button():
    src = (JS / "admin.js").read_text(encoding="utf-8")
    assert "resetHomeStartButton();" in _enter_body(src)


def test_reset_restores_enabled_and_label():
    src = (JS / "admin.js").read_text(encoding="utf-8")
    body = src[src.index("function resetHomeStartButton()") :]
    body = body[: body.index("\n}\n")]
    assert "b.disabled = false" in body
    assert "b.innerHTML = _homeStartBtnHTML" in body


def test_rematch_lobby_reenters_home_mode():
    src = (JS / "admin.js").read_text(encoding="utf-8")
    assert "window.BeatifyHome.enter();" in src
