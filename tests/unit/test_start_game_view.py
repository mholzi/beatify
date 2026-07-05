"""Tests for StartGameView's existing-game guard (#935)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.views import StartGameView


def _hass_with_game(phase: GamePhase) -> MagicMock:
    """Build a mock hass holding an active game in the given phase."""
    game = MagicMock()
    game.game_id = "test-game-id"
    game.phase = phase
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game}}
    return hass


def _request() -> MagicMock:
    """Build a minimal mock request (only `.remote` is read before the guard)."""
    request = MagicMock()
    request.remote = "1.2.3.4"
    return request


class TestStartGameExistingGameGuard:
    """start-game must hand the client a recoverable code for a LOBBY game (#935)."""

    async def test_existing_lobby_game_returns_game_in_lobby(self):
        # A game already in the lobby is recoverable — the client should
        # begin gameplay, not dead-end on "End current game first".
        view = StartGameView(_hass_with_game(GamePhase.LOBBY))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_IN_LOBBY"

    async def test_existing_playing_game_returns_already_started(self):
        # A game mid-play genuinely must be ended first — keep the old code.
        view = StartGameView(_hass_with_game(GamePhase.PLAYING))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_ALREADY_STARTED"

    async def test_existing_reveal_game_returns_already_started(self):
        view = StartGameView(_hass_with_game(GamePhase.REVEAL))
        resp = await view.post(_request())
        assert resp.status == 409
        assert json.loads(resp.body)["error"] == "GAME_ALREADY_STARTED"


# ---------------------------------------------------------------------------
# Happy-path start-game: body flags reach game_state (#1180)
# ---------------------------------------------------------------------------

_VALID_PLAYLIST = json.dumps(
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


def _make_request(hass: MagicMock, body: dict) -> MagicMock:
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
        # #1766: StartGameView now loads playlist songs off-loop via
        # _resolve_and_load_playlist, which returns (songs, warning) instead of
        # raw file content. Other executor calls keep the raw-content contract.
        if getattr(func, "__name__", "") == "_resolve_and_load_playlist":
            return json.loads(_VALID_PLAYLIST).get("songs", []), None
        return _VALID_PLAYLIST

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


class TestTitleArtistModeStartFlag:
    """StartGameView forwards title_artist_mode into create_game (#1180)."""

    async def test_title_artist_mode_forwarded(self, start_game_env):
        view, hass, body = start_game_env
        body["title_artist_mode"] = True

        resp = await view.post(_make_request(hass, body))
        assert resp.status == 200

        game_state = hass.data[DOMAIN]["game"]
        assert game_state.title_artist_mode is True

    async def test_title_artist_mode_defaults_off(self, start_game_env):
        view, hass, body = start_game_env
        body.pop("title_artist_mode", None)

        resp = await view.post(_make_request(hass, body))
        assert resp.status == 200

        game_state = hass.data[DOMAIN]["game"]
        assert game_state.title_artist_mode is False


# ---------------------------------------------------------------------------
# #1627 follow-up: game-start safety remap of a stale native-twin selection
# ---------------------------------------------------------------------------


def _twin_registry_entry(entity_id: str, platform: str, unique_id: str) -> MagicMock:
    """Fake entity-registry entry (mirrors the #1628 test helper style)."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.unique_id = unique_id
    entry.domain = "media_player"
    return entry


def _twin_start_game_env(media_player: str, entries: list[MagicMock]):
    """A StartGameView whose entity registry serves both the twin remap
    (``.entities.values()``) and per-entity platform lookup (``.async_get``).

    Returns a context-manager-style generator yielding ``(view, hass, body)``;
    the caller drives it with ``next(...)``. The registry is shared by
    ``async_get_native_twin_remap`` (patched on
    ``homeassistant.helpers.entity_registry.async_get``) and the view's own
    platform detection (patched on ``game_views.er.async_get``).
    """
    by_id = {e.entity_id: e for e in entries}

    game_state = GameState()
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game_state}}

    media_state = MagicMock()
    media_state.state = "playing"
    hass.states.get.return_value = media_state
    hass.config.path.return_value = "/tmp/beatify/playlists"

    async def _executor(func, *args):
        # #1766: StartGameView now loads playlist songs off-loop via
        # _resolve_and_load_playlist, which returns (songs, warning) instead of
        # raw file content. Other executor calls keep the raw-content contract.
        if getattr(func, "__name__", "") == "_resolve_and_load_playlist":
            return json.loads(_VALID_PLAYLIST).get("songs", []), None
        return _VALID_PLAYLIST

    hass.async_add_executor_job = AsyncMock(side_effect=_executor)

    body = {"playlists": ["test.json"], "media_player": media_player}

    registry = MagicMock()
    registry.entities.values = MagicMock(return_value=list(entries))
    registry.async_get = MagicMock(side_effect=lambda eid: by_id.get(eid))

    return game_state, hass, body, registry


class TestNativeTwinRemapAtStart:
    """StartGameView remaps a stale native-twin selection to its MA twin (#1627)."""

    async def test_native_twin_id_remapped_to_ma_twin(self):
        entries = [
            _twin_registry_entry(
                "media_player.esszimmer", "music_assistant", "RINCON_X"
            ),
            _twin_registry_entry("media_player.unnamed_room", "sonos", "RINCON_X"),
        ]
        game_state, hass, body, registry = _twin_start_game_env(
            "media_player.unnamed_room", entries
        )

        with (
            patch(
                "custom_components.beatify.server.game_views.is_authorized_http",
                new=MagicMock(return_value=True),
            ),
            patch("custom_components.beatify.server.game_views.Path") as mock_path_cls,
            patch(
                "custom_components.beatify.server.game_views.er.async_get",
                return_value=registry,
            ),
            patch(
                "homeassistant.helpers.entity_registry.async_get",
                return_value=registry,
            ),
        ):
            mock_path = MagicMock()
            full_path = MagicMock()
            full_path.resolve.return_value = full_path
            full_path.is_relative_to.return_value = True
            full_path.exists.return_value = True
            mock_path.resolve.return_value = mock_path
            mock_path.__truediv__.return_value = full_path
            mock_path_cls.return_value = mock_path

            view = StartGameView(hass)
            resp = await view.post(_make_request(hass, body))

        assert resp.status == 200
        # The stale native twin was healed to the MA twin before create_game.
        assert game_state.media_player == "media_player.esszimmer"
        assert game_state.platform == "music_assistant"

    async def test_normal_id_untouched(self):
        entries = [
            _twin_registry_entry(
                "media_player.esszimmer", "music_assistant", "RINCON_X"
            ),
            _twin_registry_entry("media_player.kitchen", "sonos", "RINCON_Y"),
        ]
        game_state, hass, body, registry = _twin_start_game_env(
            "media_player.esszimmer", entries
        )

        with (
            patch(
                "custom_components.beatify.server.game_views.is_authorized_http",
                new=MagicMock(return_value=True),
            ),
            patch("custom_components.beatify.server.game_views.Path") as mock_path_cls,
            patch(
                "custom_components.beatify.server.game_views.er.async_get",
                return_value=registry,
            ),
            patch(
                "homeassistant.helpers.entity_registry.async_get",
                return_value=registry,
            ),
        ):
            mock_path = MagicMock()
            full_path = MagicMock()
            full_path.resolve.return_value = full_path
            full_path.is_relative_to.return_value = True
            full_path.exists.return_value = True
            mock_path.resolve.return_value = mock_path
            mock_path.__truediv__.return_value = full_path
            mock_path_cls.return_value = mock_path

            view = StartGameView(hass)
            resp = await view.post(_make_request(hass, body))

        assert resp.status == 200
        # A normal (non-twin) MA entity_id is used as-is.
        assert game_state.media_player == "media_player.esszimmer"


# ---------------------------------------------------------------------------
# #1766: start-game reuses the #1704 discovery cache + loads off the loop
# ---------------------------------------------------------------------------


class TestResolveAndLoadPlaylist:
    """The per-playlist load helper runs resolve/exists (+ any read) off-loop
    and reuses discovery's already-parsed songs on a cache hit."""

    def test_cache_hit_returns_cached_songs_without_reading(self, tmp_path):
        # A real file exists, but the cached parse must be returned verbatim
        # (identity) — proving no re-read/re-parse happened on a cache hit.
        from custom_components.beatify.server.game_views import (
            _resolve_and_load_playlist,
        )

        pl = tmp_path / "p.json"
        pl.write_text(
            json.dumps({"songs": [{"year": 1999, "uri": "spotify:track:onfile"}]})
        )
        cached = [{"year": 2001, "uri": "spotify:track:fromcache"}]

        songs, warning = _resolve_and_load_playlist(tmp_path, "p.json", cached)

        assert warning is None
        assert songs is cached  # reused discovery's parse, ignored the file

    def test_cache_miss_falls_back_to_read_and_parse(self, tmp_path):
        from custom_components.beatify.server.game_views import (
            _resolve_and_load_playlist,
        )

        pl = tmp_path / "p.json"
        pl.write_text(
            json.dumps({"songs": [{"year": 1999, "uri": "spotify:track:onfile"}]})
        )

        songs, warning = _resolve_and_load_playlist(tmp_path, "p.json", None)

        assert warning is None
        assert songs == [{"year": 1999, "uri": "spotify:track:onfile"}]

    def test_missing_file_returns_warning(self, tmp_path):
        from custom_components.beatify.server.game_views import (
            _resolve_and_load_playlist,
        )

        songs, warning = _resolve_and_load_playlist(tmp_path, "nope.json", None)

        assert songs is None
        assert "not found" in warning.lower()

    def test_path_traversal_is_blocked(self, tmp_path):
        from custom_components.beatify.server.game_views import (
            _resolve_and_load_playlist,
        )

        songs, warning = _resolve_and_load_playlist(tmp_path, "../../etc/passwd", None)

        assert songs is None
        assert "Invalid playlist path" in warning


class TestStartGameUsesDiscoveryCache:
    """StartGameView routes playlist loading through the memoised #1704
    discovery entry point rather than re-reading each file itself (#1766)."""

    async def test_start_game_calls_discovery(self, start_game_env):
        view, hass, body = start_game_env

        discover = AsyncMock(return_value=([], {}))
        with patch(
            "custom_components.beatify.server.game_views."
            "async_discover_playlists_detailed",
            discover,
        ):
            resp = await view.post(_make_request(hass, body))

        assert resp.status == 200
        # The Start tap went through the shared discovery cache (one off-loop
        # parse) instead of re-reading/parsing playlists inline on the loop.
        discover.assert_awaited_once()
