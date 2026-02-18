"""Shared fixtures for Beatify test suite."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Stub out heavy external dependencies so we can import game modules without
# Home Assistant, aiohttp, etc.
# ---------------------------------------------------------------------------

def _ensure_stubs() -> None:
    """Create minimal stub modules for imports that aren't available in CI."""
    # Build a comprehensive list of homeassistant submodules that may be imported
    ha_mods = [
        "homeassistant",
        "homeassistant.core",
        "homeassistant.components",
        "homeassistant.components.frontend",
        "homeassistant.components.http",
        "homeassistant.components.media_player",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.loader",
    ]
    aiohttp_mods = [
        "aiohttp",
        "aiohttp.web",
        "aiohttp.web_exceptions",
    ]
    all_needed = ha_mods + aiohttp_mods + [
        "voluptuous",
    ]
    for mod_name in all_needed:
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            # Make every attribute access return a MagicMock so imports don't fail
            stub.__dict__.setdefault("__path__", [])  # allow sub-imports
            sys.modules[mod_name] = stub

    # Specific attributes needed by type hints / imports
    sys.modules["aiohttp.web"].WebSocketResponse = MagicMock  # type: ignore[attr-defined]
    sys.modules["aiohttp"].web = sys.modules["aiohttp.web"]  # type: ignore[attr-defined]
    sys.modules["homeassistant.core"].HomeAssistant = MagicMock  # type: ignore[attr-defined]

    # For any stub that might have named imports, use a module subclass
    # that returns MagicMock for any attribute access
    class _AttrStub(types.ModuleType):
        def __getattr__(self, name):
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            return MagicMock()

    # Re-wrap ALL stubs as _AttrStub so `from foo import bar` always works
    for mod_name in list(sys.modules):
        m = sys.modules[mod_name]
        if isinstance(m, types.ModuleType) and not isinstance(m, _AttrStub):
            if any(mod_name.startswith(prefix) for prefix in ("homeassistant", "voluptuous", "aiohttp")):
                new = _AttrStub(mod_name)
                new.__dict__.update(m.__dict__)
                new.__path__ = getattr(m, "__path__", [])
                sys.modules[mod_name] = new

    # aiohttp specifics
    sys.modules["aiohttp"].web = sys.modules["aiohttp.web"]  # type: ignore[attr-defined]


_ensure_stubs()


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------

from custom_components.beatify.game.player import PlayerSession  # noqa: E402
from custom_components.beatify.game.state import GameState, GamePhase  # noqa: E402


def _make_ws() -> MagicMock:
    """Create a mock WebSocket."""
    return MagicMock()


@pytest.fixture
def game_state() -> GameState:
    """Return a fresh GameState with a deterministic clock."""
    _time = [1000.0]

    def fake_time() -> float:
        return _time[0]

    gs = GameState(time_fn=fake_time)
    gs._test_time = _time  # type: ignore[attr-defined]  # allow tests to advance clock
    return gs


@pytest.fixture
def mock_ws() -> MagicMock:
    return _make_ws()


def make_player(
    name: str = "Alice",
    score: int = 0,
    streak: int = 0,
    **kwargs: Any,
) -> PlayerSession:
    """Helper to build a PlayerSession with a mock ws."""
    return PlayerSession(name=name, ws=_make_ws(), score=score, streak=streak, **kwargs)


@pytest.fixture
def sample_songs() -> list[dict[str, Any]]:
    """A small playlist for testing."""
    return [
        {
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "year": 1975,
            "uri": "spotify:track:aaaa",
            "_resolved_uri": "spotify:track:aaaa",
            "alt_artists": ["Led Zeppelin", "The Beatles"],
            "movie": "Wayne's World",
            "movie_choices": ["Wayne's World", "Pulp Fiction", "Grease"],
            "album_art": "/img/queen.jpg",
            "fun_fact": "6 minutes long",
        },
        {
            "title": "Billie Jean",
            "artist": "Michael Jackson",
            "year": 1982,
            "uri": "spotify:track:bbbb",
            "_resolved_uri": "spotify:track:bbbb",
            "alt_artists": ["Prince", "Stevie Wonder"],
            "album_art": "/img/mj.jpg",
            "fun_fact": "Thriller album",
        },
        {
            "title": "Smells Like Teen Spirit",
            "artist": "Nirvana",
            "year": 1991,
            "uri": "spotify:track:cccc",
            "_resolved_uri": "spotify:track:cccc",
            "album_art": "/img/nirvana.jpg",
            "fun_fact": "Grunge anthem",
        },
    ]
