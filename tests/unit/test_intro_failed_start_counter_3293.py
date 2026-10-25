"""#3293 — a failed intro start must take the same skip path as a normal round.

#3286 made a failed deferred intro start skip to the next song, but the skip
diverged from a normal round's in three ways (live test of v4.8.7-rc1):

1. ``total_rounds`` was not lowered (#3279), so the game ended a round early
   while the counter still promised the configured total.
2. The rolled-back round kept its long-passed placeholder deadline. While the
   next song was starting the phase was PLAYING with the previous round's
   number, so the server backstop ended that round a second time and revealed
   the song that never played.
3. Consequently the backstop, not the round timer, moved the game on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.const import MAX_CONSECUTIVE_PLAYBACK_FAILURES
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state


def _intro_selection(gs, results):
    """Stand-in for prepare_intro_round that sets the flags the real one sets."""
    outcomes = iter(results)

    def _prepare(song):
        rm = gs._round_manager
        rm.is_intro_round = rm._intro_splash_pending = next(outcomes)
        rm._intro_splash_deferred_song = dict(song) if rm.is_intro_round else None
        return rm.is_intro_round

    return _prepare


def _game(svc):
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
    return gs


def _service():
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.stop = AsyncMock()
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.last_failure_reason = "rate_limited"
    svc.last_attempted_uri = None
    return svc


def _cleanup(gs):
    gs.cancel_timer()
    gs._round_manager._cancel_intro_timer()
    gs._round_manager._cancel_sample_timer()


async def test_failed_intro_start_matches_the_normal_skip_path():
    svc = _service()
    gs = _game(svc)
    seen_during_retry: dict = {}

    async def play(song):
        # Call 1: round 1 (normal). Call 2: the deferred intro song of
        # round 2, which fails. Call 3: the next song, which starts slowly.
        play.calls += 1
        if play.calls == 2:
            return False
        if play.calls == 3:
            # Music Assistant can take up to 25 s here. The server backstop
            # ticks meanwhile; it must find nothing to end.
            seen_during_retry["deadline_passed"] = gs.is_deadline_passed()
            seen_during_retry["backstop"] = await gs.force_end_round_if_overdue()
            seen_during_retry["phase"] = gs.phase
        return True

    play.calls = 0
    svc.play_song = AsyncMock(side_effect=play)

    try:
        with patch.object(
            gs,
            "_prepare_intro_round",
            side_effect=_intro_selection(gs, [False, True, False]),
        ):
            assert await gs.start_round() is True
            await gs.end_round()
            assert gs.phase == GamePhase.REVEAL
            reveals_before = gs._on_round_end.await_count
            assert gs.total_rounds == 5

            assert await gs.start_round() is True
            assert gs.round == 2
            assert gs.intro_splash_pending is True
            failed_song = dict(gs.current_song)
            # The host sat on the splash: the placeholder deadline is long gone.
            gs._round_manager.deadline = 0

            await gs.confirm_intro_splash()

        # 1. The dropped intro song lowers the counter like any skipped song.
        assert gs.total_rounds == 4

        # 2. Round 1 is not ended a second time and the failed song is
        #    never revealed; the round number does not go backwards.
        assert seen_during_retry == {
            "deadline_passed": False,
            "backstop": False,
            "phase": GamePhase.PLAYING,
        }
        assert gs._on_round_end.await_count == reveals_before
        assert gs.round == 2
        assert gs.phase == GamePhase.PLAYING
        assert gs.current_song["uri"] != failed_song["uri"]

        # 3. The new round runs on its own timer, with a fresh deadline.
        assert gs._round_manager._timer_task is not None
        assert gs.is_deadline_passed() is False
        assert await gs.force_end_round_if_overdue() is False
    finally:
        _cleanup(gs)


async def test_failed_intro_start_pauses_from_reveal_after_the_budget():
    svc = _service()
    svc.last_failure_reason = "error"
    svc.play_song = AsyncMock(return_value=False)
    gs = _game(svc)
    gs._consecutive_playback_failures = MAX_CONSECUTIVE_PLAYBACK_FAILURES - 1
    try:
        with patch.object(
            gs, "_prepare_intro_round", side_effect=_intro_selection(gs, [True])
        ):
            assert await gs.start_round() is True
            await gs.confirm_intro_splash()

        assert gs.phase == GamePhase.PAUSED
        assert gs._previous_phase == GamePhase.REVEAL
        assert gs.round == 0
        assert gs.total_rounds == 4
        assert gs._consecutive_playback_failures == 0
    finally:
        _cleanup(gs)
