"""Steal und Sabotage muessen nach dem Rundenende ebenso abgewiesen werden (#2335).

#1662 hat die drei Challenge-Handler nachgezogen, weil sie nur `phase ==
PLAYING` prueften und im Fenster zwischen Deadline-Ablauf und dem
Phasenwechsel durch `end_round` noch Punkte buchten. Der Commit dazu heisst
`fix(guessing): reject late Artist/Movie/Title&Artist guesses past deadline`.

`handle_steal` und `handle_sabotage` blieben dabei aussen vor — dieselbe
Ursache, dieselbe Datei, nur nicht auf der Liste.

**Der Schaden zeigt in zwei verschiedene Richtungen**, und das ist der Grund
fuer zwei getrennte Testklassen statt einer parametrisierten:

* Ein **Steal** ist eine vollwertige Abgabe — er schreibt `current_guess`,
  setzt `submitted = True` und stempelt `submission_time`. Nach Ablauf
  ausgefuehrt schenkt er **einem Spieler Zeit**, die alle anderen nicht haben.
* Eine **Sabotage** trifft das Opfer nicht mehr: alle drei Effekte wirken auf
  dessen Abgabe-Weg, und der ist nach der Deadline ohnehin zu. Sie verbrennt
  aber ueber `consume_sabotage` den **Token des Angreifers** — der Schaden
  faellt auf den, der sie einsetzt.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_ROUND_EXPIRED
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


async def _playing_game(*, deadline_passed: bool):
    """Zwei Spieler in PLAYING; Bob hat abgegeben, Alice noch nicht."""
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()

    ws_a, ws_b = _ws(), _ws()
    gs.add_player("Alice", ws_a)
    gs.add_player("Bob", ws_b)
    gs.get_player("Alice").connected = True
    gs.get_player("Bob").connected = True
    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING

    bob = gs.get_player("Bob")
    bob.current_guess = 1984
    bob.submitted = True

    alice = gs.get_player("Alice")
    alice.steal_available = True
    alice.sabotage_available = True

    gs.is_deadline_passed = MagicMock(return_value=deadline_passed)
    return handler, gs, ws_a


def _codes(ws: AsyncMock) -> list[str]:
    return [
        c.args[0].get("code")
        for c in ws.send_json.call_args_list
        if c.args and isinstance(c.args[0], dict)
    ]


class TestStealAfterTheDeadline:
    async def test_it_is_rejected(self):
        handler, gs, ws = await _playing_game(deadline_passed=True)
        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
        assert ERR_ROUND_EXPIRED in _codes(ws)
        gs._cancel_auto_advance()

    async def test_no_submission_is_banked(self):
        # Der eigentliche Schaden: ohne den Guard stuende Alice hier mit
        # submitted=True und einem frischen submission_time da.
        handler, gs, ws = await _playing_game(deadline_passed=True)
        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
        alice = gs.get_player("Alice")
        assert alice.submitted is False
        assert alice.current_guess is None
        gs._cancel_auto_advance()

    async def test_the_steal_token_is_not_consumed(self):
        # Eine abgewiesene Aktion darf nichts kosten.
        handler, gs, ws = await _playing_game(deadline_passed=True)
        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
        assert gs.get_player("Alice").steal_available is True
        gs._cancel_auto_advance()


class TestSabotageAfterTheDeadline:
    """Ziel ist hier **Charlie**, nicht Bob — und das ist kein Detail.

    Bob hat abgegeben, und `use_sabotage` weist ein Ziel mit `submitted`
    ohnehin ab. Ein Test gegen Bob waere auch ohne den neuen Guard gruen
    gewesen und haette nichts gezeigt. Charlie hat nicht abgegeben, also ist
    der Deadline-Guard das Einzige, was die Aktion noch aufhaelt.
    """

    async def test_it_is_rejected(self):
        handler, gs, ws = await _playing_game(deadline_passed=True)
        gs.add_player("Charlie", _ws())
        gs.get_player("Charlie").connected = True
        await handler._handle_message(ws, {"type": "sabotage", "target": "Charlie"})
        assert ERR_ROUND_EXPIRED in _codes(ws)
        gs._cancel_auto_advance()

    async def test_the_saboteurs_token_is_not_burned(self):
        # Hier liegt der Schaden — nicht beim Opfer. Ohne den Guard laeuft
        # consume_sabotage() fuer einen Effekt, den niemand mehr spuert.
        handler, gs, ws = await _playing_game(deadline_passed=True)
        gs.add_player("Charlie", _ws())
        gs.get_player("Charlie").connected = True
        await handler._handle_message(ws, {"type": "sabotage", "target": "Charlie"})
        assert gs.get_player("Alice").sabotage_available is True
        assert gs.get_player("Charlie").sabotaged_by is None
        gs._cancel_auto_advance()


class TestBeforeTheDeadlineNothingChanges:
    async def test_a_steal_still_works(self):
        # Ohne diesen Test waere ein Guard, der immer abweist, ebenfalls gruen.
        handler, gs, ws = await _playing_game(deadline_passed=False)
        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
        alice = gs.get_player("Alice")
        assert ERR_ROUND_EXPIRED not in _codes(ws)
        assert alice.submitted is True
        assert alice.current_guess == 1984
        gs._cancel_auto_advance()

    async def test_a_sabotage_still_works(self):
        handler, gs, ws = await _playing_game(deadline_passed=False)
        # Bob hat schon abgegeben und ist damit kein gueltiges Ziel — Charlie
        # ist es. Das trennt „Guard weist ab" von „Regel weist ab".
        gs.add_player("Charlie", _ws())
        gs.get_player("Charlie").connected = True
        await handler._handle_message(ws, {"type": "sabotage", "target": "Charlie"})
        assert ERR_ROUND_EXPIRED not in _codes(ws)
        assert gs.get_player("Charlie").sabotaged_by == "Alice"
        gs._cancel_auto_advance()
