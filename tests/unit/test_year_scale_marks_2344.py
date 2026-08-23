"""Der Jahres-Regler braucht Landmarken (#2344).

Die Bahn trug **keine einzige Markierung** — 76 Jahre blankes Gleis. Die
Schwierigkeit ist dabei nicht die Praezision: bei 1950–2026 auf 300 px sind es
**0,25 Jahre pro Pixel**, eine Daumenbewegung von 8 px also rund **zwei Jahre**.
(Die Ausgangsbeschreibung nannte vier Jahre pro Pixel — Faktor sechzehn daneben,
im Issue korrigiert.)

Das Problem ist die **Orientierung**: man sieht nicht, wo 1985 liegt, also
zieht man, liest die Zahl, zieht nach — bei zwoelf Sekunden auf der Uhr.

**Abgeleitet statt festgenagelt.** Seit #2337 setzt `applyYearRange()` die
Grenzen aus der laufenden Playlist. Marken auf feste Prozentwerte zu legen
waere in dem Moment falsch, in dem eine Playlist ueber den Standard
hinausreicht — deshalb rechnet die Skala aus derselben Spanne.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "js"
    / "player-game.js"
)
_HTML = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "player.html"
)


def _src() -> str:
    return _JS.read_text()


def _fn(name: str) -> str:
    src = _src()
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n(?:export )?function ", src[start + 10 :])
    return src[start : start + 10 + nxt.start()] if nxt else src[start:]


def _step_for(lo: int, hi: int, max_marks: int = 8) -> float:
    """Die Schrittweiten-Regel aus dem JS, unabhaengig nachgebildet."""
    step: float = 10
    while (hi - lo) / step > max_marks:
        step = 20 if step == 10 else step * 2.5
    return step


def _marks(lo: int, hi: int) -> list[int]:
    step = _step_for(lo, hi)
    first = -(-lo // step) * step
    out, y = [], first
    while y <= hi:
        out.append(int(y))
        y += step
    return out


class TestTheMarksFollowTheSpan:
    def test_the_default_span_gets_its_decades(self):
        # 1950–2026 ist der Standardfall nach #2337. Acht Jahrzehnte, auf
        # einer 300-px-Bahn rund 35 px auseinander.
        assert _marks(1950, 2026) == [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]

    def test_a_narrow_playlist_gets_fewer_marks(self):
        # Eine enge Playlist bekommt keine erfundenen Landmarken.
        assert _marks(1980, 1995) == [1980, 1990]

    def test_a_long_span_widens_the_step(self):
        # Acht Marken sind die Grenze; darueber wird der Schritt groesser,
        # statt die Beschriftungen aufeinanderzuschieben.
        assert _step_for(1927, 2026) == 20
        assert len(_marks(1927, 2026)) <= 8


class TestTheTwoThingsEasyToGetWrong:
    def test_positions_are_inset_by_half_the_thumb(self):
        # Der Daumen-Mittelpunkt erreicht den Rand nie. Eine Marke bei echten
        # 100 % saesse hinter dem hoechsten waehlbaren Jahr.
        body = _fn("renderYearScale")
        assert "YEAR_SCALE_THUMB_PX / 2" in body
        assert "(100% - " in body

    def test_a_century_crossing_falls_back_to_four_digits(self):
        # 1900 und 2000 waeren beide "'00". Die Kurzform gilt nur, solange
        # sie eindeutig bleibt.
        body = _fn("renderYearScale")
        assert "ambiguous" in body
        short = [y % 100 for y in _marks(1900, 2026)]
        assert len(short) != len(set(short)), "der Testfall selbst muss kollidieren"


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
