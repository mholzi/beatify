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
