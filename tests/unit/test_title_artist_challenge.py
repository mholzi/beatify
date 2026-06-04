"""Tests for Title & Artist guessing mode (challenge model + scoring)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.game.challenges import (
    ChallengeManager,
    TitleArtistChallenge,
)
from custom_components.beatify.game.player import PlayerSession


def _make_manager(*, title_artist_mode: bool = True) -> ChallengeManager:
    """Build a ChallengeManager configured for title/artist mode with a round."""
    mgr = ChallengeManager()
    mgr.configure(
        artist_challenge_enabled=False,
        movie_quiz_enabled=False,
        title_artist_mode=title_artist_mode,
    )
    mgr.init_round({"title": "Bohemian Rhapsody", "artist": "Queen"})
    return mgr


class TestPlayerSessionTitleArtistFlag:
    """has_title_artist_guess defaults False and resets each round."""

    def test_defaults_false(self):
        p = PlayerSession(name="Alice", ws=MagicMock())
        assert p.has_title_artist_guess is False

    def test_reset_round_clears_flag(self):
        p = PlayerSession(name="Alice", ws=MagicMock())
        p.has_title_artist_guess = True
        p.reset_round()
        assert p.has_title_artist_guess is False


class TestTitleArtistChallengeModel:
    """init_round builds the challenge with empty vote/override state."""

    def test_init_round_creates_challenge(self):
        mgr = _make_manager()
        ch = mgr.title_artist_challenge
        assert isinstance(ch, TitleArtistChallenge)
        assert ch.correct_title == "Bohemian Rhapsody"
        assert ch.correct_artist == "Queen"
        assert ch.guesses == {}
        assert ch.votes == {}
        assert ch.overrides == {}
        assert ch.resolved is False

    def test_init_round_noop_when_mode_off(self):
        mgr = ChallengeManager()
        mgr.configure(
            artist_challenge_enabled=False,
            movie_quiz_enabled=False,
            title_artist_mode=False,
        )
        mgr.init_round({"title": "Bohemian Rhapsody", "artist": "Queen"})
        assert mgr.title_artist_challenge is None

    def test_configure_resets_challenge(self):
        mgr = _make_manager()
        assert mgr.title_artist_challenge is not None
        mgr.configure(title_artist_mode=True)
        assert mgr.title_artist_mode is True
        assert mgr.title_artist_challenge is None


class TestSubmitTitleArtistGuess:
    """submit_title_artist_guess classifies and stores per field."""

    def test_exact_both(self):
        mgr = _make_manager()
        res = mgr.submit_title_artist_guess(
            "Alice", "Bohemian Rhapsody", "Queen", ts=12.0
        )
        assert res == {"title_status": "exact", "artist_status": "exact"}
        stored = mgr.title_artist_challenge.guesses["Alice"]
        assert stored["title"] == "Bohemian Rhapsody"
        assert stored["artist"] == "Queen"
        assert stored["title_status"] == "exact"
        assert stored["artist_status"] == "exact"
        assert stored["ts"] == 12.0

    def test_fuzzy_title_exact_artist(self):
        mgr = _make_manager()
        # one-edit typo on a long title -> fuzzy (FUZZY_MIN_LEN guard satisfied)
        res = mgr.submit_title_artist_guess("Bob", "Bohemian Rhapsdy", "Queen", ts=1.0)
        assert res["title_status"] == "fuzzy"
        assert res["artist_status"] == "exact"

    def test_skipped_empty_field(self):
        mgr = _make_manager()
        res = mgr.submit_title_artist_guess("Carol", "", "  ", ts=1.0)
        assert res == {"title_status": "skipped", "artist_status": "skipped"}

    def test_near_miss_both(self):
        mgr = _make_manager()
        res = mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        assert res["title_status"] == "near_miss"
        assert res["artist_status"] == "near_miss"

    def test_resubmit_overwrites(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Eve", "Wrong", "Wrong", ts=1.0)
        mgr.submit_title_artist_guess("Eve", "Bohemian Rhapsody", "Queen", ts=2.0)
        stored = mgr.title_artist_challenge.guesses["Eve"]
        assert stored["title_status"] == "exact"
        assert stored["ts"] == 2.0

    def test_submit_without_challenge_raises(self):
        mgr = ChallengeManager()
        mgr.configure(title_artist_mode=False)
        mgr.init_round({"title": "X", "artist": "Y"})
        with pytest.raises(ValueError):
            mgr.submit_title_artist_guess("Alice", "X", "Y", ts=1.0)


class TestTitleArtistPoints:
    """title_artist_points maps stored status -> (title_pts, artist_pts)."""

    def test_exact_full_points(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Alice", "Bohemian Rhapsody", "Queen", ts=1.0)
        assert mgr.title_artist_points("Alice") == (10, 5)

    def test_fuzzy_full_points(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Bob", "Bohemian Rhapsdy", "Quen", ts=1.0)
        # both fuzzy (long strings, one edit each) -> full points
        assert mgr.title_artist_points("Bob") == (10, 5)

    def test_near_miss_zero_until_resolved(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_skipped_zero(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Carol", "", "", ts=1.0)
        assert mgr.title_artist_points("Carol") == (0, 0)

    def test_unknown_player_zero(self):
        mgr = _make_manager()
        assert mgr.title_artist_points("Nobody") == (0, 0)
