"""#3261 — the host swaps a wrong song without losing the round.

The speaker plays a live cut, a karaoke version or the wrong track behind the
URI. Until now the host could only void the round (lost for everyone) or stop
the song. ``skip_song`` is the third way out: the same round runs again with an
unplayed song from the same pool — same round number, timer restarted, guesses
cleared, nobody penalised.

The action changes what a socket may do to a running game, so the refusal for
a guest socket is tested here as well, not only assumed from ``handle_admin``.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import ERR_INVALID_ACTION, ERR_NOT_ADMIN
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


def _player_ws() -> MagicMock:
    ws = MagicMock()
    ws.closed = False
    ws.send_json = AsyncMock()
    return ws


async def _start_game(gs, names, *, songs=6):
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for name in names:
        gs.add_player(name, _player_ws())
        gs.get_player(name).connected = True
    assert await gs.start_round() is True
    return gs


def _uri(song) -> str:
    return song["_resolved_uri"]


def _handler_for(gs, admin_ws=None):
    from custom_components.beatify.const import DOMAIN
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

    hass = MagicMock()
    hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(hass)
    if admin_ws is not None:
        handler.admin_ws = admin_ws
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    return handler


def _errors(ws) -> list[dict]:
    return [
        c.args[0]
        for c in ws.send_json.await_args_list
        if c.args and isinstance(c.args[0], dict) and c.args[0].get("type") == "error"
    ]


# ---------------------------------------------------------------------------
# The swap itself
# ---------------------------------------------------------------------------


class TestSkipSongSwapsTheSong:
    async def test_new_unplayed_song_same_round(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        await gs.end_round()
        await gs.start_round()
        assert gs.round == 2
        played_before = set(gs._playlist_manager._played_uris)
        old_uri = _uri(gs.current_song)

        assert await gs.skip_song() is None

        assert gs.phase == GamePhase.PLAYING
        assert gs.round == 2
        new_uri = _uri(gs.current_song)
        assert new_uri != old_uri
        # Unplayed before the swap, and both songs now count as played.
        assert new_uri not in played_before
        assert {old_uri, new_uri} <= set(gs._playlist_manager._played_uris)

    async def test_guesses_cleared_scores_and_streaks_kept(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        alice, bob = gs.get_player("Alice"), gs.get_player("Bob")
        alice.score, alice.streak = 40, 4
        bob.score, bob.streak = 25, 2
        bob.submit_guess(1999, 3.0)

        assert await gs.skip_song() is None

        assert (alice.score, alice.streak) == (40, 4)
        assert (bob.score, bob.streak) == (25, 2)
        assert bob.submitted is False
        assert bob.current_guess is None
        assert gs.preview_round_end()["submitted_count"] == 0

    async def test_timer_restarts(self):
        clock = {"now": 1000.0}
        gs = make_game_state()
        gs._now = lambda: clock["now"]
        gs._round_manager._now = lambda: clock["now"]
        await _start_game(gs, ["Alice", "Bob"])
        old_task = gs._round_manager._timer_task
        clock["now"] += 20  # 20 s into the round

        assert await gs.skip_song() is None

        assert gs.deadline == int(clock["now"] * 1000) + int(
            gs._round_manager.round_duration * 1000
        )
        new_task = gs._round_manager._timer_task
        assert new_task is not None and new_task is not old_task
        assert old_task.cancelled() or old_task.cancelling()

    async def test_new_song_is_played_on_the_speaker(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        svc = gs._media_player_service
        svc.play_song.reset_mock()

        await gs.skip_song()

        svc.stop.assert_awaited()
        svc.play_song.assert_awaited_once()
        assert _uri(svc.play_song.await_args.args[0]) == _uri(gs.current_song)

    async def test_skipped_track_is_logged_with_its_uri(self, caplog):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        old_uri = _uri(gs.current_song)

        with caplog.at_level(logging.INFO):
            await gs.skip_song()

        hits = [
            r
            for r in caplog.records
            if r.levelno == logging.INFO and "skipped the song" in r.getMessage()
        ]
        assert hits and old_uri in hits[0].getMessage()

    async def test_refused_when_no_unplayed_song_is_left(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"], songs=1)
        old_uri = _uri(gs.current_song)
        assert gs.preview_round_end()["songs_left"] == 0

        assert await gs.skip_song() == "no_songs"

        assert gs.phase == GamePhase.PLAYING
        assert gs.round == 1
        assert _uri(gs.current_song) == old_uri

    async def test_refused_outside_playing(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        await gs.end_round()

        assert await gs.skip_song() == "not_playing"
        assert gs.phase == GamePhase.REVEAL

    async def test_no_round_end_while_the_swap_is_pending(self):
        """The round is rolled back mid-swap; ending it then would score the
        old song against guesses that were just cleared."""
        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        svc = gs._media_player_service

        async def play_and_try_to_end(song):
            await gs.end_round()
            return True

        svc.play_song = AsyncMock(side_effect=play_and_try_to_end)

        assert await gs.skip_song() is None
        assert gs.phase == GamePhase.PLAYING
        assert gs.round == 1

    async def test_preview_names_the_songs_left(self):
        gs = await _start_game(make_game_state(), ["Alice", "Bob"], songs=4)
        assert gs.preview_round_end()["songs_left"] == 3


# ---------------------------------------------------------------------------
# The admin action
# ---------------------------------------------------------------------------


class TestSkipSongAction:
    async def test_admin_socket_swaps_and_broadcasts(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        old_uri = _uri(gs.current_song)
        ws = _player_ws()
        handler = _handler_for(gs, admin_ws=ws)

        await handle_admin(handler, ws, {"action": "skip_song"}, gs)

        assert _errors(ws) == []
        assert _uri(gs.current_song) != old_uri
        assert gs.round == 1
        handler.broadcast.assert_awaited_with({"type": "song_skipped", "round": 1})
        handler.broadcast_state.assert_awaited()

    async def test_host_phone_may_swap(self):
        """The host's phone is a player socket with ``is_admin``."""
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        alice = gs.get_player("Alice")
        alice.is_admin = True
        old_uri = _uri(gs.current_song)
        handler = _handler_for(gs)

        await handle_admin(handler, alice.ws, {"action": "skip_song"}, gs)

        assert _errors(alice.ws) == []
        assert _uri(gs.current_song) != old_uri

    async def test_guest_socket_is_refused(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        bob = gs.get_player("Bob")
        bob.is_admin = False
        bob.submit_guess(1990, 2.0)
        old_uri = _uri(gs.current_song)
        old_deadline = gs.deadline
        handler = _handler_for(gs, admin_ws=_player_ws())

        await handle_admin(handler, bob.ws, {"action": "skip_song"}, gs)

        assert [e["code"] for e in _errors(bob.ws)] == [ERR_NOT_ADMIN]
        assert _uri(gs.current_song) == old_uri
        assert gs.deadline == old_deadline
        assert bob.submitted is True
        handler.broadcast.assert_not_awaited()

    async def test_unknown_socket_is_refused(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = await _start_game(make_game_state(), ["Alice", "Bob"])
        old_uri = _uri(gs.current_song)
        stranger = _player_ws()
        handler = _handler_for(gs, admin_ws=_player_ws())

        await handle_admin(handler, stranger, {"action": "skip_song"}, gs)

        assert [e["code"] for e in _errors(stranger)] == [ERR_NOT_ADMIN]
        assert _uri(gs.current_song) == old_uri

    async def test_pool_exhausted_is_an_error(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = await _start_game(make_game_state(), ["Alice", "Bob"], songs=1)
        ws = _player_ws()
        handler = _handler_for(gs, admin_ws=ws)

        await handle_admin(handler, ws, {"action": "skip_song"}, gs)

        errors = _errors(ws)
        assert [e["code"] for e in errors] == [ERR_INVALID_ACTION]
        assert errors[0]["message_key"] == "NO_SONGS_LEFT_TO_SKIP"
        handler.broadcast.assert_not_awaited()
