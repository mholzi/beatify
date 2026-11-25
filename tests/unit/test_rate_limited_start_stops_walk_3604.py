"""#3604 - a rate-limited start does not burn another budget per candidate.

Under Spotify rate limiting the nightly live test saw songs fail only after
25 s. ``play`` walks every URI candidate of the provider and then the name
fallback, each under its own budget and each through the same limiter. Once a
timeout is classified ``rate_limited`` the walk stops, so the game skips to the
next song instead of waiting out a second and third budget.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService


def _strategy(provider: str):
    svc = MediaPlayerService(
        MagicMock(),
        "media_player.sonos",
        platform="music_assistant",
        provider=provider,
    )
    return svc._strategy


def _two_candidate_song() -> dict:
    return {
        "title": "The Rose",
        "artist": "Bette Midler",
        "year": 1980,
        "uri": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa",
        "_resolved_uri": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa",
        "uri_spotify": "spotify:track:bbbbbbbbbbbbbbbbbbbbbb",
    }


@pytest.mark.asyncio
async def test_rate_limited_timeout_stops_the_candidate_walk():
    strategy = _strategy("spotify")
    song = _two_candidate_song()
    assert len(strategy.uri_candidates(song)) + 1 >= 2  # name fallback or 2nd URI

    async def _timeout(*_args, **_kwargs):
        strategy.last_failure_reason = "rate_limited"
        return False

    strategy.try_play = AsyncMock(side_effect=_timeout)

    assert await strategy.play(song) is False
    assert strategy.last_failure_reason == "rate_limited"
    assert strategy.try_play.await_count == 1


@pytest.mark.asyncio
async def test_other_failures_still_walk_every_candidate():
    """Off path: an ordinary failed start keeps trying the next URI."""
    strategy = _strategy("spotify")
    song = _two_candidate_song()
    n_candidates = len(strategy.uri_candidates(song))

    async def _fail(*_args, **_kwargs):
        strategy.last_failure_reason = "error"
        return False

    strategy.try_play = AsyncMock(side_effect=_fail)

    assert await strategy.play(song) is False
    assert strategy.try_play.await_count >= n_candidates
    assert strategy.try_play.await_count >= 2
