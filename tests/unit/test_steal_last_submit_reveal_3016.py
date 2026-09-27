"""A steal by the last player must end the round like a submit does (#3016).

Reported as "doesn't happen every time". The condition that decides it is the
artist (or movie) bonus challenge: when the player being stolen from had tapped
a *wrong* bonus tile, the early-reveal gate started waiting for every active
player's bonus guess — including the stealer, whose phone shows them as done
and gives no hint that anything is still owed. The round sat on PLAYING until
the timer ran out or the host pressed "next song".

A correct tap produces a winner and skips the wait, and no tap at all skips it
too, which is why the bug only showed up some of the time.
"""

from __future__ import annotations

from custom_components.beatify.game.challenges import ArtistChallenge, MovieChallenge
from custom_components.beatify.game.state import GamePhase
from tests.unit.test_ws_powerup_deadline_2335 import _playing_game


async def _steal_after_bob_tapped(challenge: str):
    handler, gs, ws = await _playing_game(deadline_passed=False)
    bob = gs.get_player("Bob")
    if challenge == "artist":
        gs.artist_challenge = ArtistChallenge(
            correct_artist="Right", options=["Right", "Wrong", "Other"]
        )
        bob.has_artist_guess = True  # tapped, but wrong: no winner
    else:
        gs.movie_challenge = MovieChallenge(
            correct_movie="Right", options=["Right", "Wrong", "Other"]
        )
        bob.has_movie_guess = True
        gs.movie_challenge.wrong_guesses.append({"name": "Bob", "guess": "Wrong"})
    await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
    return gs


class TestStealAsLastSubmitReveals:
    async def test_after_a_wrong_artist_tap(self):
        gs = await _steal_after_bob_tapped("artist")
        assert gs.get_player("Alice").submitted is True
        assert gs.phase == GamePhase.REVEAL
        gs._cancel_auto_advance()

    async def test_after_a_wrong_movie_tap(self):
        gs = await _steal_after_bob_tapped("movie")
        assert gs.phase == GamePhase.REVEAL
        gs._cancel_auto_advance()

    async def test_plain_steal_still_reveals(self):
        handler, gs, ws = await _playing_game(deadline_passed=False)
        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})
        assert gs.phase == GamePhase.REVEAL
        gs._cancel_auto_advance()


class TestTheBonusWaitStillHoldsForSubmitters:
    """The fix exempts stealers only — the existing rule is unchanged."""

    async def test_a_normal_submitter_is_still_waited_for(self):
        handler, gs, _ws = await _playing_game(deadline_passed=False)
        gs.artist_challenge = ArtistChallenge(
            correct_artist="Right", options=["Right", "Wrong", "Other"]
        )
        gs.get_player("Bob").has_artist_guess = True
        alice = gs.get_player("Alice")
        alice.submit_guess(1990, gs.current_time())
        assert gs.check_all_guesses_complete() is False
        gs._cancel_auto_advance()
