"""Tests for StartGameView's existing-game guard (#935)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.views import StartGameView


def _hass_with_game(phase: GamePhase) -> MagicMock:
    """Build a mock hass holding an active game in the given phase."""
    game = MagicMock()
    game.game_id = "test-game-id"
    game.phase = phase
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game}}
    return hass


def _request() -> MagicMock:
    """Build a minimal mock request (only `.remote` is read before the guard)."""
    request = MagicMock()
    request.remote = "1.2.3.4"
    return request


class TestStartGameExistingGameGuard:
    """start-game must hand the client a recoverable code for a LOBBY game (#935)."""

    async def test_existing_lobby_game_returns_game_in_lobby(self):
        # A game already in the lobby is recoverable — the client should
        # begin gameplay, not dead-end on "End current game first".
        view = StartGameView(_hass_with_game(GamePhase.LOBBY))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_IN_LOBBY"

    async def test_existing_playing_game_returns_already_started(self):
        # A game mid-play genuinely must be ended first — keep the old code.
        view = StartGameView(_hass_with_game(GamePhase.PLAYING))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_ALREADY_STARTED"

    async def test_existing_reveal_game_returns_already_started(self):
        view = StartGameView(_hass_with_game(GamePhase.REVEAL))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_ALREADY_STARTED"
