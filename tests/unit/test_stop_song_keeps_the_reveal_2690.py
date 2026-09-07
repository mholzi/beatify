"""#2690: the host's "stop song" must not collapse the following reveal.

`admin_stop_song` sends `media_stop` and sets `song_stopped`; the round keeps
running to its deadline. When it ends, `_schedule_song_end_auto_advance` arms
`_reveal_auto_advance`, whose wait loop breaks on `_song_finished()`. That poll
read only the speaker — and the speaker has been `idle` since the host tapped
Stop — so the very first tick at 2s said "the song is over" and pulled the next
round. The answer, the scores and the reaction buttons were on screen for about
two seconds.

The poll's job is not "is the speaker quiet" but "did the round's song end", and
it already refuses two other kinds of quiet: a transient `unavailable` blip
(#1374) and a TTS announcement holding the device (#2576's sibling). A
deliberate stop is a third. The game records it in the per-round `song_stopped`
flag, which the resume watchdog already reads for exactly this reason (#2576) —
so the fix is one more consumer of that signal, and the dwell falls through to
whatever the host configured.

Nothing covered stop_song together with auto-advance before this file;
`test_pause_and_stop_hints_2552_2554.py` only checks the UI chips.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.game.state import GamePhase, GameState
from tests.conftest import make_game_state, make_songs

# `_reveal_auto_advance` / `_reveal_idle_halt` walk the wait in 2.0s ticks, and
# fall back to a 360s stall-guard when no dwell is configured.
POLL = 2.0
HARD_CAP_TICKS = 180


class _TickingSleep:
    """Stand-in for ``asyncio.sleep`` that counts the auto-advance's polls.

    The wait loop is a fixed 2s tick, so the number of sleeps IS the dwell:
    one tick means the reveal lasted two seconds, 180 means it ran to the
    stall-guard. Counting them is how these tests measure a duration without
    spending it.
    """

    def __init__(self) -> None:
        self.ticks = 0

    async def __call__(self, _seconds: float) -> None:
        self.ticks += 1
        if self.ticks > HARD_CAP_TICKS + 10:
            raise AssertionError("the auto-advance never left its wait loop")

    @property
    def reveal_seconds(self) -> float:
        return self.ticks * POLL


def _game_in_reveal(**game_kwargs) -> GameState:
    """A game parked on REVEAL with a speaker that reports `idle`.

    `idle` is what both a finished track and a stopped one look like — which is
    the whole point: only `song_stopped` separates them.
    """
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **game_kwargs,
    )
    speaker = MagicMock()
    speaker.get_playback_state.return_value = "idle"
    speaker.stop = AsyncMock()
    state._media_player_service = speaker
    state.phase = GamePhase.REVEAL
    state.start_round = AsyncMock(return_value=True)
    return state


# ---------------------------------------------------------------------------
# The poll itself: a deliberate stop is not a song end
# ---------------------------------------------------------------------------


class TestSongFinishedIgnoresADeliberateStop:
    def test_idle_after_a_host_stop_is_not_a_song_end(self):
        state = _game_in_reveal()
        state.song_stopped = True
        assert state._song_finished() is False

    def test_idle_is_still_a_song_end_when_nobody_stopped_it(self):
        """The guard must not swallow the ordinary signal it exists to protect."""
        state = _game_in_reveal()
        assert state.song_stopped is False
        assert state._song_finished() is True

    def test_a_stop_never_reaches_the_speaker_at_all(self):
        """Cheap short-circuit: no state read while the flag is up."""
        state = _game_in_reveal()
        state.song_stopped = True
        state._song_finished()
        state._media_player_service.get_playback_state.assert_not_called()

    def test_the_flag_belongs_to_the_round_it_was_raised_in(self):
        """A stop in round 3 must not keep round 4's song-end undetectable.

        `RoundManager.initialize_round` clears the flag on every commit, so the
        poll is back to reading the speaker the moment the next song starts.
        """
        state = _game_in_reveal()
        state.song_stopped = True
        assert state._song_finished() is False
        state._round_manager.song_stopped = False  # what a new round commits
        assert state._song_finished() is True


# ---------------------------------------------------------------------------
# The behaviour the party sees: how long the reveal actually stays up
# ---------------------------------------------------------------------------


class TestTheRevealSurvivesAStop:
    async def test_stopped_song_no_longer_collapses_the_reveal(self):
        """The #2690 regression, in the default "at song end" configuration.

        Before the fix this advanced on the first tick — a two-second reveal.
        """
        state = _game_in_reveal(reveal_auto_advance=0)
        state.song_stopped = True
        sleep = _TickingSleep()

        with patch("asyncio.sleep", new=sleep):
            await state._reveal_auto_advance(0)

        assert sleep.reveal_seconds > 2.0, (
            "the reveal collapsed on the first poll — #2690 is back"
        )
        # With the song-end signal gone the 360s stall-guard governs; the host's
        # "Next round" is still the ordinary way out, as "0 = manual only" says.
        assert sleep.ticks == HARD_CAP_TICKS
        state.start_round.assert_awaited_once()

    async def test_an_unstopped_song_end_still_advances_immediately(self):
        """The counterpart: a track that really ran out must not be delayed."""
        state = _game_in_reveal(reveal_auto_advance=0)
        sleep = _TickingSleep()

        with patch("asyncio.sleep", new=sleep):
            await state._reveal_auto_advance(0)

        assert sleep.ticks == 1
        state.start_round.assert_awaited_once()

    @pytest.mark.parametrize("dwell", [10, 20, 45])
    async def test_a_configured_dwell_still_governs_after_a_stop(self, dwell):
        """With a dwell set, the reveal lasts exactly that — not two seconds,
        and not the stall-guard either."""
        state = _game_in_reveal(reveal_auto_advance=dwell)
        state.song_stopped = True
        sleep = _TickingSleep()

        with patch("asyncio.sleep", new=sleep):
            await state._reveal_auto_advance(dwell)

        assert sleep.reveal_seconds == pytest.approx(dwell, abs=POLL)
        state.start_round.assert_awaited_once()

    async def test_the_zero_guess_halt_no_longer_fires_at_two_seconds(self):
        """The idle-halt shares the poll, so it shared the bug: it "detected"
        song-end two seconds into a reveal nobody had guessed in. It holds on
        REVEAL either way, but it should not race there."""
        state = _game_in_reveal(reveal_auto_advance=0)
        state.song_stopped = True
        sleep = _TickingSleep()

        with patch("asyncio.sleep", new=sleep):
            await state._reveal_idle_halt()

        assert sleep.ticks == HARD_CAP_TICKS
        state.start_round.assert_not_awaited()


# ---------------------------------------------------------------------------
# TTS: the announcement grace hid this bug; it must not now stack with the fix
# ---------------------------------------------------------------------------


class TestTheAnnouncementGraceDoesNotStack:
    """With announcements on, `_song_finished` was already returning False for
    the whole announcement plus a 6s resume window — which is why the two-second
    reveal only reproduced with TTS off. Both suppressions now apply at once, so
    the thing to prove is that they do not add up: the dwell is one absolute
    timer measured from REVEAL entry, not a sum of the reasons to keep waiting.
    """

    async def test_the_dwell_is_the_same_with_and_without_an_announcement(self):
        dwell = 20

        without = _game_in_reveal(reveal_auto_advance=dwell)
        without.song_stopped = True
        quiet = _TickingSleep()
        with patch("asyncio.sleep", new=quiet):
            await without._reveal_auto_advance(dwell)

        speaking = _game_in_reveal(reveal_auto_advance=dwell)
        speaking.song_stopped = True
        # An announcement in flight, and the resume window still open behind it.
        speaking._announce_busy_until = time.monotonic() + 30.0
        talking = _TickingSleep()
        with patch("asyncio.sleep", new=talking):
            await speaking._reveal_auto_advance(dwell)

        assert talking.ticks == quiet.ticks == dwell / POLL
        speaking.start_round.assert_awaited_once()


# ---------------------------------------------------------------------------
# The host action end to end: the Stop button raises the flag the poll reads
# ---------------------------------------------------------------------------


class TestTheStopButtonReachesThePoll:
    async def test_admin_stop_song_leaves_the_reveal_poll_unconvinced(self):
        """Drive the real WS handler rather than setting the flag by hand — the
        seam between `admin_stop_song` and the auto-advance is the bug."""
        from custom_components.beatify.server.ws_handlers.admin import admin_stop_song

        state = _game_in_reveal()
        state.phase = GamePhase.PLAYING  # the Stop button only exists mid-round
        handler = MagicMock()
        handler.broadcast = AsyncMock()
        ws = AsyncMock()

        await admin_stop_song(handler, ws, {"action": "stop_song"}, state)

        state._media_player_service.stop.assert_awaited_once()
        handler.broadcast.assert_awaited_once_with({"type": "song_stopped"})
        # And now the round ends and REVEAL arms the poll:
        state.phase = GamePhase.REVEAL
        assert state._song_finished() is False
