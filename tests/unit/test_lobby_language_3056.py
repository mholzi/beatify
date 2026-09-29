"""Switching the language chip in an open lobby must reach the server (#3056).

The chip only re-translated the admin page and posted media player, TTS and
party lights to ``update-lobby``. ``game_state.language`` is what the TV state
frame and the TTS phrases read, and it was only set at lobby creation — so after
guests had scanned, the host switched to German and TV and announcements stayed
in the old language until the next game.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.game_views import UpdateLobbyView
from tests.conftest import make_game_state, make_songs


def _lobby(language: str = "en") -> GameState:
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(10),
        media_player="media_player.party",
        base_url="http://localhost:8123",
    )
    state.language = language
    assert state.phase is GamePhase.LOBBY
    return state


async def _post(
    state: GameState, body: dict[str, Any], ws_handler: Any = None
) -> dict[str, Any]:
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": ws_handler}}
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    with patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    ):
        response = await UpdateLobbyView(hass).post(request)
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_the_chip_switches_the_lobby_language_and_broadcasts():
    state = _lobby("en")
    handler = MagicMock()
    handler.broadcast_state = AsyncMock()

    result = await _post(state, {"language": "de"}, handler)

    assert state.language == "de"
    assert "language" in result["fields"]
    handler.broadcast_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_unchanged_language_does_not_broadcast():
    # saveGameSettings fires on every chip; only a real change is worth a frame.
    state = _lobby("de")
    handler = MagicMock()
    handler.broadcast_state = AsyncMock()

    result = await _post(state, {"language": "de"}, handler)

    assert "language" not in result["fields"]
    handler.broadcast_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unsupported_language_is_ignored():
    state = _lobby("en")

    result = await _post(state, {"language": "xx"})

    assert state.language == "en"
    assert "language" not in result["fields"]


@pytest.mark.asyncio
async def test_a_running_game_keeps_its_language():
    state = _lobby("en")
    state._set_phase(GamePhase.PLAYING)

    result = await _post(state, {"language": "de"})

    assert state.language == "en"
    assert "language" not in result["fields"]
