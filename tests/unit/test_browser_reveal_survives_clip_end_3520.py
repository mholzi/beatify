"""#3520: a browser target's clip ending is not a song end for the REVEAL dwell.

A browser target caps the round at its 30s preview, and the page reports
`ended` (mapped to `idle`) when the clip finishes -- about when the round ends.
`_song_finished()` read that as the track running out, so the first 2s poll of
`_reveal_auto_advance(0)` skipped the reveal. A real speaker keeps playing the
full track through REVEAL, so there `idle` is still the song-end signal.
"""

from __future__ import annotations

from unittest.mock import patch

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.providers import PLATFORM_BROWSER
from tests.unit.test_stop_song_keeps_the_reveal_2690 import (
    HARD_CAP_TICKS,
    _game_in_reveal,
    _TickingSleep,
)


def _browser_game(**kwargs):
    state = _game_in_reveal(**kwargs)
    state.platform = PLATFORM_BROWSER
    state._media_player_service.get_playback_state.return_value = "idle"  # `ended`
    return state


def test_browser_clip_ended_is_not_a_song_end():
    assert _browser_game()._song_finished() is False


def test_real_speaker_idle_is_still_a_song_end():
    state = _game_in_reveal()
    assert state.platform != PLATFORM_BROWSER
    assert state._song_finished() is True


async def test_browser_reveal_survives_first_poll_in_song_end_mode():
    state = _browser_game(reveal_auto_advance=0)
    sleep = _TickingSleep()
    with patch("asyncio.sleep", new=sleep):
        await state._reveal_auto_advance(0)
    assert sleep.ticks == HARD_CAP_TICKS  # stall-guard, not 2s
    state.start_round.assert_awaited_once()


async def test_browser_reveal_honours_configured_dwell():
    state = _browser_game(reveal_auto_advance=20)
    sleep = _TickingSleep()
    with patch("asyncio.sleep", new=sleep):
        await state._reveal_auto_advance(20)
    assert sleep.reveal_seconds == 20
    state.start_round.assert_awaited_once()


async def test_browser_idle_halt_holds_and_does_not_advance():
    state = _browser_game(reveal_auto_advance=0)
    sleep = _TickingSleep()
    with patch("asyncio.sleep", new=sleep):
        await state._reveal_idle_halt()
    assert sleep.ticks == HARD_CAP_TICKS
    assert state.phase == GamePhase.REVEAL
    state.start_round.assert_not_awaited()
