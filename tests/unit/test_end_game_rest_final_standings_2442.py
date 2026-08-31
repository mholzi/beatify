"""EndGameView must finalize before it tears the game down (#2442).

`end_game()` clears the state. Broadcasting *after* it therefore serialises
nothing, and the players never receive a `phase: END` — no podium, no
scoreboard, no share card. The endpoint is the admin UI's fallback for a closed
admin socket, so it runs exactly when the host's connection is already shaky.

The order these tests pin down is: finalize → broadcast the END state →
tear down → announce `game_ended`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.game_views import EndGameView


def _hass(phase: GamePhase, *, with_ws: bool = True):
    """Mock hass holding a game in `phase`, plus an optional WS handler."""
    calls: list[str] = []

    game = MagicMock()
    game.game_id = "game-2442"
    game.phase = phase
    game.stop_media = AsyncMock(side_effect=lambda: calls.append("stop_media"))
    game.resolve_title_artist_if_pending = AsyncMock(
        side_effect=lambda: calls.append("resolve_title_artist")
    )
    game.advance_to_end = AsyncMock(side_effect=lambda: calls.append("advance_to_end"))
    game.end_game = AsyncMock(side_effect=lambda: calls.append("end_game"))

    ws = None
    if with_ws:
        ws = MagicMock()
        ws.broadcast_state = AsyncMock(
            side_effect=lambda: calls.append("broadcast_state")
        )
        ws.broadcast = AsyncMock(
            side_effect=lambda msg: calls.append(f"broadcast:{msg['type']}")
        )

    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game, "ws_handler": ws}}
    return hass, game, ws, calls


def _request():
    request = MagicMock()
    request.remote = "1.2.3.4"
    return request


@pytest.fixture
def authorized():
    with patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    ):
        yield


@pytest.mark.usefixtures("authorized")
class TestEndGameRestFinalStandings:
    @pytest.mark.parametrize(
        "phase", [GamePhase.PLAYING, GamePhase.REVEAL, GamePhase.PAUSED]
    )
    async def test_end_state_is_broadcast_before_teardown(self, phase):
        """The END state has to leave the server while there is still a game."""
        hass, game, ws, calls = _hass(phase)
        with patch(
            "custom_components.beatify.server.game_views.finalize_and_end",
            new=AsyncMock(side_effect=lambda *a, **k: calls.append("finalize")),
        ):
            resp = await EndGameView(hass).post(_request())

        assert resp.status == 200
        assert calls.index("finalize") < calls.index("broadcast_state")
        assert calls.index("broadcast_state") < calls.index("end_game")
        # game_ended is the cleanup signal and comes last, after the podium.
        assert calls.index("broadcast_state") < calls.index("broadcast:game_ended")

    async def test_playoff_is_not_armed(self):
        """A teardown request must not start one more round (#1725)."""
        hass, game, ws, calls = _hass(GamePhase.REVEAL)
        spy = AsyncMock()
        with patch(
            "custom_components.beatify.server.game_views.finalize_and_end", new=spy
        ):
            await EndGameView(hass).post(_request())

        assert spy.await_count == 1
        assert spy.await_args.kwargs["allow_playoff"] is False

    async def test_last_round_scoring_is_resolved_first(self):
        """Title/artist scoring is deferred; without this the podium loses a round."""
        hass, game, ws, calls = _hass(GamePhase.REVEAL)
        with patch(
            "custom_components.beatify.server.game_views.finalize_and_end",
            new=AsyncMock(side_effect=lambda *a, **k: calls.append("finalize")),
        ):
            await EndGameView(hass).post(_request())

        assert calls.index("resolve_title_artist") < calls.index("finalize")
        game.stop_media.assert_awaited_once()

    async def test_lobby_game_is_only_torn_down(self):
        """Nothing was played, so there is no podium to send."""
        hass, game, ws, calls = _hass(GamePhase.LOBBY)
        spy = AsyncMock()
        with patch(
            "custom_components.beatify.server.game_views.finalize_and_end", new=spy
        ):
            resp = await EndGameView(hass).post(_request())

        assert resp.status == 200
        spy.assert_not_awaited()
        assert calls == ["end_game", "broadcast:game_ended"]

    async def test_without_ws_handler_the_game_still_ends(self):
        """No sockets to serve, but the state must still reach END and tear down."""
        hass, game, ws, calls = _hass(GamePhase.PLAYING, with_ws=False)
        resp = await EndGameView(hass).post(_request())

        assert resp.status == 200
        assert calls.index("advance_to_end") < calls.index("end_game")
