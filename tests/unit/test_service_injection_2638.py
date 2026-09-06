"""#2638: the game logic is constructible without Home Assistant.

``GameState`` used to import ``services.media_player`` / ``services.lights`` /
``services.tts`` lazily and build them itself out of ``self._hass``, and it held
``_admin_ws`` — an ``aiohttp`` socket only the server ever touched. Both are
gone: the services arrive as factories (``game/protocols.py``), and the socket
lives on ``BeatifyWebSocketHandler``.

These tests pin that contract. Every one of them builds real game logic with no
``hass`` anywhere in sight — which is the whole point.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.protocols import GameOutputFactories
from custom_components.beatify.game.state import GameState
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _create_game(state: GameState, **kwargs) -> dict:
    return state.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# No factories = no outputs, and nothing blows up
# ---------------------------------------------------------------------------


class TestBareGameStateHasNoOutputs:
    def test_constructs_without_hass(self):
        state = GameState()
        assert state._hass is None
        assert state._service_factories == GameOutputFactories()

    def test_ensure_media_player_service_is_a_no_op(self):
        state = make_game_state()
        _create_game(state)
        state._ensure_media_player_service()
        assert state._media_player_service is None

    @pytest.mark.asyncio
    async def test_configure_party_lights_is_a_no_op(self):
        state = make_game_state()
        await state.configure_party_lights(["light.a"], "medium")
        assert state._party_lights is None

    @pytest.mark.asyncio
    async def test_configure_tts_still_applies_its_flags(self):
        """No factory means no voice, but the per-event toggles still land.

        The announce_* methods all guard on ``self._tts_service``, so a game
        with no TTS backend is simply silent.
        """
        state = make_game_state()
        await state.configure_tts("tts.google", announce_winner=False)
        assert state._tts_service is None
        assert state._tts_announce_winner is False


# ---------------------------------------------------------------------------
# What the factories are handed
# ---------------------------------------------------------------------------


class TestFactoriesReceiveTheGameContext:
    def test_media_player_factory_gets_entity_platform_provider(self):
        seen = {}

        def _factory(entity_id, **kwargs):
            seen["entity_id"] = entity_id
            seen.update(kwargs)
            return MagicMock()

        state = make_game_state(media_player=_factory)
        _create_game(state)
        state.platform = "music_assistant"

        state._ensure_media_player_service()

        assert seen["entity_id"] == "media_player.test"
        assert seen["platform"] == "music_assistant"
        assert seen["provider"] == "spotify"
        assert seen["inherited_states"] is None

    def test_media_player_service_is_built_once_per_game(self):
        builds = []
        state = make_game_state(
            media_player=lambda *_a, **_kw: builds.append(1) or MagicMock()
        )
        _create_game(state)

        state._ensure_media_player_service()
        state._ensure_media_player_service()

        assert len(builds) == 1

    @pytest.mark.asyncio
    async def test_tts_factory_gets_both_entity_ids(self):
        seen = {}

        def _factory(**kwargs):
            seen.update(kwargs)
            return MagicMock(speak=AsyncMock())

        state = make_game_state(tts=_factory)
        _create_game(state)

        await state.configure_tts("tts.google_gemini_tts")

        assert seen == {
            "tts_entity_id": "tts.google_gemini_tts",
            "media_player_entity_id": "media_player.test",
        }
        assert state._tts_service is not None


# ---------------------------------------------------------------------------
# The admin spectator socket belongs to the server (#477 / #2638)
# ---------------------------------------------------------------------------


class TestAdminSocketOwnership:
    def test_game_state_no_longer_holds_the_socket(self):
        assert not hasattr(make_game_state(), "_admin_ws")

    def test_handler_owns_it_and_can_drop_it(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {"game": make_game_state()}}
        handler = BeatifyWebSocketHandler(hass)
        assert handler.admin_ws is None

        handler.admin_ws = MagicMock()
        handler.clear_admin_socket()

        assert handler.admin_ws is None

    def test_teardown_notifies_the_registered_owner(self):
        """``_reset_game_internals`` fires where it used to null ``_admin_ws``."""
        state = make_game_state()
        calls = []
        state.register_reset_callback(lambda: calls.append("reset"))

        state._reset_game_internals()

        assert calls == ["reset"]

    @pytest.mark.asyncio
    async def test_end_game_and_rematch_both_notify(self):
        state = make_game_state()
        _create_game(state)
        calls = []
        state.register_reset_callback(lambda: calls.append("reset"))

        await state.end_game()
        assert calls == ["reset"]

        _create_game(state)
        state.rematch_game()
        assert calls == ["reset", "reset"]

    @pytest.mark.asyncio
    async def test_unload_closes_and_forgets_the_socket(self):
        """The owner closes the socket it opened, then drops the reference."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"game": make_game_state()}}
        handler = BeatifyWebSocketHandler(hass)

        ws = AsyncMock()
        ws.closed = False
        ws.close = AsyncMock()
        handler.connections.add(ws)
        handler.admin_ws = ws

        await handler.async_close_all()

        ws.close.assert_awaited_once()
        assert handler.connections == set()
        assert handler.admin_ws is None
