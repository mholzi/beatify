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


class TestConfigureForcesArtistChallengeOffInTaMode:
    """#1402 B3: TA mode must disable the artist multiple-choice challenge
    server-side, so the broadcast options never leak the correct artist."""

    def test_artist_challenge_forced_off_when_ta_mode_on(self):
        mgr = ChallengeManager()
        # Even if the caller (or stale admin UI) requests artist challenge,
        # TA mode wins and the flag is forced off.
        mgr.configure(
            artist_challenge_enabled=True,
            movie_quiz_enabled=False,
            title_artist_mode=True,
        )
        assert mgr.artist_challenge_enabled is False

    def test_init_round_builds_no_artist_challenge_in_ta_mode(self):
        mgr = ChallengeManager()
        mgr.configure(
            artist_challenge_enabled=True,
            movie_quiz_enabled=False,
            title_artist_mode=True,
        )
        mgr.init_round(
            {
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "alt_artists": ["ABBA", "Blur"],
            }
        )
        # No artist challenge object -> options never reach clients.
        assert mgr.artist_challenge is None
        assert mgr.get_artist_challenge_dict(include_answer=False) is None

    def test_artist_challenge_still_works_without_ta_mode(self):
        mgr = ChallengeManager()
        mgr.configure(
            artist_challenge_enabled=True,
            movie_quiz_enabled=False,
            title_artist_mode=False,
        )
        assert mgr.artist_challenge_enabled is True


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
        res = mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_skipped_zero(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Carol", "", "", ts=1.0)
        assert mgr.title_artist_points("Carol") == (0, 0)

    def test_unknown_player_zero(self):
        mgr = _make_manager()
        assert mgr.title_artist_points("Nobody") == (0, 0)


class TestTitleArtistRoundResult:
    """title_artist_round_result classifies the share-grid cell (#1373).

    exact / scored / close / missed, mirroring _field_points scoring.
    """

    def test_both_exact_is_exact(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Alice", "Bohemian Rhapsody", "Queen", ts=1.0)
        assert mgr.title_artist_round_result("Alice") == "exact"

    def test_title_exact_artist_wrong_is_scored(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess(
            "Alice", "Bohemian Rhapsody", "Totally Different", ts=1.0
        )
        assert mgr.title_artist_round_result("Alice") == "scored"

    def test_fuzzy_field_is_scored(self):
        mgr = _make_manager()
        # fuzzy title earns full points -> "scored" (not "exact").
        mgr.submit_title_artist_guess("Bob", "Bohemian Rhapsdy", "Queen", ts=1.0)
        assert mgr.title_artist_round_result("Bob") == "scored"

    def test_accepted_near_miss_only_is_close(self):
        mgr = _make_manager()
        # Near-miss title accepted, artist wrong -> only partial points -> close.
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Totally Different", ts=1.0)
        mgr.set_title_artist_override("Dan:title", accept=True)
        mgr.resolve_title_artist()
        assert mgr.title_artist_round_result("Dan") == "close"

    def test_unaccepted_near_miss_is_missed(self):
        mgr = _make_manager()
        # Near-miss both, no votes/override -> rejected -> 0 points -> missed.
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        mgr.resolve_title_artist()
        assert mgr.title_artist_round_result("Dan") == "missed"

    def test_no_guess_is_missed(self):
        mgr = _make_manager()
        assert mgr.title_artist_round_result("Nobody") == "missed"


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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
            "guess": "Bohemian",
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss"
        assert stored["artist_status"] == "near_miss"
        assert mgr.title_artist_points("Dan") == (0, 0)

    def test_one_one_tie_is_accepted(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        # 1 yes / 1 no -> 1/2 == 0.5 >= 0.5 -> accepted by majority policy.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        stored = mgr.title_artist_challenge.guesses["Dan"]
        assert stored["title_status"] == "near_miss_accepted"
        assert mgr.title_artist_points("Dan") == (5, 0)

    def test_reject_by_vote_minority(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        # Override both near-miss fields to accepted -> partial (5, 3).
        mgr.set_title_artist_override("Dan:title", accept=True)
        mgr.set_title_artist_override("Dan:artist", accept=True)
        mgr.resolve_title_artist()

        assert mgr.title_artist_points("Dan") == (5, 3)

    def test_resolve_is_idempotent(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
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


class TestGameStateTitleArtistMode:
    """GameState exposes title_artist_mode and wires it into create_game."""

    def _songs(self):
        return [
            {
                "title": "Bohemian Rhapsody",
                "artist": "Queen",
                "year": 1975,
                "uri": "spotify:track:1",
                "uri_spotify": "spotify:track:1",
            },
            {
                "title": "Imagine",
                "artist": "John Lennon",
                "year": 1971,
                "uri": "spotify:track:2",
                "uri_spotify": "spotify:track:2",
            },
        ]

    def test_default_off(self):
        from custom_components.beatify.game.state import GameState

        gs = GameState()
        assert gs.title_artist_mode is False

    def test_create_game_enables_mode(self):
        from custom_components.beatify.game.state import GameState

        gs = GameState()
        gs.create_game(
            playlists=["test.json"],
            songs=self._songs(),
            media_player="media_player.test",
            base_url="http://localhost:8123",
            provider="spotify",
            title_artist_mode=True,
        )
        assert gs.title_artist_mode is True
        # init_round wires the challenge through the manager
        gs._challenge_manager.init_round(self._songs()[0])
        assert gs.title_artist_challenge is not None
        assert gs.title_artist_challenge.correct_title == "Bohemian Rhapsody"

    def test_property_setter_writes_through(self):
        from custom_components.beatify.game.state import GameState

        gs = GameState()
        gs.title_artist_mode = True
        assert gs._challenge_manager.title_artist_mode is True

    def test_apply_config_does_not_clobber_mode(self):
        from custom_components.beatify.game.state import GameState

        gs = GameState()
        gs.title_artist_mode = True
        # _apply_config must not reset the manager-owned flag back to False
        gs._apply_config(gs._default_config)
        assert gs.title_artist_mode is True


class TestGetNearMissOutcomes:
    """get_near_miss_outcomes surfaces resolved verdicts for the reveal UI (#1243)."""

    def test_empty_before_resolution(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        # Not resolved yet -> outcomes are empty; the live tally lives in
        # get_near_misses until the window closes.
        assert mgr.get_near_miss_outcomes() == []

    def test_empty_without_challenge(self):
        mgr = ChallengeManager()
        mgr.configure(title_artist_mode=False)
        mgr.init_round({"title": "X", "artist": "Y"})
        assert mgr.get_near_miss_outcomes() == []

    def test_accepted_and_rejected_after_resolution(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        # Title: 2 yes / 1 no -> accepted (partial 5). Artist: no votes -> rejected.
        mgr.register_title_artist_vote("V1", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V2", "Dan:title", accept=True)
        mgr.register_title_artist_vote("V3", "Dan:title", accept=False)
        mgr.resolve_title_artist()

        outcomes = {o["id"]: o for o in mgr.get_near_miss_outcomes()}
        assert set(outcomes) == {"Dan:title", "Dan:artist"}

        assert outcomes["Dan:title"] == {
            "id": "Dan:title",
            "player": "Dan",
            "field": "title",
            "guess": "Bohemian",
            "votes_yes": 2,
            "votes_no": 1,
            "accepted": True,
            "points": 5,
        }
        assert outcomes["Dan:artist"] == {
            "id": "Dan:artist",
            "player": "Dan",
            "field": "artist",
            "guess": "Queen Rock",
            "votes_yes": 0,
            "votes_no": 0,
            "accepted": False,
            "points": 0,
        }

    def test_accepted_artist_awards_partial_three(self):
        mgr = _make_manager()
        mgr.submit_title_artist_guess("Dan", "Bohemian", "Queen Rock", ts=1.0)
        mgr.register_title_artist_vote("V1", "Dan:artist", accept=True)
        mgr.resolve_title_artist()

        outcomes = {o["id"]: o for o in mgr.get_near_miss_outcomes()}
        assert outcomes["Dan:artist"]["accepted"] is True
        assert outcomes["Dan:artist"]["points"] == 3

    def test_exact_fields_excluded(self):
        mgr = _make_manager()
        # Exact title + exact artist -> never a near-miss, never in outcomes.
        mgr.submit_title_artist_guess("Eve", "Bohemian Rhapsody", "Queen", ts=1.0)
        mgr.resolve_title_artist()
        assert mgr.get_near_miss_outcomes() == []
