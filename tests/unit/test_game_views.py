"""Tests for the HTTP API views in custom_components.beatify.server.game_views.

Targeted at the provider-validation regression in #808: Apple Music wizard
selections were silently coerced to Spotify, breaking Apple-Music-only setups.
"""

from __future__ import annotations

import pytest

from custom_components.beatify.const import (
    PROVIDER_APPLE_MUSIC,
    PROVIDER_DEEZER,
    PROVIDER_DEFAULT,
    PROVIDER_SPOTIFY,
    PROVIDER_TIDAL,
    PROVIDER_YOUTUBE_MUSIC,
)
from custom_components.beatify.server.game_views import _validate_provider


class TestValidateProvider:
    """#808: every supported provider must round-trip through _validate_provider."""

    @pytest.mark.parametrize(
        "provider",
        [
            PROVIDER_SPOTIFY,
            PROVIDER_APPLE_MUSIC,
            PROVIDER_YOUTUBE_MUSIC,
            PROVIDER_TIDAL,
            PROVIDER_DEEZER,
        ],
    )
    def test_valid_provider_round_trips(self, provider: str) -> None:
        """Each supported provider must come out the same as it went in."""
        assert _validate_provider(provider) == provider

    def test_apple_music_not_coerced_to_spotify(self) -> None:
        """#808 regression: apple_music must NOT silently become spotify.

        This was the originating bug — apple_music wasn't in the valid-
        providers tuple, so the validator fell through to PROVIDER_DEFAULT
        (= spotify). Apple-Music-only setups then got Spotify URIs in the
        cascade and every round failed.
        """
        assert _validate_provider("apple_music") == PROVIDER_APPLE_MUSIC
        assert _validate_provider("apple_music") != PROVIDER_DEFAULT

    @pytest.mark.parametrize(
        "junk",
        [
            "",
            "  ",
            "qobuz",
            "soundcloud",
            "SPOTIFY",  # case-sensitive
            "apple-music",  # wrong separator
            None,
        ],
    )
    def test_invalid_provider_falls_back_to_default(self, junk) -> None:
        """Unknown / malformed providers must coerce to PROVIDER_DEFAULT."""
        assert _validate_provider(junk) == PROVIDER_DEFAULT
