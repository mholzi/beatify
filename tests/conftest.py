"""Shared fixtures for Beatify tests."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Stub homeassistant.helpers.entity_registry before any beatify imports
# so that tests can run without the full Home Assistant package.
_er_stub = ModuleType("homeassistant.helpers.entity_registry")
_er_stub.async_get = MagicMock()  # type: ignore[attr-defined]
sys.modules.setdefault("homeassistant.helpers.entity_registry", _er_stub)

from custom_components.beatify.game.player import PlayerSession  # noqa: E402
from custom_components.beatify.game.state import GameState  # noqa: E402


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
