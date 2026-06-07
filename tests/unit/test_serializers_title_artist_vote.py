"""Tests for near_misses + voting_open in the REVEAL title/artist serializer (P4)."""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from tests.conftest import make_game_state


def _gs_in_mode():
    gs = make_game_state()
    gs._challenge_manager.configure(
        artist_challenge_enabled=False,
        movie_quiz_enabled=False,
        title_artist_mode=True,
    )
    gs._challenge_manager.init_round({"title": "Bohemian Rhapsody", "artist": "Queen"})
    return gs


class TestRevealVoteFields:
    def test_near_misses_and_voting_open_present(self):
        gs = _gs_in_mode()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian", "Queen", 1.0
        )
        gs._title_artist_voting_open = True
        d = gs.get_title_artist_challenge_dict(include_answer=True)
        assert d["voting_open"] is True
        assert d["near_misses"][0]["id"] == "Alice:title"
        assert d["near_misses"][0]["field"] == "title"
        assert d["correct_title"] == "Bohemian Rhapsody"
        assert d["correct_artist"] == "Queen"

    def test_no_near_misses_empty_list_and_closed(self):
        gs = _gs_in_mode()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian Rhapsody", "Queen", 1.0
        )
        d = gs.get_title_artist_challenge_dict(include_answer=True)
        assert d["near_misses"] == []
        assert d["voting_open"] is False

    def test_playing_dict_has_no_truth_or_votes(self):
        gs = _gs_in_mode()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian", "Queen", 1.0
        )
        d = gs.get_title_artist_challenge_dict(include_answer=False)
        # PLAYING: never leaks truth, results, or near_misses.
        assert d is None or (
            "correct_title" not in d and "near_misses" not in d and "results" not in d
        )

    def test_top_level_state_has_voting_open_in_reveal(self):
        gs = _gs_in_mode()
        gs.game_id = "g1"
        from custom_components.beatify.game.state import GamePhase

        gs.phase = GamePhase.REVEAL
        gs.current_song = {
            "title": "Bohemian Rhapsody",
            "artist": "Queen",
            "year": 1975,
        }
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian", "Queen", 1.0
        )
        gs._title_artist_voting_open = True
        state = GameStateSerializer.serialize(gs)
        ta = state.get("title_artist_challenge")
        assert ta is not None
        assert ta["voting_open"] is True
        assert ta["near_misses"][0]["id"] == "Alice:title"


class TestRevealOutcomeFields:
    """near_miss_outcomes appears in the REVEAL dict once the vote resolves (#1243)."""

    def test_outcomes_empty_while_voting_open(self):
        gs = _gs_in_mode()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian", "Queen", 1.0
        )
        gs._title_artist_voting_open = True
        d = gs.get_title_artist_challenge_dict(include_answer=True)
        # Live tally drives the UI while open; outcomes fill in after resolution.
        assert d["near_miss_outcomes"] == []

    def test_outcomes_present_after_resolution(self):
        gs = _gs_in_mode()
        # Both fields wrong enough to be near-misses (artist "Queen Rock" != "Queen").
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Bohemian", "Queen Rock", 1.0
        )
        gs._challenge_manager.register_title_artist_vote("Bob", "Alice:title", accept=True)
        gs._challenge_manager.resolve_title_artist()
        gs._title_artist_voting_open = False

        d = gs.get_title_artist_challenge_dict(include_answer=True)
        outcomes = {o["id"]: o for o in d["near_miss_outcomes"]}
        assert outcomes["Alice:title"]["accepted"] is True
        assert outcomes["Alice:title"]["points"] == 5
        assert outcomes["Alice:title"]["votes_yes"] == 1
        # Artist had no votes -> rejected verdict, zero points.
        assert outcomes["Alice:artist"]["accepted"] is False
        assert outcomes["Alice:artist"]["points"] == 0


class TestVoteSecondsRemaining:
    """Server publishes an authoritative countdown, not a client-clock guess (#1180)."""

    def test_remaining_zero_when_not_voting(self):
        gs = _gs_in_mode()
        gs._challenge_manager.submit_title_artist_guess("Alice", "Bohemian", "Queen", 1.0)
        # Voting not opened -> 0.
        assert gs.title_artist_vote_seconds_remaining() == 0
        d = gs.get_title_artist_challenge_dict(include_answer=True)
        assert d["vote_seconds_remaining"] == 0

    def test_remaining_counts_down_from_deadline(self):
        # Inject a controllable clock so we can advance it deterministically.
        clock = {"t": 1000.0}
        gs = make_game_state(time_fn=lambda: clock["t"])
        gs._challenge_manager.configure(
            artist_challenge_enabled=False,
            movie_quiz_enabled=False,
            title_artist_mode=True,
        )
        gs._challenge_manager.init_round({"title": "Bohemian Rhapsody", "artist": "Queen"})
        gs._title_artist_voting_open = True
        gs._title_artist_vote_deadline = clock["t"] + 30  # 30s window

        assert gs.title_artist_vote_seconds_remaining() == 30
        clock["t"] += 12
        assert gs.title_artist_vote_seconds_remaining() == 18
        d = gs.get_title_artist_challenge_dict(include_answer=True)
        assert d["vote_seconds_remaining"] == 18
        # Never goes negative past the deadline.
        clock["t"] += 100
        assert gs.title_artist_vote_seconds_remaining() == 0
