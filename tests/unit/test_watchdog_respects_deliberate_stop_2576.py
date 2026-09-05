"""#2576: the TTS resume watchdog must not undo a deliberate stop.

After every round start a watchdog runs for ~20 seconds and pushes `media_play`
as soon as the player reports `paused`, or reports `idle` with a title twice in
a row. It checked neither the game phase nor `song_stopped`, so it read two
*wanted* states as a hang:

* the host taps "stop song" — `media_stop` leaves a Music Assistant player as
  `idle` WITH a title, which is exactly the stuck signature; the watchdog
  restarted the song the host had just stopped.
* the game pauses (host phone drops off the wifi) — `pause_game` stops the
  speaker, and the watchdog pushed play, so the music kept going under the
  PAUSED banner.

The watchdog itself is a closure inside `_start_round_locked` and cannot be
called directly, so this pins the guard in the source *and* the two inputs it
relies on: that stopping sets `song_stopped`, and that pausing leaves PLAYING.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state

SRC = (
    Path(__file__).parents[2]
    / "custom_components"
    / "beatify"
    / "game"
    / "state_lifecycle.py"
).read_text(encoding="utf-8")


class TestWatchdogGuard:
    def test_the_guard_exists(self):
        assert "song_stopped" in SRC, "watchdog does not consult song_stopped"
        assert "self.phase != GamePhase.PLAYING" in SRC

    def test_the_guard_runs_before_the_state_is_read(self):
        """Order is the whole point: reading the player first and deciding
        afterwards would still fire one kick on the tick where the host
        stopped the song."""
        guard = SRC.index("playback stopped on purpose")
        # the first `states.get` inside the polling loop
        loop = SRC.index("for tick in range(20):")
        lookup = SRC.index("st = self._hass.states.get(self.media_player)", loop)
        assert loop < guard < lookup


class TestTheInputsTheGuardRelieson:
    @pytest.mark.asyncio
    async def test_pausing_leaves_the_playing_phase(self):
        state = make_game_state()
        state.phase = GamePhase.PLAYING
        await state.pause_game("admin_disconnected")
        assert state.phase is GamePhase.PAUSED

    def test_song_stopped_is_a_per_round_flag(self):
        """`song_stopped` belongs to the round — a stop in round 3 must not
        keep the watchdog disarmed in round 4."""
        state = make_game_state()
        state.song_stopped = True
        state._round_manager.reset()
        assert state.song_stopped is False
