"""Shared fixtures for Beatify tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import GameState
from custom_components.beatify.server.views import StartGameView


def make_player(name: str = "Alice", score: int = 0, **kwargs) -> PlayerSession:
    """Create a PlayerSession with a mock WebSocket (avoids aiohttp dependency)."""
    return PlayerSession(name=name, ws=MagicMock(), score=score, **kwargs)


def make_game_state(time_fn=None) -> GameState:
    """Create a fresh GameState (optionally with injected time function)."""
    return GameState(time_fn=time_fn)


def make_songs(n: int = 5) -> list[dict]:
    """Generate minimal song dicts for testing."""
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "_resolved_uri": f"spotify:track:test{i:022d}",
            "uri": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# start-game harness (#2530): moved here from test_start_game_view.py so more
# than one module can drive a real create_game. Importing a fixture across test
# modules works but reads as a redefinition to the linter, and the repo's own
# convention for shared test scaffolding is conftest (see make_game_state /
# make_songs in tests/conftest.py). Behaviour is unchanged.
# ---------------------------------------------------------------------------
VALID_START_GAME_PLAYLIST = json.dumps(
    {
        "songs": [
            {
                "year": 1985,
                "title": "Song One",
                "artist": "Artist One",
                "uri": "spotify:track:0000000000000000000001",
            },
            {
                "year": 1990,
                "title": "Song Two",
                "artist": "Artist Two",
                "uri": "spotify:track:0000000000000000000002",
            },
        ]
    }
)


def make_start_game_request(hass: MagicMock, body: dict) -> MagicMock:
    """Build a mock request returning ``body`` from ``.json()`` (#1180)."""
    request = MagicMock()
    request.remote = "1.2.3.4"
    request.json = AsyncMock(return_value=body)
    request.url = SimpleNamespace(scheme="http", host="localhost", port=8123)
    return request


@pytest.fixture
def start_game_env():
    """A StartGameView + real GameState + a valid playlist mocked on disk.

    Returns ``(view, hass, body)`` where the body is a minimal-but-complete
    start-game payload. The playlist file read and platform capabilities are
    mocked so ``create_game`` runs and writes the body flags onto the
    real ``GameState`` stored in ``hass.data[DOMAIN]["game"]``.
    """
    game_state = GameState()
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game_state}}

    # Media player entity exists and is available.
    media_state = MagicMock()
    media_state.state = "playing"
    hass.states.get.return_value = media_state

    hass.config.path.return_value = "/tmp/beatify/playlists"

    # Playlist file read runs in an executor; return the valid content.
    async def _executor(func, *args):
        return VALID_START_GAME_PLAYLIST

    hass.async_add_executor_job = AsyncMock(side_effect=_executor)

    body = {
        "playlists": ["test.json"],
        "media_player": "media_player.test",
    }

    with (
        patch(
            "custom_components.beatify.server.game_views.is_authorized_http",
            new=MagicMock(return_value=True),
        ),
        patch("custom_components.beatify.server.game_views.Path") as mock_path_cls,
        patch(
            "custom_components.beatify.server.game_views.er.async_get"
        ) as mock_async_get,
        patch(
            "custom_components.beatify.server.game_views.get_platform_capabilities",
            return_value={"supported": True},
        ),
    ):
        # Make path-traversal + existence checks pass for any playlist path.
        mock_path = MagicMock()
        full_path = MagicMock()
        full_path.resolve.return_value = full_path
        full_path.is_relative_to.return_value = True
        full_path.exists.return_value = True
        mock_path.resolve.return_value = mock_path
        mock_path.__truediv__.return_value = full_path
        mock_path_cls.return_value = mock_path

        entity_entry = MagicMock()
        entity_entry.platform = "music_assistant"
        mock_async_get.return_value.async_get.return_value = entity_entry

        view = StartGameView(hass)
        yield view, hass, body
