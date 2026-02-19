"""Shared fixtures for Beatify tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import GameState


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
