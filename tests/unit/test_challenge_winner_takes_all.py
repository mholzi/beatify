"""Winner-takes-all side challenges (Issue #1723).

Both side challenges (artist quiz + movie quiz) award CHALLENGE_BONUS_POINTS to
the single fastest correct guesser and 0 to everyone else. The movie quiz used
to pay tiered [5, 3, 1] by speed rank; this suite pins the new unified behavior:
fastest correct wins +5, later-correct and incorrect players get 0.
"""

from __future__ import annotations

from custom_components.beatify.const import CHALLENGE_BONUS_POINTS
from custom_components.beatify.game.challenges import (
    ArtistChallenge,
    ChallengeManager,
    MovieChallenge,
)

SONG = {
    "movie": "Titanic",
    "movie_choices": ["Titanic", "Grease", "Cats"],
    "artist": "Celine Dion",
    "alt_artists": ["Whitney Houston", "Mariah Carey"],
}


def _manager() -> ChallengeManager:
    mgr = ChallengeManager()
    mgr.configure(
        artist_challenge_enabled=True,
        movie_quiz_enabled=True,
        title_artist_mode=False,
    )
    mgr.init_round(SONG)
    return mgr


# ---------------------------------------------------------------------------
# MovieChallenge — winner-takes-all
# ---------------------------------------------------------------------------


class TestMovieWinnerTakesAll:
    def test_fastest_correct_gets_bonus_later_correct_gets_zero(self) -> None:
        mgr = _manager()
        # Alice guesses at elapsed 2s, Bob correct later at 5s.
        alice = mgr.submit_movie_guess("Alice", "Titanic", 102.0, 100.0)
        bob = mgr.submit_movie_guess("Bob", "Titanic", 105.0, 100.0)

        assert alice["correct"] is True
        assert alice["rank"] == 1
        assert alice["bonus"] == CHALLENGE_BONUS_POINTS
        # Second-fastest correct earns nothing — no more tiered [5, 3, 1].
        assert bob["correct"] is True
        assert bob["rank"] == 2
        assert bob["bonus"] == 0

    def test_get_player_bonus_only_fastest(self) -> None:
        mgr = _manager()
        mgr.submit_movie_guess("Alice", "Titanic", 102.0, 100.0)
        mgr.submit_movie_guess("Bob", "Titanic", 103.0, 100.0)
        mgr.submit_movie_guess("Carol", "Titanic", 104.0, 100.0)

        mc = mgr.movie_challenge
        assert mc is not None
        assert mc.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
        assert mc.get_player_bonus("Bob") == 0
        assert mc.get_player_bonus("Carol") == 0
        # Unknown / never-guessed player.
        assert mc.get_player_bonus("Nobody") == 0

    def test_incorrect_guess_gets_zero(self) -> None:
        mgr = _manager()
        result = mgr.submit_movie_guess("Alice", "Grease", 101.0, 100.0)
        assert result["correct"] is False
        assert result["bonus"] == 0
        mc = mgr.movie_challenge
        assert mc is not None
        assert mc.get_player_bonus("Alice") == 0

    def test_out_of_order_submission_ranks_by_elapsed_final_scoring(self) -> None:
        # Bob submits first in wall-clock but with a larger elapsed time than
        # Alice, who submits later but was faster off the round start. Bob's
        # in-round ack bonus is optimistic (he was momentarily fastest), but the
        # authoritative reveal-time get_player_bonus ranks strictly by elapsed
        # and pays only Alice.
        mgr = _manager()
        mgr.submit_movie_guess("Bob", "Titanic", 100.0, 90.0)  # elapsed 10s
        alice = mgr.submit_movie_guess("Alice", "Titanic", 101.0, 100.0)  # elapsed 1s

        assert alice["rank"] == 1
        assert alice["bonus"] == CHALLENGE_BONUS_POINTS
        mc = mgr.movie_challenge
        assert mc is not None
        assert mc.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
        assert mc.get_player_bonus("Bob") == 0

    def test_tie_in_elapsed_time_is_deterministic(self) -> None:
        # Equal elapsed time -> the earlier submitter (inserted first) wins,
        # thanks to the stable sort. Deterministic, no coin flip.
        mgr = _manager()
        first = mgr.submit_movie_guess("Alice", "Titanic", 102.0, 100.0)
        second = mgr.submit_movie_guess("Bob", "Titanic", 102.0, 100.0)

        assert first["bonus"] == CHALLENGE_BONUS_POINTS
        assert second["bonus"] == 0
        mc = mgr.movie_challenge
        assert mc is not None
        assert mc.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
        assert mc.get_player_bonus("Bob") == 0

    def test_reveal_results_show_single_winner(self) -> None:
        mgr = _manager()
        mgr.submit_movie_guess("Alice", "Titanic", 102.0, 100.0)
        mgr.submit_movie_guess("Bob", "Titanic", 105.0, 100.0)
        mgr.submit_movie_guess("Carol", "Grease", 103.0, 100.0)  # wrong

        mc = mgr.movie_challenge
        assert mc is not None
        results = mc.to_dict(include_answer=True)["results"]
        winners = results["winners"]
        # Only the fastest correct guesser is surfaced (no 2nd/3rd tiers).
        assert len(winners) == 1
        assert winners[0]["name"] == "Alice"
        assert winners[0]["bonus"] == CHALLENGE_BONUS_POINTS
        # Wrong guesser still listed separately.
        assert [g["name"] for g in results["wrong_guesses"]] == ["Carol"]

    def test_zero_correct_guessers_no_winner(self) -> None:
        mgr = _manager()
        mgr.submit_movie_guess("Alice", "Grease", 101.0, 100.0)  # wrong
        mgr.submit_movie_guess("Bob", "Cats", 102.0, 100.0)  # wrong

        mc = mgr.movie_challenge
        assert mc is not None
        results = mc.to_dict(include_answer=True)["results"]
        assert results["winners"] == []
        assert mc.get_player_bonus("Alice") == 0
        assert mc.get_player_bonus("Bob") == 0


# ---------------------------------------------------------------------------
# ArtistChallenge — already winner-takes-all, now shares get_player_bonus
# ---------------------------------------------------------------------------


class TestArtistWinnerTakesAll:
    def test_first_correct_wins_others_zero(self) -> None:
        mgr = _manager()
        alice = mgr.submit_artist_guess("Alice", "Celine Dion", 101.0)
        bob = mgr.submit_artist_guess("Bob", "Celine Dion", 102.0)

        assert alice["correct"] is True
        assert alice["first"] is True
        assert bob["correct"] is True
        assert bob["first"] is False

        ac = mgr.artist_challenge
        assert ac is not None
        assert ac.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
        assert ac.get_player_bonus("Bob") == 0
        assert ac.get_player_bonus("Nobody") == 0

    def test_no_winner_bonus_is_zero(self) -> None:
        mgr = _manager()
        mgr.submit_artist_guess("Alice", "Wrong Artist", 101.0)
        ac = mgr.artist_challenge
        assert ac is not None
        assert ac.get_player_bonus("Alice") == 0


# ---------------------------------------------------------------------------
# Both challenges expose the identical winner-takes-all contract
# ---------------------------------------------------------------------------


def test_both_challenges_award_same_bonus_to_fastest() -> None:
    artist = ArtistChallenge(
        correct_artist="Queen", options=["Queen", "Abba"], winner="Alice"
    )
    movie = MovieChallenge(
        correct_movie="Grease",
        options=["Grease", "Cats"],
        correct_guesses=[{"name": "Alice", "time": 1.0}, {"name": "Bob", "time": 2.0}],
    )
    # Same fastest winner, same +5, same 0 for the rest — the whole point of #1723.
    assert artist.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
    assert movie.get_player_bonus("Alice") == CHALLENGE_BONUS_POINTS
    assert artist.get_player_bonus("Bob") == 0
    assert movie.get_player_bonus("Bob") == 0
