"""Regression coverage for finale-playoff spectators (#2612)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_ELIMINATED
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _game_with_players(*names: str):
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    for name in names:
        ws = MagicMock()
        ws.closed = False
        state.add_player(name, ws)
    return state


class TestFinalePlayoffScoring:
    def test_spectators_are_not_scored(self):
        state = _game_with_players("Alice", "Clara")
        alice = state.get_player("Alice")
        clara = state.get_player("Clara")
        state.round_start_time = None

        alice.current_guess = 1980
        alice.submitted = True
        clara.current_guess = 1980
        clara.submitted = True
        clara.playoff_spectator = True
        clara.score = 50
        clara.round_score = 7
        clara.round_scores = [7]

        state._score_all_players(1980, list(state.players.values()))

        assert alice.score > 0
        assert clara.score == 50
        assert clara.round_score == 7
        assert clara.round_scores == [7]

    def test_active_guessers_exclude_playoff_spectators(self):
        state = _game_with_players("Alice", "Bob", "Clara")
        state.get_player("Bob").playoff_spectator = True
        state.get_player("Clara").eliminated = True

        assert [p.name for p in state._active_guessers()] == ["Alice"]

    def test_all_submitted_ignores_playoff_spectator(self):
        state = _game_with_players("Alice", "Bob")
        state.get_player("Alice").submitted = True
        state.get_player("Bob").playoff_spectator = True

        assert state.all_submitted() is True


class TestFinalePlayoffGuessGuard:
    async def test_spectator_guess_is_rejected_before_recording(self):
        state = _game_with_players("Alice")
        ws = state.get_player("Alice").ws
        state.phase = GamePhase.PLAYING
        state.deadline = int(state._now() * 1000) + 60_000
        state.get_player("Alice").playoff_spectator = True

        hass = MagicMock()
        hass.data = {DOMAIN: {"game": state}}
        handler = BeatifyWebSocketHandler(hass)
        ws.send_json = AsyncMock()

        await handler._handle_message(ws, {"type": "submit", "year": 1980})

        message = ws.send_json.call_args[0][0]
        assert message["code"] == ERR_ELIMINATED
        assert message["message"] == "You are sitting out this playoff"
        assert state.get_player("Alice").submitted is False
