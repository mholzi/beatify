"""#3562 - a round start never leaves the game in REVEAL without a deadline.

Reported on v5.1.0-rc3 with Music Assistant's Spotify provider rate limiting:
after ``next_round`` the announced 25 s playback budget never produced a
result, and the game sat in REVEAL for minutes. Two things combined:

* the admin handler awaited the whole round start inline in the websocket
  reader loop, so the socket stopped answering pings, the client dropped it
  after ~22 s, and the handler task - the round start with it - was cancelled
  mid-await, silently, leaving the phase on REVEAL;
* nothing around the confirmation wait had a deadline of its own (queue
  snapshot, post-timeout state read), so a call parked there outlived the
  budget.

Pinned here: a hung start ends in PLAYING with the next song or PAUSED with
``media_player_error`` within budget + grace, a late answer is still accepted,
and the websocket keeps serving traffic - and finishes the start - while a
start is pending, including after the host's socket drops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback import (
    BrowserClientRegistry,
)
from custom_components.beatify.services.playback import music_assistant as ma
from tests.conftest import make_game_state, make_songs

BUDGET = 0.2
GRACE = 0.2


class _Speaker:
    """A Music Assistant speaker whose state follows what was requested."""

    def __init__(self) -> None:
        self.state = self._attrs("paused", "Sunny", "0", "spotify--abc://track/old")
        self.play_requests: list[str] = []

    @staticmethod
    def _attrs(state: str, title: str, stamp: str, content_id: str) -> MagicMock:
        st = MagicMock()
        st.state = state
        st.attributes = {
            "media_title": title,
            "media_artist": "Someone",
            "media_position_updated_at": stamp,
            "media_content_id": content_id,
        }
        return st

    def start(self, uri: str, title: str) -> None:
        self.play_requests.append(uri)
        self.state = self._attrs(
            "playing", title, f"t{len(self.play_requests)}", f"spotify--abc://{uri}"
        )


def _service(*, play_media, get_queue=None):
    """A real MediaPlayerService (Music Assistant) over a scripted hass."""
    speaker = _Speaker()
    hass = MagicMock()
    hass.states.get = MagicMock(side_effect=lambda _eid: speaker.state)

    async def _call(domain, service, data=None, *args, blocking=False, **kwargs):
        if (domain, service) == ("music_assistant", "play_media"):
            return await play_media(speaker, data)
        if (domain, service) == ("music_assistant", "get_queue") and get_queue:
            return await get_queue()
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)
    svc = MediaPlayerService(
        hass,
        "media_player.sonos",
        platform="music_assistant",
        provider="spotify",
    )
    return svc, speaker


async def _plays_at_once(speaker: _Speaker, data) -> None:
    uri = data["media_id"]
    speaker.start(uri, f"Song {uri[-1]}")


def _lobby_with(service, n: int = 10):
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


@pytest.fixture(autouse=True)
def _short_budget(monkeypatch):
    monkeypatch.setattr(ma, "MA_PLAYBACK_TIMEOUT", BUDGET)
    monkeypatch.setattr(ma, "MA_ATTEMPT_GRACE", GRACE)
    monkeypatch.setattr(ma, "MA_QUEUE_SNAPSHOT_TIMEOUT", BUDGET)


def _hang_state_read_once(svc) -> None:
    """The post-budget state read parks forever on the FIRST attempt only."""
    real = svc._context.state_with_retry
    calls = {"n": 0}

    async def _state_with_retry(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.Event().wait()
        return await real(*args, **kwargs)

    svc._context.state_with_retry = _state_with_retry


# ---------------------------------------------------------------------------
# A start that never returns
# ---------------------------------------------------------------------------


async def test_play_call_that_never_returns_is_skipped_and_the_next_song_plays(
    caplog,
):
    """First play_media hangs, the speaker never changes, and the code after the
    budget hangs too: the hard deadline fires, the song is skipped, round 1
    plays the NEXT song."""
    hung: dict = {"first": True, "uri": None}

    async def play_media(speaker, data):
        if hung["first"]:
            hung["first"] = False
            hung["uri"] = data["media_id"]
            await asyncio.Event().wait()  # Music Assistant never answers
        await _plays_at_once(speaker, data)

    svc, speaker = _service(play_media=play_media)
    _hang_state_read_once(svc)
    gs = _lobby_with(svc)

    started = time.monotonic()
    with caplog.at_level(logging.ERROR):
        ok = await asyncio.wait_for(gs.start_round(), timeout=5)
    took = time.monotonic() - started

    assert ok is True
    assert gs.phase == GamePhase.PLAYING
    assert hung["uri"] is not None
    assert speaker.play_requests == [gs.current_song["_resolved_uri"]]
    assert gs.current_song["_resolved_uri"] != hung["uri"], "the hung song was skipped"
    # First play gets the cold-start budget (x4/3), plus grace, plus slack.
    assert took < BUDGET * 4 / 3 + GRACE + 1.0
    assert any(
        "hard deadline fired" in r.getMessage() and "#3562" in r.getMessage()
        for r in caplog.records
    ), "the guard says so when it fires"


async def test_every_start_hanging_pauses_with_media_player_error():
    async def play_media(speaker, data):
        await asyncio.Event().wait()

    svc, _speaker = _service(play_media=play_media)

    async def _never(*args, **kwargs):
        await asyncio.Event().wait()

    svc._context.state_with_retry = _never
    gs = _lobby_with(svc)

    started = time.monotonic()
    ok = await asyncio.wait_for(gs.start_round(), timeout=10)
    took = time.monotonic() - started

    assert ok is False
    assert gs.phase == GamePhase.PAUSED
    assert gs.pause_reason == "media_player_error"
    # Two counted failures (MAX_CONSECUTIVE_PLAYBACK_FAILURES), each ended by
    # the guard, plus the skip pause between them.
    assert took < 2 * (BUDGET * 4 / 3 + GRACE) + 2.0


async def test_hung_queue_snapshot_does_not_hold_the_start(caplog):
    """get_queue goes through the same rate-limited provider and has no timeout
    of its own; the snapshot is bounded and the round plays."""

    async def get_queue():
        await asyncio.Event().wait()

    svc, speaker = _service(play_media=_plays_at_once, get_queue=get_queue)
    gs = _lobby_with(svc)

    started = time.monotonic()
    ok = await asyncio.wait_for(gs.start_round(), timeout=5)

    assert ok is True
    assert gs.phase == GamePhase.PLAYING
    assert speaker.play_requests == [gs.current_song["_resolved_uri"]]
    assert time.monotonic() - started < BUDGET + 1.0


# ---------------------------------------------------------------------------
# A start that returns late
# ---------------------------------------------------------------------------


async def test_late_confirmation_inside_the_grace_still_plays_this_song():
    """Music Assistant answers after the budget but the post-budget read is slow
    too: both finish inside the grace, so nothing is cut short."""

    async def play_media(speaker, data):
        await asyncio.sleep(BUDGET * 1.5)  # past the 0.27 s first-play budget
        await _plays_at_once(speaker, data)

    svc, speaker = _service(play_media=play_media)
    real = svc._context.state_with_retry

    async def slow_read(*args, **kwargs):
        await asyncio.sleep(GRACE / 4)
        return await real(*args, **kwargs)

    svc._context.state_with_retry = slow_read
    gs = _lobby_with(svc)

    ok = await asyncio.wait_for(gs.start_round(), timeout=5)

    assert ok is True
    assert gs.phase == GamePhase.PLAYING
    assert speaker.play_requests == [gs.current_song["_resolved_uri"]]
    assert len(speaker.play_requests) == 1, "no skip, no second request"


async def test_backstop_ends_a_play_song_that_ignores_every_inner_deadline(
    monkeypatch, caplog
):
    """Any strategy: the outer deadline of play_song is the last line."""
    from custom_components.beatify.services import media_player as mp

    monkeypatch.setattr(mp, "ROUND_START_HARD_DEADLINE", 0.2)

    svc, _speaker = _service(play_media=_plays_at_once)

    async def hang(song):
        await asyncio.Event().wait()

    svc._strategy.play = hang

    with caplog.at_level(logging.ERROR):
        result = await asyncio.wait_for(
            svc.play_song({"_resolved_uri": "spotify:track:x", "title": "T"}),
            timeout=2,
        )

    assert result is False
    assert svc.last_failure_reason == "error"
    assert any("hard deadline" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# The websocket stays alive while a start is pending
# ---------------------------------------------------------------------------


async def _revealed_game(play_song):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(6),
        media_player="media_player.x",
        base_url="http://h",
    )
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    gs._media_player_service = svc
    gs.platform = "music_assistant"
    ws = MagicMock()
    ws.closed = False
    ws.send_json = AsyncMock()
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True
    assert await gs.start_round() is True
    await gs.end_round()
    assert gs.phase == GamePhase.REVEAL
    svc.play_song = AsyncMock(side_effect=play_song)
    return gs


async def _serve(gs):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(hass, browser_clients=BrowserClientRegistry())
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    handler.is_admin_socket = lambda ws: True  # type: ignore[method-assign]
    app = web.Application()
    app.router.add_get("/ws", handler.handle)
    client = TestClient(TestServer(app))
    await client.start_server()
    return handler, client


async def _recv(ws, kind, timeout=2.0):
    async with asyncio.timeout(timeout):
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == kind:
                return msg


async def test_socket_keeps_serving_while_next_round_waits_on_the_speaker():
    release = asyncio.Event()

    async def play_song(song):
        await release.wait()
        return True

    gs = await _revealed_game(play_song)
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "admin", "action": "next_round"})
        await asyncio.sleep(0.05)  # the start is now parked on the speaker
        assert gs.phase == GamePhase.REVEAL

        # Same socket, and a second one: both still answered.
        await ws.send_json({"type": "ping"})
        assert (await _recv(ws, "pong"))["type"] == "pong"
        other = await client.ws_connect("/ws")
        await other.send_json({"type": "ping"})
        assert (await _recv(other, "pong"))["type"] == "pong"

        release.set()
        async with asyncio.timeout(2):
            while gs.phase != GamePhase.PLAYING:
                await asyncio.sleep(0.01)
        assert gs.round == 2
        await ws.close()
        await other.close()
    finally:
        release.set()
        await client.close()


async def test_round_start_survives_the_hosts_socket_dropping():
    """The report: the admin socket dropped ~22 s into the pending call and the
    start died with it. It must run to the end without its socket."""
    release = asyncio.Event()

    async def play_song(song):
        await release.wait()
        return True

    gs = await _revealed_game(play_song)
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "admin", "action": "next_round"})
        await asyncio.sleep(0.05)
        await ws.close()  # the host's socket drops mid-start
        await asyncio.sleep(0.1)
        assert gs.phase == GamePhase.REVEAL

        release.set()
        async with asyncio.timeout(2):
            while gs.phase != GamePhase.PLAYING:
                await asyncio.sleep(0.01)
        assert gs.round == 2
    finally:
        release.set()
        await client.close()


async def test_failed_start_over_the_socket_ends_paused_not_in_reveal():
    async def play_song(song):
        return False

    gs = await _revealed_game(play_song)
    gs._media_player_service.last_failure_reason = "error"
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "admin", "action": "next_round"})
        async with asyncio.timeout(3):
            while gs.phase == GamePhase.REVEAL:
                await asyncio.sleep(0.01)
        assert gs.phase == GamePhase.PAUSED
        assert gs.pause_reason == "media_player_error"
        await ws.close()
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Round-start dispatches are serialized
# ---------------------------------------------------------------------------


async def test_two_next_rounds_back_to_back_advance_exactly_once():
    calls = []

    async def play_song(song):
        calls.append(song)
        await asyncio.sleep(0.1)
        return True

    gs = await _revealed_game(play_song)
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        other = await client.ws_connect("/ws")
        await ws.send_json({"type": "admin", "action": "next_round"})
        await other.send_json({"type": "admin", "action": "next_round"})
        await asyncio.sleep(0.6)
        assert gs.phase == GamePhase.PLAYING
        assert gs.round == 2, "one advance, the second tap hit the stale guard"
        assert len(calls) == 1
        await ws.close()
        await other.close()
    finally:
        await client.close()


async def test_hung_first_start_does_not_block_the_second_beyond_the_deadline(
    monkeypatch,
):
    """The first start hangs; the hard deadline ends it, then the lock frees."""
    from custom_components.beatify.services import media_player as mp

    monkeypatch.setattr(mp, "ROUND_START_HARD_DEADLINE", 0.3)
    svc, speaker = _service(play_media=_plays_at_once)
    first = {"hang": True}
    real_play = svc._strategy.play

    async def play(song):
        if first["hang"]:
            first["hang"] = False
            await asyncio.Event().wait()
        return await real_play(song)

    svc._strategy.play = play
    gs = await _revealed_game(None)
    gs._media_player_service = svc
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        started = time.monotonic()
        await ws.send_json({"type": "admin", "action": "next_round"})
        await asyncio.sleep(0.05)
        assert handler._round_start_dispatch_lock.locked()
        await ws.send_json({"type": "admin", "action": "next_round"})
        async with asyncio.timeout(5):
            while not (gs.phase == GamePhase.PLAYING and speaker.play_requests):
                await asyncio.sleep(0.02)
        assert time.monotonic() - started < 0.3 + 2.0
        async with asyncio.timeout(2):
            while handler._round_start_dispatch_lock.locked():
                await asyncio.sleep(0.02)
        await ws.close()
    finally:
        await client.close()


async def test_other_messages_are_served_while_the_lock_is_held():
    release = asyncio.Event()

    async def play_song(song):
        await release.wait()
        return True

    gs = await _revealed_game(play_song)
    handler, client = await _serve(gs)
    try:
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "admin", "action": "next_round"})
        await asyncio.sleep(0.05)
        assert handler._round_start_dispatch_lock.locked()
        await ws.send_json({"type": "ping"})
        assert (await _recv(ws, "pong"))["type"] == "pong"
        await ws.send_json({"type": "admin", "action": "set_volume", "direction": "up"})
        await ws.send_json({"type": "ping"})
        assert (await _recv(ws, "pong"))["type"] == "pong"
        release.set()
        await ws.close()
    finally:
        release.set()
        await client.close()
