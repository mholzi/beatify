"""
Beatify Test Fixtures - Shared test infrastructure.

This file provides the core fixtures used across all test types:
- Unit tests (game state, scoring)
- Integration tests (WebSocket, MA service)
- E2E tests (Playwright browser tests)

Fixture Architecture:
- Pure functions in support/helpers/ (testable without pytest)
- Fixtures wrap helpers with cleanup and injection
- Factories in support/factories/ generate test data
"""

from __future__ import annotations

# =============================================================================
# HOME ASSISTANT MOCK (must be before any custom_components imports)
# =============================================================================
import sys
from unittest.mock import MagicMock

# Create mock homeassistant module before any imports that need it
mock_ha = MagicMock()
mock_ha.core = MagicMock()
mock_ha.core.HomeAssistant = MagicMock

# Mock components
mock_ha.components = MagicMock()
mock_ha.components.frontend = MagicMock()
mock_ha.components.frontend.async_register_built_in_panel = MagicMock()
mock_ha.components.frontend.async_remove_panel = MagicMock()
mock_ha.components.http = MagicMock()
mock_ha.components.http.StaticPathConfig = MagicMock

# Mock helpers
mock_ha.helpers = MagicMock()
mock_ha.helpers.aiohttp_client = MagicMock()
mock_ha.config_entries = MagicMock()

# Register all mocked modules
sys.modules["homeassistant"] = mock_ha
sys.modules["homeassistant.core"] = mock_ha.core
sys.modules["homeassistant.components"] = mock_ha.components
sys.modules["homeassistant.components.frontend"] = mock_ha.components.frontend
sys.modules["homeassistant.components.http"] = mock_ha.components.http
sys.modules["homeassistant.helpers"] = mock_ha.helpers
sys.modules["homeassistant.helpers.aiohttp_client"] = mock_ha.helpers.aiohttp_client
sys.modules["homeassistant.config_entries"] = mock_ha.config_entries

# =============================================================================

import asyncio
from collections.abc import AsyncGenerator, Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from aiohttp.test_utils import TestClient


# =============================================================================
# TIME CONTROL FIXTURES
# =============================================================================


@pytest.fixture
def frozen_time() -> float:
    """Fixed timestamp for deterministic timer tests.

    Usage:
        def test_round_expiry(game_state, frozen_time):
            assert game_state._now() == frozen_time
    """
    return 1000.0


@pytest.fixture
def time_fn(frozen_time: float):
    """Time function fixture for GameState injection.

    Usage:
        game = GameState(time_fn=time_fn)
    """
    return lambda: frozen_time


# =============================================================================
# GAME STATE FIXTURES
# =============================================================================


@dataclass
class MockGameState:
    """Mock game state for testing state transitions.

    This is a placeholder until the actual GameState is implemented.
    Replace with import from custom_components.beatify.game.state
    """

    phase: str = "LOBBY"
    round: int = 0
    total_rounds: int = 10
    players: list[dict[str, Any]] = field(default_factory=list)
    _now: Any = field(default_factory=lambda: lambda: 1000.0)

    def add_player(self, name: str, session_id: str) -> dict[str, Any]:
        """Add a player to the game."""
        player = {
            "name": name,
            "session_id": session_id,
            "score": 0,
            "submitted": False,
            "connected": True,
        }
        self.players.append(player)
        return player

    def start_game(self) -> None:
        """Transition from LOBBY to PLAYING."""
        if self.phase != "LOBBY":
            raise ValueError(f"Cannot start game from phase: {self.phase}")
        if len(self.players) < 2:
            raise ValueError("Need at least 2 players to start")
        self.phase = "PLAYING"
        self.round = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for WebSocket broadcast."""
        return {
            "phase": self.phase,
            "round": self.round,
            "total_rounds": self.total_rounds,
            "players": self.players,
        }


@pytest.fixture
def game_state(time_fn) -> MockGameState:
    """Fresh game state with controlled time.

    Usage:
        def test_state_transition(game_state):
            game_state.add_player("Alice", "session-1")
            game_state.add_player("Bob", "session-2")
            game_state.start_game()
            assert game_state.phase == "PLAYING"
    """
    return MockGameState(_now=time_fn)


# =============================================================================
# HOME ASSISTANT MOCKS
# =============================================================================


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance.

    Provides the essential HA APIs needed by Beatify:
    - hass.config.path() for file paths
    - hass.bus for event handling
    - hass.states for entity states

    Usage:
        async def test_setup(mock_hass):
            await async_setup_entry(mock_hass, config_entry)
    """
    hass = MagicMock()
    hass.config.path = lambda *parts: "/config/" + "/".join(parts)
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.states = MagicMock()
    hass.states.async_set = MagicMock()
    return hass


# =============================================================================
# MUSIC ASSISTANT MOCKS
# =============================================================================


@pytest.fixture
def mock_ma_service() -> AsyncMock:
    """Mock Music Assistant service.

    Simulates MA responses for:
    - get_library_tracks() -> list of track metadata
    - play_media() -> playback control
    - get_player() -> media player state

    Usage:
        async def test_song_selection(mock_ma_service):
            tracks = await mock_ma_service.get_library_tracks()
            assert len(tracks) > 0
    """
    ma = AsyncMock()

    # Mock track data
    ma.get_library_tracks.return_value = [
        {
            "id": "track-001",
            "name": "Last Christmas",
            "artist": "Wham!",
            "album": "Music from the Edge of Heaven",
            "year": 1984,
            "album_art_url": "https://example.com/art.jpg",
        },
        {
            "id": "track-002",
            "name": "Billie Jean",
            "artist": "Michael Jackson",
            "album": "Thriller",
            "year": 1982,
            "album_art_url": "https://example.com/thriller.jpg",
        },
    ]

    ma.play_media.return_value = True
    ma.get_player.return_value = {
        "state": "playing",
        "volume": 0.5,
        "position": 0,
    }

    return ma


@pytest.fixture
def mock_media_player() -> MagicMock:
    """Mock Home Assistant media player entity.

    Usage:
        async def test_volume_control(mock_media_player):
            await hass.services.async_call(
                "media_player", "volume_set",
                {"entity_id": mock_media_player.entity_id, "volume_level": 0.8}
            )
    """
    player = MagicMock()
    player.entity_id = "media_player.beatify_speaker"
    player.state = "playing"
    player.attributes = {
        "volume_level": 0.5,
        "media_title": "Last Christmas",
        "media_artist": "Wham!",
    }
    return player


# =============================================================================
# WEBSOCKET TEST FIXTURES
# =============================================================================


@dataclass
class MockWebSocketMessage:
    """Mock WebSocket message for testing handlers."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


@pytest.fixture
def ws_join_message() -> MockWebSocketMessage:
    """Pre-built join message for testing."""
    return MockWebSocketMessage(type="join", data={"name": "TestPlayer"})


@pytest.fixture
def ws_submit_message() -> MockWebSocketMessage:
    """Pre-built submit guess message for testing."""
    return MockWebSocketMessage(
        type="submit",
        data={"guess": 1985, "bet": False},
    )


@pytest.fixture
def ws_admin_start_message() -> MockWebSocketMessage:
    """Pre-built admin start game message."""
    return MockWebSocketMessage(
        type="admin",
        data={"action": "start_game"},
    )


# =============================================================================
# AIOHTTP TEST CLIENT (for WebSocket integration tests)
# =============================================================================


@pytest.fixture
async def ws_client(aiohttp_client, game_state, mock_hass, mock_ma_service):
    """WebSocket test client for integration tests.

    Requires pytest-aiohttp to be installed.

    Usage:
        async def test_player_join(ws_client):
            async with ws_client.ws_connect('/beatify/ws') as ws:
                await ws.send_json({"type": "join", "name": "Alice"})
                msg = await ws.receive_json()
                assert msg["type"] == "state"

    Note: This fixture will need to be updated when the actual
    WebSocket server is implemented in custom_components/beatify/server/
    """
    # Placeholder: Replace with actual app creation when implemented
    # from custom_components.beatify.server.websocket import create_app
    # app = create_app(game_state, mock_hass, mock_ma_service)
    # return await aiohttp_client(app)

    pytest.skip("WebSocket server not yet implemented")


# =============================================================================
# PYTEST MARKERS
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external deps)")
    config.addinivalue_line("markers", "integration: Integration tests (WebSocket, MA)")
    config.addinivalue_line("markers", "e2e: End-to-end browser tests (Playwright)")
    config.addinivalue_line("markers", "slow: Tests that take > 5 seconds")


# =============================================================================
# CLEANUP UTILITIES
# =============================================================================


@pytest.fixture(autouse=True)
async def cleanup_after_test():
    """Auto-cleanup fixture that runs after each test.

    Ensures no state leaks between tests.
    """
    yield
    # Add cleanup logic here when needed
    # e.g., reset singletons, clear caches, etc.
