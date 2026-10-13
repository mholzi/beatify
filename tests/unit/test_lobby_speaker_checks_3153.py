"""Switching the speaker of an open lobby applies the start-game checks (#3153).

``UpdateLobbyView`` only checked that the entity existed and the platform was
supported. A lobby created with a provider that only plays through Music
Assistant could be moved to a speaker that cannot play it, and the game then
failed at the first song. It also kept a native twin of an MA speaker (#1627).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.game_views import UpdateLobbyView
from tests.conftest import make_game_state, make_songs

VIEWS = "custom_components.beatify.server.game_views"


def _lobby(provider: str):
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(10),
        media_player="media_player.party",
        base_url="http://localhost:8123",
    )
    state.provider = provider
    assert state.phase is GamePhase.LOBBY
    return state


async def _switch(
    state, entity_id: str, platform: str, twin_remap: dict[str, str] | None = None
) -> tuple[int, dict[str, Any]]:
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state}}
    hass.states.get.return_value = SimpleNamespace(state="idle", name="Speaker")
    registry = MagicMock()
    registry.async_get.return_value = MagicMock(platform=platform)
    request = MagicMock()
    request.json = AsyncMock(return_value={"media_player": entity_id})
    with (
        patch(f"{VIEWS}.is_authorized_http", return_value=True),
        patch(f"{VIEWS}.er.async_get", return_value=registry),
        patch(
            f"{VIEWS}.async_get_native_twin_remap",
            AsyncMock(return_value=twin_remap or {}),
        ),
    ):
        response = await UpdateLobbyView(hass).post(request)
    return response.status, json.loads(response.body)


@pytest.mark.asyncio
async def test_a_speaker_the_provider_cannot_play_on_is_rejected():
    state = _lobby("ytmusic_free")

    status, body = await _switch(state, "media_player.echo", "alexa_media")

    assert status == 400
    assert body["error"] == "PROVIDER_NOT_SUPPORTED"
    assert state.media_player == "media_player.party"


@pytest.mark.asyncio
async def test_a_speaker_the_provider_can_play_on_is_accepted():
    state = _lobby("spotify")

    status, body = await _switch(state, "media_player.kitchen", "music_assistant")

    assert status == 200
    assert state.media_player == "media_player.kitchen"
    assert state.platform == "music_assistant"


@pytest.mark.asyncio
async def test_a_native_twin_is_remapped_to_the_ma_speaker():
    state = _lobby("spotify")

    status, _ = await _switch(
        state,
        "media_player.unnamed_room",
        "music_assistant",
        twin_remap={"media_player.unnamed_room": "media_player.kitchen_ma"},
    )

    assert status == 200
    assert state.media_player == "media_player.kitchen_ma"
