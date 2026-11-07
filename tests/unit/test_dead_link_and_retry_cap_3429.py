"""#3429 - a dead link is skipped at once, and a stalled start pauses sooner.

Reported with Spotify on a Sonos speaker through Music Assistant: after round 2
the game stayed in REVEAL for ~80 s while Beatify walked through songs that
each burned the 25 s playback budget. Music Assistant answered one of them
"The requested media item could not be found" - 29 s after Beatify had given
up on it - and Beatify had logged the same failure as rate limiting.

Pinned here:

* "media item could not be found" ends the attempt at once as a dead link
  (``unavailable``: skipped, not counted) instead of waiting out the budget;
* an answer that arrives after the attempt is over does not touch the next one;
* two counted failures in a row pause the game (was three).
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.beatify.const import MAX_CONSECUTIVE_PLAYBACK_FAILURES
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.services.media_player import MediaPlayerService
from tests.conftest import make_game_state, make_songs


class MediaNotFoundError(Exception):
    """Stand-in for music_assistant_models.errors.MediaNotFoundError."""


def _not_found() -> HomeAssistantError:
    try:
        raise MediaNotFoundError("The requested media item could not be found.")
    except MediaNotFoundError as err:
        wrapped = HomeAssistantError("The requested media item could not be found.")
        wrapped.__cause__ = err
        return wrapped


def _speaker() -> MagicMock:
    state = MagicMock()
    state.state = "paused"
    state.attributes = {
        "media_title": "Sunny",
        "media_artist": "Boney M.",
        "media_position_updated_at": "2026-11-06T23:00:00+00:00",
        "media_content_id": "spotify--abc://track/3pf96IFggfQuT6Gafqx2rt",
    }
    return state


def _service(answer_after: float):
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_speaker())

    async def _ma_play_media():
        await asyncio.sleep(answer_after)
        raise _not_found()

    async def _call(domain, service, *args, blocking=False, **kwargs):
        if (domain, service) != ("music_assistant", "play_media"):
            return None
        if blocking:
            return await _ma_play_media()
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    svc = MediaPlayerService(
        hass,
        "media_player.sonos",
        platform="music_assistant",
        provider="spotify",
    )
    return svc, hass


_SONG = {
    "title": "Use Somebody",
    "artist": "Kings of Leon",
    "year": 2008,
    "uri": "spotify:track:5VGlqQANWDKJFl0MBG3sg2",
}


@pytest.mark.asyncio
async def test_not_found_ends_the_attempt_at_once_as_a_dead_link(caplog):
    svc, _hass = _service(answer_after=0.05)

    with caplog.at_level(logging.WARNING):
        result = await asyncio.wait_for(svc.play_song(dict(_SONG)), timeout=3)

    assert result is False
    # "unavailable" is skipped without counting, and is not "rate_limited".
    assert svc.last_failure_reason == "unavailable"
    assert any("dead link" in r.getMessage() for r in caplog.records)
    assert not any("rate limit" in r.getMessage().lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_late_answer_after_giving_up_does_not_touch_the_next_attempt(
    monkeypatch, caplog
):
    """MA answers 'not found' after the budget ran out; that answer belongs to
    the song the game already left and must change nothing."""
    from custom_components.beatify.services.playback import music_assistant as ma

    monkeypatch.setattr(ma, "MA_PLAYBACK_TIMEOUT", 0.1)
    svc, _hass = _service(answer_after=0.4)

    with caplog.at_level(logging.DEBUG):
        await svc.play_song(dict(_SONG))
        # The attempt is over and the next song would be classified from here.
        svc.last_failure_reason = None
        await asyncio.sleep(0.6)  # the late 'not found' lands here

    assert svc.last_failure_reason is None, "the late answer must change nothing"
    assert any(
        "answered after Beatify gave up" in r.getMessage() for r in caplog.records
    )


def _lobby_with(service: MagicMock, n: int = 10):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(n),
        media_player="media_player.sonos",
        base_url="http://localhost:8123",
    )
    gs._media_player_service = service
    gs.media_player = "media_player.sonos"
    gs.platform = "music_assistant"
    return gs


def _failing_service(reason: str) -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = reason
    svc.last_attempted_uri = "spotify:track:x"
    svc.play_song = AsyncMock(return_value=False)
    svc.stop = AsyncMock(return_value=True)
    return svc


@pytest.mark.asyncio
async def test_two_counted_failures_in_a_row_pause_the_game():
    assert MAX_CONSECUTIVE_PLAYBACK_FAILURES == 2
    service = _failing_service("rate_limited")
    gs = _lobby_with(service)

    assert await gs.start_round() is False

    assert service.play_song.await_count == 2
    assert gs.phase == GamePhase.PAUSED
    assert gs.pause_reason == "media_player_error"


@pytest.mark.asyncio
async def test_dead_links_are_skipped_without_pausing():
    """Fast dead links do not count: the game walks past them."""
    service = _failing_service("unavailable")
    gs = _lobby_with(service, n=5)

    await gs.start_round()

    assert service.play_song.await_count >= 3
    assert gs._consecutive_playback_failures == 0
