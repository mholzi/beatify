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


class TestNearMisses:
    """get_near_misses / has_near_misses surface near-miss fields."""

    def test_no_near_misses_empty(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Alice", "Bohemian Rhapsody", "Queen", ts=1.0)
        assert mgr.get_near_misses() == []
        assert mgr.has_near_misses() is False

    def test_near_miss_shape_and_counts(self):
        mgr = _make_manager()
        # Both title and artist classify as near_miss.
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # Cast votes only on the title near-miss.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.register_title_artist_vote("V3", "Dan:title", accept=True)

        near = {nm["id"]: nm for nm in mgr.get_near_misses()}
        assert set(near) == {"Dan:title", "Dan:artist"}
        assert mgr.has_near_misses() is True

        title_nm = near["Dan:title"]
        assert title_nm == {
            "id": "Dan:title",
            "player": "Dan",
            "field": "title",
            "guess": "Some Other Song",
            "votes_yes": 2,
            "votes_no": 1,
        }
        artist_nm = near["Dan:artist"]
        assert artist_nm["votes_yes"] == 0
        assert artist_nm["votes_no"] == 0

    def test_near_misses_empty_without_challenge(self):
        mgr = ChallengeManager()
        mgr.configure(title_artist_mode=False)
        mgr.init_round({"title": "X", "artist": "Y"})
        assert mgr.get_near_misses() == []
        assert mgr.has_near_misses() is False


class TestResolveTitleArtist:
    """resolve_title_artist applies override/vote policy to near-misses."""

    def test_accept_by_vote_majority(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # 2 yes / 1 no -> 2/3 >= 0.5 -> accepted (partial points).
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V3", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        # artist had no votes/override -> rejected, stays near_miss
        assert stored["artist_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (5, 0)
        assert mgr.title_artist_challenge.resolved is True

    def test_reject_by_default_no_votes(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss"
        assert stored["artist_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_one_one_tie_is_accepted(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # 1 yes / 1 no -> 1/2 == 0.5 >= 0.5 -> accepted by majority policy.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        assert mgr.title_artist_points("Dan") == (5, 0)

    def test_reject_by_vote_minority(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # 1 yes / 2 no -> 1/3 < 0.5 -> rejected.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.register_title_artist_vote("V3", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_override_accepts_against_no_majority(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # Votes would reject (0 yes / 2 no) but host override accepts.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=False)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.set_title_artist_override("Dan:title", accept=True)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        assert mgr.title_artist_points("Dan") == (5, 0)

    def test_override_rejects_against_yes_majority(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # Votes would accept (2 yes / 0 no) but host override rejects.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=True)
        mgr.set_title_artist_override("Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_accepted_near_miss_awards_partial_both_fields(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        # Override both near-miss fields to accepted -> partial (5, 3).
        mgr.set_title_artist_override("Dan:title", accept=True)
        mgr.set_title_artist_override("Dan:artist", accept=True)
        mgr.resolve_title_artist()

        assert mgr.title_artist_points("Dan") == (5, 3)

    def test_resolve_is_idempotent(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.resolve_title_artist()
        assert mgr.title_artist_challenge.resolved is True
        assert mgr.title_artist_points("Dan") == (5, 0)

        # A late "yes" vote on the artist field after resolve must not change
        # the already-finalized result.
        mgr.register_title_artist_vote("V2", "Dan:artist", accept=True)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        assert stored["artist_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (5, 0)

    def test_late_opposing_vote_does_not_flip_accepted_field(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Some Other Song", "Beatles", ts=1.0)
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.resolve_title_artist()
        assert mgr.title_artist_challenge.guesses["Dan"]["title_status"] == (
            "near_miss_accepted"
        )

        # A late "no" vote on the already-accepted title field after resolve
        # must not flip the finalized result.
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        assert mgr.title_artist_points("Dan") == (5, 0)

    def test_resolve_noop_without_challenge(self):
        mgr = ChallengeManager()
        mgr.configure(title_artist_mode=False)
        mgr.init_round({"title": "X", "artist": "Y"})
        # Should not raise.
        mgr.resolve_title_artist()
        mgr.register_title_artist_vote("V1", "X:title", accept=True)
        mgr.set_title_artist_override("X:title", accept=True)
