"""#3286 — a failed song start in an intro round must skip the song.

The deferred intro song was started by ``confirm_intro_splash`` and its result
was dropped: the splash was confirmed, the round timer armed and the round ran
(and was scored) in silence. A normal round skips the song and tries the next.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state


def _service(reason: str | None) -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    # First start (the deferred intro song) fails, the next song plays.
    svc.play_song = AsyncMock(side_effect=[False, True])
    svc.stop = AsyncMock()
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.last_failure_reason = reason
    return svc


def _intro_selection(gs, results):
    """Stand-in for prepare_intro_round that sets the flags the real one sets."""
    outcomes = iter(results)

    def _prepare(song):
        rm = gs._round_manager
        rm.is_intro_round = rm._intro_splash_pending = next(outcomes)
        rm._intro_splash_deferred_song = dict(song) if rm.is_intro_round else None
        return rm.is_intro_round

    return _prepare


async def _intro_round_with_failing_start(reason: str | None):
    svc = _service(reason)
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(5),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = svc
    gs.platform = "music_assistant"
    ws = MagicMock()
    ws.closed = False
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True
    gs._on_round_end = AsyncMock()

    # Round 1 is the intro round (deferred); the retry is a normal round.
    with patch.object(
        gs, "_prepare_intro_round", side_effect=_intro_selection(gs, [True, False])
    ):
        assert await gs.start_round() is True
        failed_song = dict(gs.current_song)
        assert gs.intro_splash_pending is True
        svc.play_song.assert_not_awaited()
        await gs.confirm_intro_splash()
    return gs, svc, failed_song


@pytest.mark.parametrize("reason", ["unavailable", "error", "rate_limited"])
async def test_failed_intro_start_skips_to_the_next_song(reason, caplog):
    with caplog.at_level(logging.INFO):
        gs, svc, failed_song = await _intro_round_with_failing_start(reason)
    try:
        assert svc.play_song.await_count == 2
        assert "Intro splash confirmed" not in caplog.text
        assert gs.round == 1  # the failed round gave its number back
        assert gs.current_song["uri"] != failed_song["uri"]
        assert gs.intro_splash_pending is False
        assert gs.is_intro_round is False
        assert gs.phase == GamePhase.PLAYING
        assert gs._consecutive_playback_failures == 0
    finally:
        gs.cancel_timer()
        gs._round_manager._cancel_intro_timer()
        gs._round_manager._cancel_sample_timer()


async def test_successful_intro_start_still_confirms_the_splash(caplog):
    svc = _service(None)
    svc.play_song = AsyncMock(return_value=True)
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = svc
    gs.platform = "music_assistant"
    gs._on_round_end = AsyncMock()
    with patch.object(
        gs, "_prepare_intro_round", side_effect=_intro_selection(gs, [True])
    ):
        await gs.start_round()
    with caplog.at_level(logging.INFO):
        await gs.confirm_intro_splash()
    try:
        assert "Intro splash confirmed" in caplog.text
        assert gs.round == 1
    finally:
        gs.cancel_timer()
        gs._round_manager._cancel_intro_timer()
        gs._round_manager._cancel_sample_timer()
