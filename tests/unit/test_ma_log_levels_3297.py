"""#3297: Music Assistant log lines must name the right provider and level.

Found in the v4.8.7-rc2 live test (Spotify, rate-limited): the slow-start
warning said "Apple Music rate limiter", and a cleanly skipped song was logged
at ERROR, which the live-test checklist reads as a regression.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.beatify.services.playback.music_assistant import (
    _provider_label,
)
from tests.unit.test_playback_budget_2682 import (
    _make_state,
    _make_song,
    _play_and_time_out,
    _service,
)


@pytest.mark.parametrize(
    ("uri", "label"),
    [
        ("spotify:track:abc", "Spotify"),
        ("apple_music://track/1", "Apple Music"),
        ("tidal://track/1", "Tidal"),
        ("", "provider's"),
        ("mystery://x", "provider's"),
    ],
)
def test_provider_label_comes_from_the_uri_scheme(uri, label):
    assert _provider_label(uri) == label


@pytest.mark.asyncio
async def test_slow_start_warning_names_spotify_not_apple_music(caplog):
    svc = _service([_make_state("idle"), _make_state("idle")])
    with caplog.at_level(logging.WARNING):
        svc._strategy._note_start_duration(
            11.2, "spotify:track:abc", 25.0, first_play=False
        )
    assert "its Spotify rate limiter" in caplog.text
    assert "Apple Music" not in caplog.text


@pytest.mark.asyncio
async def test_exhausted_candidates_are_a_warning_not_an_error(caplog):
    svc = _service([_make_state("idle"), _make_state("idle")])
    with caplog.at_level(logging.WARNING):
        assert await _play_and_time_out(svc) is False
    lines = [r for r in caplog.records if "URI candidate(s) failed" in r.getMessage()]
    assert lines
    assert all(r.levelno == logging.WARNING for r in lines)
    assert _make_song()["title"] in lines[0].getMessage()
