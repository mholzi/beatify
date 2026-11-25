"""The room hears about a slow or failed round 2+ song start (#3604).

From round 2 on, ``_start_round_locked`` waits on ``play_song`` while the
phase stays the previous round's REVEAL. Under rate limiting that wait took up
to 27 s, and no client got a single message. Now:

* ``song_starting`` goes out once the start has waited
  ``SONG_STARTING_HINT_DELAY_SECONDS`` without confirmed playback;
* a normal start (1-2 s) sends nothing, so the hint never flickers;
* ``song_start_failed`` goes out when ``_skip_failed_start`` moves on to the
  next song;
* round 1 keeps its own vinyl loader (``game_starting``) and sends neither.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs

#: Stand-in for the 3 s delay, so the tests run in milliseconds.
DELAY = 0.05


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = "error"
    svc.last_attempted_uri = "spotify:track:1"
    svc.play_song = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    return svc


def _slow_play(seconds: float, result: bool = True):
    async def play(_song):
        await asyncio.sleep(seconds)
        return result

    return play


def _in_turn(*plays):
    """One ``play_song`` side effect per attempt, in order."""
    queue = list(plays)

    async def play(song):
        return await queue.pop(0)(song)

    return play


async def _game_in_reveal():
    """A game whose round 1 played and that now sits in REVEAL."""
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    gs._media_player_service = _stub_media_service()
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    gs.pause_game = AsyncMock()
    assert await gs.start_round()
    gs.cancel_timer()
    gs._set_phase(GamePhase.REVEAL)
    notices = AsyncMock()
    gs.set_song_start_notice_callback(notices)
    return gs, notices


def _sent(notices: AsyncMock) -> list[str]:
    return [call.args[0] for call in notices.await_args_list]


@pytest.fixture(autouse=True)
def _short_delay():
    with patch(
        "custom_components.beatify.game.state_lifecycle.SONG_STARTING_HINT_DELAY_SECONDS",
        DELAY,
    ):
        yield


@pytest.mark.asyncio
async def test_a_slow_start_tells_the_room_the_song_is_loading() -> None:
    gs, notices = await _game_in_reveal()
    gs._media_player_service.play_song = AsyncMock(side_effect=_slow_play(DELAY * 4))

    assert await gs.start_round()

    assert _sent(notices) == ["song_starting"]
    assert gs.phase == GamePhase.PLAYING
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_a_fast_start_sends_nothing() -> None:
    gs, notices = await _game_in_reveal()
    gs._media_player_service.play_song = AsyncMock(side_effect=_slow_play(DELAY / 5))

    assert await gs.start_round()
    # Give a cancelled hint every chance to fire anyway.
    await asyncio.sleep(DELAY * 2)

    notices.assert_not_awaited()
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_a_skipped_song_is_announced_then_the_next_one_starts() -> None:
    gs, notices = await _game_in_reveal()
    gs._media_player_service.play_song = AsyncMock(side_effect=[False, True])

    assert await gs.start_round()

    assert _sent(notices) == ["song_start_failed"]
    gs.pause_game.assert_not_awaited()
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_a_slow_failure_then_a_slow_retry_goes_back_to_loading() -> None:
    """The mock-up: after "trying another one", a hanging retry reads "loading"."""
    gs, notices = await _game_in_reveal()
    gs._media_player_service.play_song = AsyncMock(
        side_effect=_in_turn(_slow_play(DELAY * 3, False), _slow_play(DELAY * 3))
    )

    assert await gs.start_round()

    assert _sent(notices) == ["song_starting", "song_start_failed", "song_starting"]
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_a_failure_that_pauses_the_game_sends_no_skip_notice() -> None:
    gs, notices = await _game_in_reveal()
    gs._media_player_service.play_song = AsyncMock(return_value=False)

    assert not await gs.start_round()

    # The first failure skips (announced), the second spends the budget and
    # pauses; the pause screen is the room's answer for that one.
    assert _sent(notices) == ["song_start_failed"]
    gs.pause_game.assert_awaited_once_with("media_player_error")


@pytest.mark.asyncio
async def test_round_one_keeps_its_own_loader() -> None:
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    svc = _stub_media_service()
    svc.play_song = AsyncMock(
        side_effect=_in_turn(_slow_play(0, False), _slow_play(DELAY * 4))
    )
    gs._media_player_service = svc
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    gs.pause_game = AsyncMock()
    notices = AsyncMock()
    gs.set_song_start_notice_callback(notices)

    assert gs.phase == GamePhase.LOBBY
    assert await gs.start_round()

    notices.assert_not_awaited()
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_a_broken_notice_never_breaks_the_start() -> None:
    gs, notices = await _game_in_reveal()
    notices.side_effect = RuntimeError("socket gone")
    gs._media_player_service.play_song = AsyncMock(side_effect=[False, True])

    assert await gs.start_round()
    assert gs.phase == GamePhase.PLAYING
    gs.cancel_timer()


@pytest.mark.asyncio
async def test_the_handler_broadcasts_the_typed_message() -> None:
    handler = SimpleNamespace(broadcast=AsyncMock())

    await BeatifyWebSocketHandler.broadcast_song_start_notice(handler, "song_starting")
    await BeatifyWebSocketHandler.broadcast_song_start_notice(
        handler, "song_start_failed"
    )

    assert [c.args[0] for c in handler.broadcast.await_args_list] == [
        {"type": "song_starting"},
        {"type": "song_start_failed"},
    ]
