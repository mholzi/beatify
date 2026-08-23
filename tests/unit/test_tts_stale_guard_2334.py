"""Der Waechter gegen veraltete Ansagen hat nie gegriffen (#2334).

``_tts_announce`` merkt sich beim Einreihen die laufende Runde und vergleicht
sie erneut, wenn die Ansage vorne in der Warteschlange ankommt. Der Kommentar
darueber beschreibt genau, wozu: eine in Runde N eingereihte Phrase, die erst
in Runde N+1 gesprochen wuerde, ist falsch und gehoert verworfen.

Gefragt wurde nach ``self.current_round``. **Das Attribut existiert auf
GameState nicht** — es heisst ``round`` und kommt aus
``RoundManagerDelegationMixin``, das GameState ohnehin mitkomponiert. Beide
Seiten des Vergleichs lieferten damit ``None``, ``None != None`` war nie wahr,
und der Verwerfen-Zweig war unerreichbar.

Sichtbar war das nur an einer Stelle: die Log-Zeile in ``state_lifecycle.py``,
die dieselbe falsche Abfrage benutzte, druckte statt der Rundennummer immer
``?`` — waehrend die Zeile ein paar Zeilen weiter unten den richtigen Namen
verwendet. Eine Umbenennung, die drei Aufrufstellen uebersehen hat.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_game_state


def _state_with_speaker():
    s = make_game_state()
    s._tts_service = MagicMock()
    s._tts_service.speak = AsyncMock()
    s._lang = lambda: "de"
    s._bg_tasks = set()
    return s


async def _drain(state):
    """Alle Hintergrund-Tasks der Ansage-Warteschlange zu Ende laufen lassen."""
    for _ in range(10):
        await asyncio.sleep(0)
    if state._bg_tasks:
        await asyncio.gather(*list(state._bg_tasks), return_exceptions=True)


class TestTheGuardActuallyFires:
    @pytest.mark.asyncio
    async def test_an_announcement_from_the_previous_round_is_dropped(self):
        s = _state_with_speaker()
        s.round = 4
        await s._tts_announce("Die Zeit ist um")
        # Die Runde dreht weiter, bevor die Phrase gesprochen wird.
        s.round = 5
        await _drain(s)
        s._tts_service.speak.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_round_is_read_from_the_attribute_that_exists(self):
        # Der eigentliche Fehler war ein Name. Wenn `round` gelesen wird,
        # unterscheiden sich die beiden Seiten ueberhaupt erst.
        s = _state_with_speaker()
        s.round = 1
        assert getattr(s, "current_round", None) is None
        assert s.round == 1


class TestWhatMustKeepWorking:
    @pytest.mark.asyncio
    async def test_an_announcement_in_the_same_round_is_spoken(self):
        # Der Normalfall. Ohne diesen Test koennte ein zu scharfer Waechter
        # jede Ansage verschlucken und der obere Test waere trotzdem gruen.
        s = _state_with_speaker()
        s.round = 4
        await s._tts_announce("Die Antwort war 1984")
        await _drain(s)
        s._tts_service.speak.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_phase_change_within_the_round_does_not_drop_it(self):
        # Ausdruecklich im Kommentar am Waechter: die Ansagen zum Rundenende
        # werden GENAU beim Phasenwechsel PLAYING -> REVEAL gefeuert. Wuerde
        # der Waechter auf die Phase schauen, waeren sie samt und sonders
        # "veraltet" — das war der Grund, nur auf die Runde zu schauen.
        s = _state_with_speaker()
        s.round = 7
        await s._tts_announce("Niemand hatte es")
        s.phase = "REVEAL"
        await _drain(s)
        s._tts_service.speak.assert_awaited_once()
