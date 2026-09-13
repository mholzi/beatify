"""Der Jahres-Regler braucht Landmarken (#2344).

Die Bahn trug **keine einzige Markierung** — 76 Jahre blankes Gleis. Das
Problem ist die **Orientierung**: man sieht nicht, wo die Spanne anfaengt und
aufhoert, also zieht man, liest die Zahl, zieht nach.

**Abgeleitet statt festgenagelt.** Seit #2337 setzt `applyYearRange()` die
Grenzen aus der laufenden Playlist, deshalb rechnet die Skala aus derselben
Spanne.

#2827: the decade marks from #2344 overlapped on real phones. Between the four
±1/±5 buttons the track is about 62px wide on a 360px screen, and up to eight
labels sat on top of each other. The scale now shows exactly two labels — the
lowest and the highest selectable year, as full years, pinned to the ends. The
behaviour is unit-tested in
`www/js/__tests__/player-dotaxis-layout-2823.test.js`; this file keeps the
wiring guards.
"""

from __future__ import annotations

import re
from pathlib import Path

_WWW = Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"
_JS = _WWW / "js" / "player-game.js"
_CSS = _WWW / "css" / "styles.css"
_HTML = _WWW / "player.html"


def _src() -> str:
    return _JS.read_text()


def _fn(name: str) -> str:
    src = _src()
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n(?:export )?function ", src[start + 10 :])
    return src[start : start + 10 + nxt.start()] if nxt else src[start:]


class TestOnlyMinAndMax:
    def test_the_scale_is_built_from_the_pure_rule(self):
        assert "yearScaleMarks(lo, hi)" in _fn("renderYearScale")

    def test_the_rule_returns_the_two_bounds(self):
        body = _fn("yearScaleMarks")
        assert "edge: 'start'" in body
        assert "edge: 'end'" in body
        # No decade loop any more: that loop is what overlapped (#2827).
        assert "step" not in body

    def test_the_two_labels_are_pinned_to_the_ends(self):
        css = _CSS.read_text()
        assert re.search(r"\.year-scale-mark--start\s*\{[^}]*left:\s*0", css)
        assert re.search(r"\.year-scale-mark--end\s*\{[^}]*right:\s*0", css)

    def test_the_buttons_do_not_inherit_the_global_button_padding(self):
        # The global `button` padding made the ±1/±5 buttons 52px ovals and
        # starved the track (#2827).
        css = _CSS.read_text()
        block = re.search(r"\n\.slider-btn-year \{([^}]*)\}", css)
        assert block and re.search(r"padding:\s*0", block.group(1))


class TestItIsWiredToTheOneSourceOfTheSpan:
    def test_applyyearrange_rebuilds_the_scale(self):
        # Grenzen und Marken duerfen nicht aus zwei Quellen kommen.
        assert "renderYearScale(lo, hi)" in _fn("applyYearRange")

    def test_the_markup_ships_an_empty_container(self):
        # Feste Marken im HTML waeren genau der Fehler, den #2337 gerade
        # beseitigt hat.
        html = _HTML.read_text()
        assert 'id="year-scale"' in html
        m = re.search(r'<div id="year-scale"[^>]*>(.*?)</div>', html, re.DOTALL)
        assert m and not m.group(1).strip()
