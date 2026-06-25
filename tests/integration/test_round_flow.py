"""End-to-end integration: a full scored round through the GameState machine.

Issue #1587: ``tests/integration/`` held only ``test_placeholder.py`` (skipped
WebSocket stubs from #197). The most load-bearing untested path is the *round
lifecycle* — the seam where the #1271 mixins cooperate: ``GameSetupMixin``
(create), ``PlayerLifecycleMixin`` (join), ``RoundLifecycleMixin``
(start_game), ``RoundScoringMixin`` + ``ScoringService`` (end_round scoring),
and ``LeaderboardMixin`` (ranking). ``test_state.py`` exercises only the
*resilience* of ``end_round`` (one player throwing); it never asserts the
**happy-path scoring outcome** of a real round driven through the public API.

These tests drive ``GameState`` exactly as the WebSocket layer would —
create → join → start → submit → end_round — and assert the resulting scores,
phase transition, and leaderboard (including rank movement across rounds). No
running Home Assistant instance is required: the root ``conftest.py`` HA stubs
plus the pure ``ScoringService`` make the flow fully deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _create_fresh_game(state) -> None:
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )


def _begin_round(state, *, year: int) -> None:
    """Put the machine into a scorable PLAYING round for ``year``.

    Mirrors what ``start_round`` establishes once the media player is up:
    a ``current_song`` with the correct year, a round-start clock, and the
    PLAYING phase. We set it directly to keep the test off the HA media path.
    """
    state.current_song = {"title": "Test Song", "artist": "Test Artist", "year": year}
    state.round_start_time = state._now()
    state.phase = GamePhase.PLAYING


def _setup_started_game(*names: str):
    """Create a game, join ``names``, and start it — returns the GameState."""
    state = make_game_state()
    _create_fresh_game(state)
    for name in names:
        state.add_player(name, MagicMock())
    started, _ = state.start_game()
    assert started is True
    return state


# ---------------------------------------------------------------------------
# Single scored round — the core happy path
# ---------------------------------------------------------------------------


class TestSingleRoundScoring:
    @pytest.mark.asyncio
    async def test_exact_beats_near_beats_miss(self):
        """A full round: exact guess > near guess > far miss, and the phase
        transitions to REVEAL with the broadcast callback fired exactly once.
        """
        state = _setup_started_game("Alice", "Bob", "Carol")
        broadcast = MagicMock()

        async def _broadcast() -> None:
            broadcast()

        state.set_round_end_callback(_broadcast)

        _begin_round(state, year=1990)
        state.players["Alice"].submit_guess(1990, state._now())  # exact
        state.players["Bob"].submit_guess(1985, state._now())  # 5 off
        state.players["Carol"].submit_guess(2010, state._now())  # 20 off

        await state.end_round()

        # Phase transitioned and the UI was notified once.
        assert state.phase == GamePhase.REVEAL
        broadcast.assert_called_once()

        # Strict scoring order: exact > near > far.
        alice = state.players["Alice"]
        bob = state.players["Bob"]
        carol = state.players["Carol"]
        assert alice.years_off == 0
        assert bob.years_off == 5
        assert carol.years_off == 20
        assert alice.score > bob.score >= carol.score
        assert alice.score > 0

    @pytest.mark.asyncio
    async def test_non_submitter_scores_zero_and_is_marked_missed(self):
        """A player who never submits earns nothing and is recorded as a miss
        in the shareable round_results card (#120)."""
        state = _setup_started_game("Alice", "Bob")
        _begin_round(state, year=2000)
        state.players["Alice"].submit_guess(2000, state._now())
        # Bob stays silent.

        await state.end_round()

        bob = state.players["Bob"]
        assert bob.submitted is False
        assert bob.score == 0
        assert bob.round_results[-1] == "missed"
        assert state.players["Alice"].round_results[-1] == "exact"


# ---------------------------------------------------------------------------
# Multi-round flow — score accumulation + leaderboard rank movement
# ---------------------------------------------------------------------------


class TestMultiRoundLeaderboard:
    @pytest.mark.asyncio
    async def test_scores_accumulate_and_ranks_move_across_rounds(self):
        """Two rounds with a lead change: scores accumulate and the leaderboard
        reports the rank movement (previous_rank -> rank_change) from round 1.
        """
        state = _setup_started_game("Alice", "Bob")

        # Round 1: Bob nails it, Alice is far off -> Bob leads.
        _begin_round(state, year=1990)
        state._store_previous_ranks()
        state.players["Bob"].submit_guess(1990, state._now())
        state.players["Alice"].submit_guess(1950, state._now())
        await state.end_round()

        round1 = {e["name"]: e for e in state.get_leaderboard()}
        assert round1["Bob"]["rank"] == 1
        assert round1["Alice"]["rank"] == 2
        bob_r1 = state.players["Bob"].score

        # Round 2: Alice nails it (Bob far off). Her exact guess earns the same
        # as Bob's round-1 exact, so the two pull level on cumulative score.
        for player in state.players.values():
            player.reset_round()
        _begin_round(state, year=2000)
        state._store_previous_ranks()  # snapshot: Bob 1st, Alice 2nd
        state.players["Alice"].submit_guess(2000, state._now())
        state.players["Bob"].submit_guess(1900, state._now())
        await state.end_round()

        # Cumulative: scores are summed across rounds, not replaced.
        assert state.players["Bob"].score == bob_r1  # round-2 far miss added 0
        assert state.players["Alice"].score == bob_r1  # round-2 exact == Bob's r1

        # Movement reflects the round-1 ranks as the baseline snapshot.
        final = {e["name"]: e for e in state.get_leaderboard()}
        # Now level on score -> both share rank 1 (tie-break by name keeps order).
        assert final["Alice"]["rank"] == 1
        assert final["Bob"]["rank"] == 1
        # Alice climbed from her round-1 rank 2 into the shared lead (+1).
        assert final["Alice"]["rank_change"] == 1
        assert final["Bob"]["rank_change"] == 0

    @pytest.mark.asyncio
    async def test_final_leaderboard_reflects_played_game(self):
        """After a played round the final leaderboard carries the end-of-game
        stat block and ranks players by their accumulated score."""
        state = _setup_started_game("Alice", "Bob")
        _begin_round(state, year=1990)
        state.players["Alice"].submit_guess(1990, state._now())
        state.players["Bob"].submit_guess(1995, state._now())
        await state.end_round()

        board = state.get_final_leaderboard()

        assert [e["name"] for e in board] == ["Alice", "Bob"]
        assert board[0]["rank"] == 1
        # Final stat block keys are present for every entry.
        for entry in board:
            assert {"best_streak", "rounds_played", "bets_won"} <= entry.keys()
