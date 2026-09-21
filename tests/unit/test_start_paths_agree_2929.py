"""#2929 — the two ways to start a game must decide the same things.

A host can start a game over the admin websocket or over ``POST
/beatify/api/start-gameplay``. Both existed for a long time, and they had
drifted:

* only the REST path lowered Sudden Death below its floor, so the *same* game
  started over the websocket ran with Sudden Death active and too few players;
* only the websocket path broadcast ``game_starting``, so a REST start left the
  TV and every phone on the lobby view for the ~10-15 s the speaker needs.

The direction of the gap is what made it expensive: the admin page presses the
**websocket** button, so the missing floor was on the path humans use, while the
live test drives REST and could never see it.

These tests assert the agreement rather than the implementation: each one runs
both surfaces through the same situation and demands the same outcome. Whatever
``start_gameplay.py`` looks like later, a future start rule that lands in only
one surface fails here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.const import DOMAIN, SUDDEN_DEATH_MIN_PLAYERS
from custom_components.beatify.server.game_views import StartGameplayView
from custom_components.beatify.server.ws_handlers.admin import admin_start_game

from tests.conftest import make_game_state, make_songs


def _fresh_game(state, **kwargs):
    return state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


def _add_live_player(state, name: str) -> None:
    ws = AsyncMock()
    ws.closed = False
    state.add_player(name, ws)
    state.get_player(name).connected = True


def _handler() -> MagicMock:
    handler = MagicMock()
    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    handler.broadcast_metadata_update = AsyncMock()
    return handler


def _started_game(players: int, *, sudden_death: bool):
    state = make_game_state()
    _fresh_game(state, sudden_death_mode=sudden_death)
    for i in range(players):
        _add_live_player(state, f"P{i}")
    state.start_round = AsyncMock(return_value=True)
    return state


async def _start_over_websocket(state, handler):
    await admin_start_game(handler, AsyncMock(), {}, state)


@patch(
    "custom_components.beatify.server.game_views.is_authorized_http",
    return_value=True,
)
async def _start_over_rest(state, handler, _auth):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": handler}}
    return await StartGameplayView(hass).post(MagicMock())


class TestBothPathsApplyTheSuddenDeathFloor:
    """The floor is a property of the game, not of the button that was pressed."""

    async def test_websocket_start_lowers_sudden_death(self):
        state = _started_game(SUDDEN_DEATH_MIN_PLAYERS - 1, sudden_death=True)
        await _start_over_websocket(state, _handler())
        assert state.sudden_death_mode is False

    async def test_rest_start_lowers_sudden_death(self):
        state = _started_game(SUDDEN_DEATH_MIN_PLAYERS - 1, sudden_death=True)
        await _start_over_rest(state, _handler())
        assert state.sudden_death_mode is False

    async def test_neither_path_lowers_it_at_the_floor(self):
        """Exactly at the floor both must leave the mode alone."""
        for start in (_start_over_websocket, _start_over_rest):
            state = _started_game(SUDDEN_DEATH_MIN_PLAYERS, sudden_death=True)
            await start(state, _handler())
            assert state.sudden_death_mode is True, start.__name__


class TestBothPathsAnnounceTheStart:
    """`game_starting` is the room's cue to show the loader, not a socket detail."""

    @staticmethod
    def _announced(handler) -> bool:
        return any(
            call.args and call.args[0] == {"type": "game_starting"}
            for call in handler.broadcast.call_args_list
        )

    async def test_websocket_start_announces(self):
        handler = _handler()
        await _start_over_websocket(_started_game(2, sudden_death=False), handler)
        assert self._announced(handler)

    async def test_rest_start_announces(self):
        handler = _handler()
        await _start_over_rest(_started_game(2, sudden_death=False), handler)
        assert self._announced(handler)


class TestNeitherPathAnnouncesARefusal:
    """A start that is refused must not tell the room a game is beginning."""

    async def test_websocket_refusal_is_silent(self):
        handler = _handler()
        state = _started_game(1, sudden_death=False)  # one short of MIN_PLAYERS
        await _start_over_websocket(state, handler)
        assert not TestBothPathsAnnounceTheStart._announced(handler)

    async def test_rest_refusal_is_silent(self):
        handler = _handler()
        state = _started_game(1, sudden_death=False)
        resp = await _start_over_rest(state, handler)
        assert resp.status == 409
        assert not TestBothPathsAnnounceTheStart._announced(handler)
