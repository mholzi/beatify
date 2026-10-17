"""#3199 — intro mode follow-ups from the #3095 report.

The previous round's song kept playing under the intro splash, because the
deferred branch of ``_start_round_locked`` skipped ``play_song`` without ever
stopping the speaker. The intro-song length (playback cut after
``INTRO_DURATION_SECONDS``) is covered with the sample tests in
``test_song_sample_3152.py``; here: the stop on the deferred path, and that
confirming the splash still starts the deferred song.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state


def _service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.stop = AsyncMock()
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


def _game(service: MagicMock):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = service
    gs.platform = "music_assistant"
    ws = MagicMock()
    ws.closed = False
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True
    return gs


class TestPreviousSongStopsForTheSplash:
    async def test_a_deferred_round_stops_the_previous_song(self):
        svc = _service()
        gs = _game(svc)

        with patch.object(gs, "_prepare_intro_round", return_value=True):
            assert await gs.start_round() is True

        svc.stop.assert_awaited_once_with()
        svc.play_song.assert_not_awaited()
        assert gs.phase == GamePhase.PLAYING
        gs.cancel_timer()

    async def test_a_normal_round_is_not_stopped_first(self):
        svc = _service()
        gs = _game(svc)

        with patch.object(gs, "_prepare_intro_round", return_value=False):
            assert await gs.start_round() is True

        svc.stop.assert_not_awaited()
        svc.play_song.assert_awaited()
        gs.cancel_timer()
        gs._round_manager._cancel_intro_timer()

    async def test_a_failing_stop_does_not_break_the_round_start(self):
        svc = _service()
        svc.stop = AsyncMock(side_effect=RuntimeError("speaker offline"))
        gs = _game(svc)

        with patch.object(gs, "_prepare_intro_round", return_value=True):
            assert await gs.start_round() is True

        assert gs.phase == GamePhase.PLAYING
        gs.cancel_timer()

    async def test_confirming_the_splash_still_starts_the_deferred_song(self):
        svc = _service()
        gs = _game(svc)
        rm = gs._round_manager
        gs.phase = GamePhase.PLAYING
        rm.is_intro_round = True
        rm._intro_splash_pending = True
        rm._intro_splash_deferred_song = {"uri": "spotify:track:x"}
        gs.play_deferred_song = AsyncMock(return_value=True)
        gs._on_round_end = AsyncMock()

        await gs.confirm_intro_splash()

        gs.play_deferred_song.assert_awaited_once()
        assert gs.intro_splash_pending is False
        svc.stop.assert_not_awaited()
        gs.cancel_timer()
        rm._cancel_intro_timer()
        rm._cancel_sample_timer()
