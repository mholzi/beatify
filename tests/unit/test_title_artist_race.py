"""Tests for the Title & Artist RACE mode (live buzzer, first-correct-wins).

Covers the challenge model + ChallengeManager logic, the race-aware scoring
path, and the broadcast serialization (answer hidden until REVEAL).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import (
    ARTIST_RACE_POINTS,
    RACE_FEED_MAX,
    TITLE_RACE_POINTS,
)
from custom_components.beatify.game.challenges import ChallengeManager
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.scoring import ScoringService


def _race_manager(song: dict | None = None) -> ChallengeManager:
    """Build a ChallengeManager configured for race mode with one round."""
    mgr = ChallengeManager()
    mgr.configure(
        artist_challenge_enabled=True,  # should be forced off by race mode
        movie_quiz_enabled=False,
        title_artist_race_mode=True,
    )
    mgr.init_round(song or {"title": "Bohemian Rhapsody", "artist": "Queen"})
    return mgr


class TestRaceConfiguration:
    """Race mode implies title/artist mode and disables the artist MC challenge."""

    def test_race_implies_title_artist_mode(self):
        mgr = _race_manager()
        assert mgr.title_artist_race_mode is True
        assert mgr.title_artist_mode is True

    def test_race_disables_artist_multiple_choice(self):
        mgr = _race_manager()
        # The artist MC challenge would leak the correct artist — must stay off.
        assert mgr.artist_challenge_enabled is False

    def test_init_round_flags_challenge_race_mode(self):
        mgr = _race_manager()
        assert mgr.title_artist_challenge.race_mode is True

    def test_reset_clears_race_mode(self):
        mgr = _race_manager()
        mgr.reset()
        assert mgr.title_artist_race_mode is False
        assert mgr.title_artist_mode is False


class TestRaceGuessing:
    """submit_race_guess classifies, races per field, and feeds the live view."""

    def test_correct_title_wins_and_feeds(self):
        mgr = _race_manager()
        res = mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        assert res["title_status"] == "exact"
        assert res["won_title"] is True
        assert res["artist_status"] == "skipped"
        assert mgr.title_artist_challenge.title_winner == "Alice"
        assert mgr.title_artist_challenge.title_winner_ts == 1.0
        # Feed carries the attempt with its correctness flag.
        assert mgr.title_artist_challenge.feed == [
            {
                "player": "Alice",
                "field": "title",
                "guess": "Bohemian Rhapsody",
                "correct": True,
                "ts": 1.0,
            }
        ]

    def test_wrong_guess_does_not_win_but_still_feeds(self):
        mgr = _race_manager()
        res = mgr.submit_race_guess("Bob", "Some Other Song", "", 2.0)
        assert res["won_title"] is False
        assert mgr.title_artist_challenge.title_winner is None
        assert len(mgr.title_artist_challenge.feed) == 1
        assert mgr.title_artist_challenge.feed[0]["correct"] is False

    def test_fuzzy_match_counts_as_correct(self):
        mgr = _race_manager()
        # One-letter typo — classifies as fuzzy, which wins the race.
        res = mgr.submit_race_guess("Alice", "Bohemian Rhapsdy", "", 1.0)
        assert res["title_status"] == "fuzzy"
        assert res["won_title"] is True

    def test_first_correct_wins_second_does_not_steal(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        res = mgr.submit_race_guess("Bob", "Bohemian Rhapsody", "", 2.0)
        assert res["won_title"] is False
        assert mgr.title_artist_challenge.title_winner == "Alice"

    def test_title_and_artist_won_by_different_players(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        mgr.submit_race_guess("Bob", "", "Queen", 2.0)
        assert mgr.title_artist_challenge.title_winner == "Alice"
        assert mgr.title_artist_challenge.artist_winner == "Bob"

    def test_unlimited_attempts_same_player(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "wrong one", "", 1.0)
        mgr.submit_race_guess("Alice", "still wrong", "", 2.0)
        res = mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 3.0)
        assert res["won_title"] is True
        assert len(mgr.title_artist_challenge.feed) == 3

    def test_empty_guess_both_fields_is_all_skipped(self):
        mgr = _race_manager()
        res = mgr.submit_race_guess("Alice", "  ", "", 1.0)
        assert res["title_status"] == "skipped"
        assert res["artist_status"] == "skipped"
        assert mgr.title_artist_challenge.feed == []

    def test_feed_is_capped(self):
        mgr = _race_manager()
        for i in range(RACE_FEED_MAX + 10):
            mgr.submit_race_guess("Alice", f"guess {i}", "", float(i))
        assert len(mgr.title_artist_challenge.feed) == RACE_FEED_MAX
        # Oldest dropped: the last entry is the most recent guess.
        assert mgr.title_artist_challenge.feed[-1]["guess"] == (
            f"guess {RACE_FEED_MAX + 9}"
        )


class TestRaceComplete:
    """The round ends once both fields are settled."""

    def test_not_complete_until_both_solved(self):
        mgr = _race_manager()
        assert mgr.race_complete() is False
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        assert mgr.race_complete() is False
        mgr.submit_race_guess("Alice", "", "Queen", 2.0)
        assert mgr.race_complete() is True

    def test_empty_truth_field_counts_as_done(self):
        # A song with no artist truth can never be "won"; the round must still
        # be completable on the title alone.
        mgr = _race_manager({"title": "Instrumental", "artist": ""})
        assert mgr.race_complete() is False
        mgr.submit_race_guess("Alice", "Instrumental", "", 1.0)
        assert mgr.race_complete() is True


class TestRacePointsAndStatus:
    """Only the field winners bank points; both fields are worth the same."""

    def test_winner_banks_points_loser_gets_zero(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "Queen", 1.0)
        mgr.submit_race_guess("Bob", "Bohemian Rhapsody", "Queen", 2.0)
        assert mgr.title_artist_points("Alice") == (
            TITLE_RACE_POINTS,
            ARTIST_RACE_POINTS,
        )
        assert mgr.title_artist_points("Bob") == (0, 0)

    def test_split_win_each_gets_one_field(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        mgr.submit_race_guess("Bob", "", "Queen", 2.0)
        assert mgr.title_artist_points("Alice") == (TITLE_RACE_POINTS, 0)
        assert mgr.title_artist_points("Bob") == (0, ARTIST_RACE_POINTS)

    def test_status_exact_for_won_field_else_skipped(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        assert mgr.title_artist_status("Alice", "title") == "exact"
        assert mgr.title_artist_status("Alice", "artist") == "skipped"
        assert mgr.title_artist_status("Bob", "title") == "skipped"


class TestRaceScoringIntegration:
    """A race winner is scored even though it is never marked ``submitted``."""

    def _player(self, name):
        p = PlayerSession(name=name, ws=MagicMock())
        p.submitted = False  # race players never lock in
        return p

    def _score(self, player, mgr):
        ScoringService.score_player_round(
            player,
            correct_year=1975,
            round_start_time=0.0,
            round_duration=30.0,
            difficulty="normal",
            artist_challenge=None,
            movie_challenge=None,
            is_intro_round=False,
            intro_round_start_time=None,
            all_players=[player],
            streak_achievements={},
            bet_tracking={"total_bets": 0, "bets_won": 0},
            title_artist_manager=mgr,
        )

    def test_winner_scored_without_submitted_flag(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "Queen", 1.0)
        alice = self._player("Alice")
        self._score(alice, mgr)
        assert alice.round_score == TITLE_RACE_POINTS + ARTIST_RACE_POINTS
        assert alice.score == TITLE_RACE_POINTS + ARTIST_RACE_POINTS
        assert alice.missed_round is False
        assert alice.streak == 1  # won the title -> streak counts

    def test_non_winner_scores_zero(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "Queen", 1.0)
        bob = self._player("Bob")
        self._score(bob, mgr)
        assert bob.round_score == 0
        assert bob.streak == 0


class TestRaceSerialization:
    """The broadcast dict hides the answer during PLAYING, shows it at REVEAL."""

    def test_playing_hides_answer_but_shows_live_feed(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        d = mgr.get_title_artist_challenge_dict(include_answer=False)
        assert d["active"] is True
        assert "correct_title" not in d.get("race", {})
        assert d["race"]["title_winner"] == "Alice"
        assert d["race"]["title_solved"] is True
        assert d["race"]["artist_solved"] is False
        assert len(d["race"]["feed"]) == 1
        assert d["race"]["points"] == {
            "title": TITLE_RACE_POINTS,
            "artist": ARTIST_RACE_POINTS,
        }

    def test_reveal_includes_answer(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "Queen", 1.0)
        d = mgr.get_title_artist_challenge_dict(include_answer=True)
        assert d["race"]["correct_title"] == "Bohemian Rhapsody"
        assert d["race"]["correct_artist"] == "Queen"
        assert d["voting_open"] is False
        assert d["near_misses"] == []


class TestRaceFeedDoesNotLeakTheAnswer:
    """#3557: a correct guess is the answer — its text waits for REVEAL."""

    def test_playing_feed_withholds_correct_guess_text(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rapsody", "", 1.0)  # fuzzy hit
        mgr.submit_race_guess("Bob", "", "Freddie", 2.0)  # wrong
        feed = mgr.get_title_artist_challenge_dict(include_answer=False)["race"]["feed"]
        assert feed[0]["correct"] is True
        assert feed[0]["guess"] is None
        assert feed[0]["player"] == "Alice"
        assert feed[1]["guess"] == "Freddie"

    def test_redaction_does_not_touch_the_stored_feed(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        mgr.get_title_artist_challenge_dict(include_answer=False)
        assert mgr.title_artist_challenge.feed[0]["guess"] == "Bohemian Rhapsody"

    def test_reveal_feed_shows_correct_guess_text(self):
        mgr = _race_manager()
        mgr.submit_race_guess("Alice", "Bohemian Rhapsody", "", 1.0)
        feed = mgr.get_title_artist_challenge_dict(include_answer=True)["race"]["feed"]
        assert feed[0]["guess"] == "Bohemian Rhapsody"


class TestRaceAttemptThrottle:
    """One race attempt per RACE_GUESS_MIN_INTERVAL per player."""

    def test_second_attempt_inside_interval_is_refused(self):
        mgr = _race_manager()
        ch = mgr.title_artist_challenge
        assert ch.race_attempt_allowed("Alice", 10.0, 0.4) is True
        assert ch.race_attempt_allowed("Alice", 10.1, 0.4) is False
        # A refused attempt does not push the window out.
        assert ch.race_attempt_allowed("Alice", 10.4, 0.4) is True

    def test_players_are_throttled_independently(self):
        mgr = _race_manager()
        ch = mgr.title_artist_challenge
        assert ch.race_attempt_allowed("Alice", 10.0, 0.4) is True
        assert ch.race_attempt_allowed("Bob", 10.0, 0.4) is True

    def test_new_round_starts_a_fresh_throttle(self):
        mgr = _race_manager()
        mgr.title_artist_challenge.race_attempt_allowed("Alice", 10.0, 0.4)
        mgr.init_round({"title": "Yesterday", "artist": "The Beatles"})
        assert mgr.title_artist_challenge.race_attempt_allowed("Alice", 10.1, 0.4)


class TestRaceGameOptions:
    """The race flag travels through GameOptions like every other option."""

    def test_rematch_capture_keeps_race_mode(self):
        from custom_components.beatify.game.config import GameOptions
        from tests.conftest import make_game_state, make_songs

        gs = make_game_state()
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            title_artist_race_mode=True,
        )
        opts = GameOptions.capture(gs)
        assert opts.title_artist_race_mode is True
        assert opts.title_artist_mode is True

    def test_race_mode_is_player_visible(self):
        from custom_components.beatify.server.serializers import PLAYER_VISIBLE_KEYS

        assert "title_artist_race_mode" in PLAYER_VISIBLE_KEYS
