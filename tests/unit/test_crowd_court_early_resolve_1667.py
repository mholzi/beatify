"""Crowd-Court resolves as soon as every eligible voter has voted (#1667).

The REVEAL vote window exists to give the room 30 s to weigh in on a near-miss.
Once the room *has* weighed in, the rest of the countdown is dead air. These
tests pin the predicate that decides "everyone has voted", including the two
cases where it must deliberately stay False and let the timer run.

Eligibility follows the rules the WS handler already enforces (`guessing.py`):
active players only, and nobody votes on their own near-miss.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import make_game_state


def _game_with_near_miss(players=("Alice", "Bob", "Carol")):
    """A game in near-miss state: Alice's title guess is close but not exact."""
    gs = make_game_state()
    gs._challenge_manager.configure(
        artist_challenge_enabled=False,
        movie_quiz_enabled=False,
        title_artist_mode=True,
    )
    gs._challenge_manager.init_round({"title": "Word Up Now", "artist": "A Word"})
    gs._challenge_manager.submit_title_artist_guess(
        "Alice", "Word Up Later", "A Word", 1.0
    )
    for name in players:
        # `is_active` is `connected and ws is not None and not ws.closed`, and a
        # bare MagicMock's `.closed` is truthy — so an unconfigured mock socket
        # reads as a stale ghost and every player would be filtered out.
        ws = MagicMock()
        ws.closed = False
        gs.add_player(name, ws)
    for p in gs.players.values():
        p.connected = True
    return gs


def _player(gs, name):
    """Look a player up by name — the registry is keyed by player_id (#1664)."""
    return next(p for p in gs.players.values() if p.name == name)


def _near_miss_id(gs) -> str:
    return gs.get_near_misses()[0]["id"]


class TestAllVotesIn:
    def test_false_while_a_vote_is_missing(self):
        gs = _game_with_near_miss()
        nm = _near_miss_id(gs)
        gs.register_title_artist_vote("Bob", nm, True)
        # Carol is active and eligible but has not voted.
        assert gs.all_crowd_court_votes_in() is False

    def test_true_once_every_eligible_player_voted(self):
        gs = _game_with_near_miss()
        nm = _near_miss_id(gs)
        gs.register_title_artist_vote("Bob", nm, True)
        gs.register_title_artist_vote("Carol", nm, False)
        # Alice owns the near-miss and may not vote on it — her silence must
        # not block the resolve, or early resolve could never fire at all.
        assert gs.all_crowd_court_votes_in() is True

    def test_disconnected_player_does_not_block(self):
        # #928: a stale ghost must not hold the room hostage. Same rule as
        # PlayerRegistry.all_submitted, which is why this reads is_active.
        gs = _game_with_near_miss()
        nm = _near_miss_id(gs)
        _player(gs, "Carol").connected = False
        gs.register_title_artist_vote("Bob", nm, True)
        assert gs.all_crowd_court_votes_in() is True

    def test_stale_ghost_does_not_block(self):
        # The case that actually separates `is_active` from `connected`:
        # `connected` is still True, but the socket is closed and
        # `_handle_disconnect` has not run yet (#928). Without this test,
        # swapping `is_active` for `connected` passes the whole suite — the
        # disconnect test above clears `connected` and so cannot tell them
        # apart. Verified by mutation.
        gs = _game_with_near_miss()
        nm = _near_miss_id(gs)
        carol = _player(gs, "Carol")
        carol.connected = True
        carol.ws.closed = True
        gs.register_title_artist_vote("Bob", nm, True)
        assert gs.all_crowd_court_votes_in() is True

    def test_eliminated_player_does_not_block(self):
        # #827: eliminated players are out of the round entirely.
        gs = _game_with_near_miss()
        nm = _near_miss_id(gs)
        _player(gs, "Carol").eliminated = True
        gs.register_title_artist_vote("Bob", nm, True)
        assert gs.all_crowd_court_votes_in() is True

    def test_every_near_miss_must_be_complete(self):
        # Two near-misses, one fully voted, one not: still False. Resolving on
        # the first complete one would cut the vote on the second short.
        gs = _game_with_near_miss()
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", "Word Up Now", "A Word Or Two", 1.0
        )
        ids = [nm["id"] for nm in gs.get_near_misses()]
        assert len(ids) >= 2, ids
        gs.register_title_artist_vote("Bob", ids[0], True)
        gs.register_title_artist_vote("Carol", ids[0], True)
        assert gs.all_crowd_court_votes_in() is False

    def test_solo_game_falls_back_to_the_timer(self):
        # Only Alice is in the game and the near-miss is hers, so nobody may
        # vote. "Everyone voted" can never become true — returning True here
        # would resolve instantly and silently skip the crowd vote.
        gs = _game_with_near_miss(players=("Alice",))
        assert gs.all_crowd_court_votes_in() is False

    def test_no_near_misses_is_false(self):
        # Nothing to decide; the window is not even opened on this path.
        gs = make_game_state()
        assert gs.all_crowd_court_votes_in() is False

    def test_no_active_players_is_false(self):
        gs = _game_with_near_miss()
        for p in gs.players.values():
            p.connected = False
        assert gs.all_crowd_court_votes_in() is False


class TestWindowResolvesEarly:
    """End-to-end: the open window actually closes once the votes are in.

    The predicate above is only half the feature — this drives the real
    REVEAL window and asserts it stops waiting. The window is the production
    30 s one, so a run that finishes in ~1 s can only mean it broke out early.
    """

    async def test_window_closes_without_waiting_out_the_timer(self):
        import asyncio

        from custom_components.beatify.game.state import GamePhase
        from tests.unit.test_state_title_artist_window import _start_round

        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        # Alice near-misses the title, Bob is exact -> exactly one near-miss.
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
            p.ws.closed = False  # make is_active true (see helper above)
        await gs.end_round()
        assert gs.phase == GamePhase.REVEAL
        assert gs.is_title_artist_voting_open() is True

        nm = gs.get_near_misses()[0]["id"]
        # Bob is the only eligible voter: Alice owns the near-miss.
        gs.register_title_artist_vote("Bob", nm, True)

        # Poll interval is 0.5 s; give it two, far short of the 30 s window.
        await asyncio.sleep(1.5)

        assert gs.is_title_artist_voting_open() is False, (
            "window still open — early resolve did not fire"
        )
        assert gs._challenge_manager.title_artist_challenge.resolved is True
        gs._cancel_auto_advance()
