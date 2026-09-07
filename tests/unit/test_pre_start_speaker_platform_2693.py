"""The pre-start hook must move the speaker AND its platform (#2693).

Since #2636 the platform is the key :func:`build_strategy` dispatches on, so a
speaker and a platform that disagree do not fail loudly — they pick the wrong
strategy. The game starts, the first song times out, and nothing in the log
points at the cause.

The pre-start hook (``StartGameView`` -> ``_regen_library_songs``) re-applies
the persisted output settings, which hold ``media_player`` but no platform. It
used to assign the entity alone.

The fix has two halves and both are pinned here:

* the factory DERIVES the platform from the entity registry, so no caller can
  build a service whose strategy disagrees with the speaker (the class of bug);
* the hook writes ``gs.platform`` as well, so the round path's non-MA
  responsiveness probe reads the truth too (this instance of it).

Every assertion below is on the strategy that is actually SELECTED, not on the
attribute — an attribute test would have passed with the routing still broken.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN, PROVIDER_MA_LIBRARY
from custom_components.beatify.game.state import GameState
from custom_components.beatify.services.factories import ha_service_factories
from custom_components.beatify.services.playback import (
    MusicAssistantStrategy,
    SonosStrategy,
)
from custom_components.beatify.server.game_views import StartGameView

MA_SPEAKER = "media_player.ma_speaker"
SONOS_SPEAKER = "media_player.sonos_kitchen"

_PLATFORM_BY_ENTITY = {
    MA_SPEAKER: "music_assistant",
    SONOS_SPEAKER: "sonos",
}


def _registry() -> MagicMock:
    """An entity registry that knows both speakers and their platforms."""

    def _lookup(entity_id: str):
        platform = _PLATFORM_BY_ENTITY.get(entity_id)
        if platform is None:
            return None
        entry = MagicMock()
        entry.platform = platform
        return entry

    reg = MagicMock()
    reg.async_get.side_effect = _lookup
    return reg


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.states.get.return_value = MagicMock(state="playing")
    return hass


def _library_songs(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri_ma_library": f"library://track/{i}",
        }
        for i in range(n)
    ]


def _selected_strategy(game_state: GameState):
    """Build the media-player service the way a round does, return its strategy."""
    game_state._media_player_service = None
    game_state._ensure_media_player_service()
    assert game_state._media_player_service is not None
    return game_state._media_player_service._strategy


class TestFactoryDerivesThePlatform:
    """The class of bug: a caller cannot hand the factory a wrong platform."""

    def test_stale_platform_does_not_choose_the_strategy(self):
        hass = _hass()
        with patch(
            "homeassistant.helpers.entity_registry.async_get", return_value=_registry()
        ):
            service = ha_service_factories(hass).media_player(
                SONOS_SPEAKER, platform="music_assistant"
            )
        assert isinstance(service._strategy, SonosStrategy)

    def test_the_other_direction_too(self):
        hass = _hass()
        with patch(
            "homeassistant.helpers.entity_registry.async_get", return_value=_registry()
        ):
            service = ha_service_factories(hass).media_player(
                MA_SPEAKER, platform="sonos"
            )
        assert isinstance(service._strategy, MusicAssistantStrategy)

    def test_unregistered_entity_keeps_what_the_caller_passed(self):
        """A YAML-only player has no registry entry — don't downgrade it."""
        hass = _hass()
        with patch(
            "homeassistant.helpers.entity_registry.async_get", return_value=_registry()
        ):
            service = ha_service_factories(hass).media_player(
                "media_player.not_in_registry", platform="sonos"
            )
        assert isinstance(service._strategy, SonosStrategy)


@pytest.fixture
def library_game():
    """A started Crate Digger game whose pre-start hook is installed.

    Returns ``(game_state, hass)``. The game was created on the Music Assistant
    speaker; the persisted output settings point at the Sonos one, which is the
    switch the hook exists to apply.
    """
    hass = _hass()
    game_state = GameState(service_factories=ha_service_factories(hass))
    game_state._hass = hass
    hass.data = {DOMAIN: {"game": game_state}}

    body = {
        "playlists": [],
        "media_player": MA_SPEAKER,
        "provider": PROVIDER_MA_LIBRARY,
    }
    request = MagicMock()
    request.remote = "1.2.3.4"
    request.json = AsyncMock(return_value=body)

    with (
        patch(
            "custom_components.beatify.server.game_views.is_authorized_http",
            return_value=True,
        ),
        patch(
            "homeassistant.helpers.entity_registry.async_get", return_value=_registry()
        ),
        patch(
            "custom_components.beatify.server.game_views._generate_library_songs",
            new=AsyncMock(return_value=(_library_songs(), None)),
        ),
        patch(
            "custom_components.beatify.server.game_views.async_get_native_twin_remap",
            new=AsyncMock(return_value={}),
        ),
    ):
        yield StartGameView(hass), request, game_state, hass


@pytest.mark.asyncio
class TestPreStartHookMovesBoth:
    async def _start(self, view, request):
        resp = await view.post(request)
        assert resp.status == 200, resp.body
        return resp

    async def test_hook_is_installed_for_a_library_game(self, library_game):
        view, request, game_state, _hass_ = library_game
        with (
            patch(
                "homeassistant.helpers.entity_registry.async_get",
                return_value=_registry(),
            ),
            patch(
                "custom_components.beatify.server.game_views._generate_library_songs",
                new=AsyncMock(return_value=(_library_songs(), None)),
            ),
            patch(
                "custom_components.beatify.server.game_views.async_get_native_twin_remap",
                new=AsyncMock(return_value={}),
            ),
        ):
            await self._start(view, request)
        assert callable(game_state.pre_start_hook)
        # Baseline: created on MA, so MA is what the game would play through.
        assert game_state.platform == "music_assistant"
        assert isinstance(_selected_strategy(game_state), MusicAssistantStrategy)

    async def test_stored_sonos_speaker_gets_the_sonos_strategy(self, library_game):
        """The regression. Before the fix this built MusicAssistantStrategy."""
        view, request, game_state, _hass_ = library_game
        stored = {"media_player": SONOS_SPEAKER}
        with (
            patch(
                "homeassistant.helpers.entity_registry.async_get",
                return_value=_registry(),
            ),
            patch(
                "custom_components.beatify.server.game_views._generate_library_songs",
                new=AsyncMock(return_value=(_library_songs(), None)),
            ),
            patch(
                "custom_components.beatify.server.game_views.async_get_native_twin_remap",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "custom_components.beatify.server.library_views."
                "async_load_game_output_settings",
                new=AsyncMock(return_value=stored),
            ),
        ):
            await self._start(view, request)
            hook = game_state.pre_start_hook
            await hook(game_state)

            assert game_state.media_player == SONOS_SPEAKER
            # What actually matters, asserted first: the strategy the next
            # round will use. On origin/main this is MusicAssistantStrategy.
            assert isinstance(_selected_strategy(game_state), SonosStrategy)
            # The attribute — necessary, but on its own it proves nothing.
            assert game_state.platform == "sonos"
