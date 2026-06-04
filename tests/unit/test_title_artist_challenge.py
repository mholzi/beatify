"""Tests for Title & Artist guessing mode (PlayerSession flag)."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.game.player import PlayerSession


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
