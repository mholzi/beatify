"""A rejected lobby speaker no longer discards the rest of the request (#3223).

``saveGameSettings`` sends the speaker with every settings change. When
``UpdateLobbyView`` refused the speaker it returned before TTS, party lights and
language were looked at, so those changes were lost without a word. The view
now applies them, keeps the speaker, and returns the rejection together with
the fields it applied and the speaker the game is still on.
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


def _lobby(provider: str = "ytmusic_free"):
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(10),
        media_player="media_player.party",
        base_url="http://localhost:8123",
    )
    state.provider = provider
    state.language = "en"
    assert state.phase is GamePhase.LOBBY
    return state


async def _post(
    state, body: dict[str, Any], platform: str
) -> tuple[int, dict[str, Any], dict[str, AsyncMock]]:
    hass = MagicMock()
    handler = MagicMock()
    handler.broadcast_state = AsyncMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": handler}}
    names = {"media_player.echo": "Kitchen Echo", "media_player.party": "Living Room"}
    hass.states.get.side_effect = lambda eid: SimpleNamespace(
        state="idle", name=names.get(eid, "Speaker")
    )
    registry = MagicMock()
    registry.async_get.return_value = MagicMock(platform=platform)
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    mocks = {
        "tts": AsyncMock(return_value=True),
        "lights": AsyncMock(return_value=True),
        "save": AsyncMock(),
    }
    with (
        patch(f"{VIEWS}.is_authorized_http", return_value=True),
        patch(f"{VIEWS}.er.async_get", return_value=registry),
        patch(f"{VIEWS}.async_get_native_twin_remap", AsyncMock(return_value={})),
        patch(f"{VIEWS}._apply_tts_config", mocks["tts"]),
        patch(f"{VIEWS}._apply_party_lights_config", mocks["lights"]),
        patch(f"{VIEWS}.async_save_game_output_settings", mocks["save"]),
    ):
        response = await UpdateLobbyView(hass).post(request)
    mocks["broadcast"] = handler.broadcast_state
    return response.status, json.loads(response.body), mocks


BODY = {
    "media_player": "media_player.echo",
    "tts": {"enabled": True, "entity_id": "tts.cloud"},
    "party_lights": {"enabled": True, "lights": ["light.a"]},
    "language": "de",
}


@pytest.mark.asyncio
async def test_rejected_speaker_still_applies_tts_lights_and_language():
    state = _lobby()

    status, body, mocks = await _post(state, BODY, "alexa_media")

    # The speaker stays and the rejection is reported as before.
    assert status == 400
    assert body["code"] == "PROVIDER_NOT_SUPPORTED"
    assert body["speaker"] == "Kitchen Echo"
    assert state.media_player == "media_player.party"
    # The rest of the request was applied.
    mocks["tts"].assert_awaited_once_with(state, BODY["tts"])
    mocks["lights"].assert_awaited_once_with(state, BODY["party_lights"])
    assert state.language == "de"
    mocks["broadcast"].assert_awaited_once()
    assert set(body["fields"]) == {"tts", "party_lights", "language"}
    assert body["updated"] is True
    # The admin learns which speaker the game is still on.
    assert body["media_player"] == "media_player.party"
    assert body["current_speaker"] == "Living Room"


@pytest.mark.asyncio
async def test_rejected_speaker_is_not_persisted_but_the_rest_is():
    state = _lobby()

    _, _, mocks = await _post(state, BODY, "alexa_media")

    mocks["save"].assert_awaited_once()
    patch_arg = mocks["save"].await_args.args[1]
    assert "media_player" not in patch_arg
    assert patch_arg["tts"] == BODY["tts"]
    assert patch_arg["party_lights"] == BODY["party_lights"]


@pytest.mark.asyncio
async def test_unknown_speaker_still_applies_the_rest():
    state = _lobby()
    hass_missing = {"media_player": "media_player.gone", "language": "de"}

    with patch(f"{VIEWS}._validate_media_player") as validate:
        from custom_components.beatify.server.base import _json_error

        validate.return_value = (
            "media_player.gone",
            "unknown",
            _json_error(
                "Media player not found",
                400,
                code="INVALID_REQUEST",
                message_key="MEDIA_PLAYER_NOT_FOUND",
            ),
        )
        status, body, _ = await _post(state, hass_missing, "music_assistant")

    assert status == 400
    assert body["message_key"] == "MEDIA_PLAYER_NOT_FOUND"
    assert state.media_player == "media_player.party"
    assert state.language == "de"
    assert body["fields"] == ["language"]


@pytest.mark.asyncio
async def test_accepted_speaker_response_is_unchanged():
    state = _lobby("spotify")

    status, body, _ = await _post(
        state, {"media_player": "media_player.kitchen"}, "music_assistant"
    )

    assert status == 200
    assert body == {"updated": True, "fields": ["media_player"]}
    assert state.media_player == "media_player.kitchen"
