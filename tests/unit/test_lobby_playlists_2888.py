"""Editing the setup from the lobby did not change the lobby's playlists (#2888).

Found by the live end-to-end test of v4.7.2-rc2 on the real admin page. The
admin page creates a LOBBY from ``saved_setup`` on load. The host taps **Back**,
changes the playlist selection in the wizard and taps **Go to lobby**. The
wizard's exit path pushes the new setup through ``/beatify/api/game/update-lobby``
— which patched the speaker, TTS, lights and (since #2769) the game options, but
not the playlists. The home card renders the selection from local settings, so
the screen showed "80er Hits" while round 1 played a song from
``summer-party-anthems.json``.

These tests drive the real view against a real ``GameState`` and assert on the
song pool the game will draw from.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.game_views import UpdateLobbyView
from tests.conftest import make_game_state


def _songs(prefix: str, n: int) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"{prefix} {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:{prefix[:4]}{i:018d}",
            "uri_spotify": f"spotify:track:{prefix[:4]}{i:018d}",
            "_playlist_source": f"{prefix}.json",
        }
        for i in range(n)
    ]


EIGHTIES = _songs("eighties", 30)
SUMMER = _songs("summer", 25)
LIBRARY = {"eighties.json": EIGHTIES, "summer.json": SUMMER}


async def _fake_load(_hass, paths):
    songs: list[dict[str, Any]] = []
    for path in paths:
        songs.extend(LIBRARY.get(path, []))
    return songs, []


def _lobby(paths: list[str], max_rounds: int = 0) -> GameState:
    state = make_game_state()
    songs: list[dict[str, Any]] = []
    for path in paths:
        songs.extend(LIBRARY[path])
    state.create_game(
        playlists=list(paths),
        songs=songs,
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(max_rounds=max_rounds),
    )
    assert state.phase is GamePhase.LOBBY
    return state


def _pool_titles(state: GameState) -> set[str]:
    return {s["title"] for s in state._playlist_manager._songs}


async def _post(state: GameState, body: dict[str, Any]) -> dict[str, Any]:
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state}}
    view = UpdateLobbyView(hass)
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    with (
        patch(
            "custom_components.beatify.server.game_views.is_authorized_http",
            return_value=True,
        ),
        patch(
            "custom_components.beatify.server.game_views.async_load_songs_from_paths",
            _fake_load,
        ),
    ):
        response = await view.post(request)
    return json.loads(response.body)


@pytest.mark.asyncio
async def test_a_removed_playlist_no_longer_plays():
    # Run 1 of the issue: two playlists reduced to one.
    state = _lobby(["eighties.json", "summer.json"])
    game_id = state.game_id

    result = await _post(state, {"playlists": ["eighties.json"]})

    assert "playlists" in result["fields"]
    assert state.playlists == ["eighties.json"]
    assert _pool_titles(state) == {s["title"] for s in EIGHTIES}
    assert state.total_rounds == len(EIGHTIES)
    # Patched, not replaced: guests who joined by QR stay in the room.
    assert state.game_id == game_id


@pytest.mark.asyncio
async def test_an_added_playlist_plays_and_the_round_cap_follows():
    # Run 2 of the issue: one playlist expanded to two, rounds raised to 20 in
    # the same wizard run. The cap has to apply to the NEW pool.
    state = _lobby(["eighties.json"], max_rounds=10)

    result = await _post(
        state,
        {
            "playlists": ["eighties.json", "summer.json"],
            "game_options": {"max_rounds": 20},
        },
    )

    assert set(result["fields"]) >= {"playlists", "max_rounds"}
    assert state.playlists == ["eighties.json", "summer.json"]
    assert state.songs == EIGHTIES + SUMMER
    assert state.total_rounds == 20
    assert _pool_titles(state) <= {s["title"] for s in EIGHTIES + SUMMER}


@pytest.mark.asyncio
async def test_the_same_selection_is_not_reloaded():
    state = _lobby(["eighties.json", "summer.json"])
    manager = state._playlist_manager

    result = await _post(state, {"playlists": ["summer.json", "eighties.json"]})

    assert result == {"updated": False, "fields": []}
    assert state._playlist_manager is manager


@pytest.mark.asyncio
async def test_a_selection_with_no_songs_keeps_the_lobby_playable():
    state = _lobby(["eighties.json"])

    result = await _post(state, {"playlists": ["missing.json"]})

    assert "playlists" not in result["fields"]
    assert state.playlists == ["eighties.json"]
    assert _pool_titles(state) == {s["title"] for s in EIGHTIES}


@pytest.mark.asyncio
async def test_a_running_game_keeps_its_playlists():
    # update-lobby also serves PLAYING for the speaker switch; the playlists
    # must not change under the players.
    state = _lobby(["eighties.json"])
    state._set_phase(GamePhase.PLAYING)

    result = await _post(state, {"playlists": ["summer.json"]})

    assert "playlists" not in result["fields"]
    assert state.playlists == ["eighties.json"]


@pytest.mark.asyncio
async def test_a_crate_digger_regeneration_hook_is_dropped_on_a_swap():
    # A library game created without playlists regenerates its songs at start;
    # once the host has picked playlists, that hook would discard them.
    state = _lobby(["eighties.json"])
    state.pre_start_hook = AsyncMock()

    await _post(state, {"playlists": ["summer.json"]})

    assert state.pre_start_hook is None
    assert _pool_titles(state) == {s["title"] for s in SUMMER}
