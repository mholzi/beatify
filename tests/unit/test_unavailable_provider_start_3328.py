"""#3328 — a start with a provider Music Assistant does not have must fail fast.

Found in the v4.8.7-rc5 live test: a game created with ``apple_music`` while
the Apple Music provider was not available in Music Assistant never started.
Home Assistant logged that ``music_assistant.play_media`` failed ("The provider
is currently unavailable.") 55 ms after the request, but the call was
fire-and-forget, so Beatify waited out its whole 33 s first-play budget. The
live test's HTTP client gave up after 30 s, Home Assistant cancels a handler
whose client hangs up (``handler_cancellation=True``), and the cancellation
unwound through the playback wait without a log line: LOBBY, no error, no log.

Three things are pinned here:

* Music Assistant's refusal ends the attempt at once, names the provider, and
  is not retried with the next URI;
* the game pauses on the first such refusal through the existing
  ``media_player_error`` path, with the provider in the detail the host sees;
* a start whose caller goes away still finishes and tells the room.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.beatify.game.start_gameplay import (
    begin_gameplay,
    start_failure,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.services.media_player import MediaPlayerService
from tests.conftest import make_game_state, make_songs


class ProviderUnavailableError(Exception):
    """Stand-in for music_assistant_models.errors.ProviderUnavailableError."""


def _refused() -> HomeAssistantError:
    """What Home Assistant's MA integration raises (helpers.py wraps it)."""
    try:
        raise ProviderUnavailableError("The provider is currently unavailable.")
    except ProviderUnavailableError as err:
        wrapped = HomeAssistantError("The provider is currently unavailable.")
        wrapped.__cause__ = err
        return wrapped


def _idle_speaker() -> MagicMock:
    state = MagicMock()
    state.state = "paused"
    state.attributes = {
        "media_title": "Villajoyosa",
        "media_artist": "Someone",
        "media_position_updated_at": "2026-10-27T12:15:59+00:00",
        "media_content_id": "spotify--UcpG62CQ://track/4NfCD3XMShOOR3EtV0QZm1",
    }
    return state


def _apple_music_service() -> tuple[MediaPlayerService, MagicMock]:
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=_idle_speaker())

    background: set[asyncio.Task] = set()

    async def _ma_play_media():
        await asyncio.sleep(0.05)  # MA answers after one round trip
        raise _refused()

    async def _call(domain, service, *args, blocking=False, **kwargs):
        """Home Assistant's semantics: blocking=False runs the service in the
        background, where a failure is only logged (core.py)."""
        if (domain, service) != ("music_assistant", "play_media"):
            return None
        if blocking:
            return await _ma_play_media()
        task = asyncio.ensure_future(_ma_play_media())
        background.add(task)
        task.add_done_callback(lambda t: (background.discard(t), t.exception()))
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    svc = MediaPlayerService(
        hass,
        "media_player.esszimmer",
        platform="music_assistant",
        provider="apple_music",
    )
    return svc, hass


_SONG = {
    "title": "Dancing In the Dark",
    "artist": "Bruce Springsteen",
    "year": 1984,
    "uri": "spotify:track:7FwBtcecmlpc1sLySPXeGE",
    "uri_apple_music": "applemusic://track/1476083695",
    "_resolved_uri": "applemusic://track/1476083695",
}


@pytest.mark.asyncio
async def test_a_refused_play_fails_at_once_not_after_the_budget(caplog):
    """The real budget (33 s on the first play) stays in force: the refusal
    alone has to end the attempt. Without the fix this waits all 33 s."""
    svc, hass = _apple_music_service()

    with caplog.at_level(logging.ERROR):
        result = await asyncio.wait_for(svc.play_song(dict(_SONG)), timeout=3)

    assert result is False
    assert svc.last_failure_reason == "provider_unavailable"
    plays = [
        c
        for c in hass.services.async_call.await_args_list
        if c.args[:2] == ("music_assistant", "play_media")
    ]
    assert len(plays) == 1, "a refused provider must not be retried per URI"
    line = next(r for r in caplog.records if "#3328" in r.getMessage())
    assert line.levelno == logging.ERROR
    assert "Apple Music" in line.getMessage()
    assert "not available in Music Assistant" in line.getMessage()


def _lobby_with(service: MagicMock):
    songs = make_songs(10)
    for i, song in enumerate(songs):
        song["uri_apple_music"] = f"applemusic://track/{1476083695 + i}"
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=songs,
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
        provider="apple_music",
    )
    gs._media_player_service = service
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    return gs


def _refusing_speaker() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = "provider_unavailable"
    svc.last_attempted_uri = "apple_music://track/1476083695"
    svc.play_song = AsyncMock(return_value=False)
    svc.stop = AsyncMock(return_value=True)
    return svc


@pytest.mark.asyncio
async def test_the_first_refusal_pauses_with_the_provider_named():
    """Skipping through the playlist would only delay the same answer."""
    service = _refusing_speaker()
    gs = _lobby_with(service)

    assert await gs.start_round() is False

    assert service.play_song.await_count == 1
    assert gs.phase == GamePhase.PAUSED
    assert gs.pause_reason == "media_player_error"
    failure = start_failure(gs)
    # The existing start-failure message, not a new one.
    assert failure["message_key"] == "MEDIA_PLAYER_ERROR"
    assert "Apple Music is not available in Music Assistant" in failure["detail"]
    assert "media_player.esszimmer" in failure["detail"]


@pytest.mark.asyncio
async def test_the_pause_state_carries_the_cause_for_the_headline_3339():
    """The headline must not offer rate limiting when the cause is known.

    The detail line names the provider, but the headline above it is picked by
    the host's browser. It can only pick the single-cause wording if the state
    says what the cause was.
    """
    gs = _lobby_with(_refusing_speaker())

    assert await gs.start_round() is False

    state = gs.get_state()
    assert state["last_error_kind"] == "provider_unavailable"
    assert state["provider"] == "apple_music"
    # The cause travels to the host's phone (a player socket) as well.
    from custom_components.beatify.server.serializers import (
        _PLAYER_VISIBLE_PAUSED,
    )

    assert "last_error_kind" in _PLAYER_VISIBLE_PAUSED


@pytest.mark.asyncio
async def test_a_start_outlives_a_caller_that_hangs_up():
    """Home Assistant cancels the request handler when the client goes away.
    The start must finish regardless and announce its result to the room."""
    gs = make_game_state()
    release = asyncio.Event()
    finished: list[bool] = []

    async def start_round(*_a, **_kw):
        await release.wait()
        gs.phase = GamePhase.PAUSED
        gs.pause_reason = "media_player_error"
        finished.append(True)
        return False

    gs.start_round = start_round
    ws_handler = MagicMock()
    ws_handler.broadcast = AsyncMock()
    ws_handler.broadcast_state = AsyncMock()

    caller = asyncio.ensure_future(begin_gameplay(gs, ws_handler))
    await asyncio.sleep(0.01)
    caller.cancel()  # the 30 s client timeout
    with pytest.raises(asyncio.CancelledError):
        await caller

    release.set()
    for _ in range(5):
        await asyncio.sleep(0)

    assert finished == [True]
    ws_handler.broadcast_state.assert_awaited()


@pytest.mark.asyncio
async def test_a_missing_service_still_fails_at_once():
    """Running play_media in its own task must not swallow an error that never
    reached Music Assistant (no integration loaded): it is raised as before."""
    # The class play_song catches, whatever another test did to the stub.
    from custom_components.beatify.services.media_player import ServiceNotFound

    svc, hass = _apple_music_service()

    async def _call(domain, service, *args, **kwargs):
        if (domain, service) == ("music_assistant", "play_media"):
            raise ServiceNotFound(domain, service)
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)

    result = await asyncio.wait_for(svc.play_song(dict(_SONG)), timeout=3)

    assert result is False
