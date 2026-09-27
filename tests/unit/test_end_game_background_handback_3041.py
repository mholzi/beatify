"""REST end-game must not wait for the speaker hand-back (#3041).

``EndGameView`` awaited ``end_game()``, and ``end_game()`` awaited the volume
and Music Assistant queue restore — ~8 s on real hardware (track load plus the
#2605 pause hold). Only after that was ``game_ended`` broadcast and the HTTP
response sent, so the TV sat on the podium and "Start New Game" hung.

The hand-back now runs as a tracked background task. These tests pin three
things: the response and the broadcast do not wait for it, it still runs to
completion (and survives a failing half), and a new game started meanwhile
waits for it before it can touch the same speaker.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server.game_views import EndGameView
from tests.conftest import make_game_state, make_songs

from .conftest import make_start_game_request


class _SlowSpeaker:
    """A media-player service whose queue restore blocks until released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[str] = []
        self.queue_restored = False
        self.volume_error: Exception | None = None

    async def restore_volume(self) -> bool:
        self.calls.append("volume")
        if self.volume_error is not None:
            raise self.volume_error
        return True

    async def restore_queue(self) -> bool:
        self.calls.append("queue")
        await self.release.wait()
        self.queue_restored = True
        return True


@pytest.fixture
def game_with_speaker():
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    speaker = _SlowSpeaker()
    state._media_player_service = speaker
    return state, speaker


def _hass(state, ws_handler):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": ws_handler}}
    return hass


def _request():
    request = MagicMock()
    request.remote = "1.2.3.4"
    return request


@pytest.fixture
def authorized():
    with patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("authorized")
class TestRestEndGameDoesNotWaitForTheSpeaker:
    async def test_responds_and_broadcasts_before_the_restore_finishes(
        self, game_with_speaker
    ):
        state, speaker = game_with_speaker
        ws_handler = MagicMock()
        ws_handler.broadcast = AsyncMock()

        # On origin/main this times out: the view sits on restore_queue().
        resp = await asyncio.wait_for(
            EndGameView(_hass(state, ws_handler)).post(_request()), timeout=1.0
        )

        assert resp.status == 200
        ws_handler.broadcast.assert_awaited_once_with({"type": "game_ended"})
        assert state.game_id is None
        # The hand-back is under way but not done.
        await asyncio.sleep(0)
        assert speaker.calls == ["volume", "queue"]
        assert speaker.queue_restored is False
        task = state._speaker_handback_task
        assert task is not None and not task.done()

        speaker.release.set()
        await asyncio.wait_for(task, timeout=1.0)
        assert speaker.queue_restored is True
        assert state._speaker_handback_task is None

    async def test_a_failing_volume_restore_is_logged_and_the_queue_still_runs(
        self, game_with_speaker, caplog
    ):
        state, speaker = game_with_speaker
        speaker.volume_error = RuntimeError("speaker went away")
        speaker.release.set()
        ws_handler = MagicMock()
        ws_handler.broadcast = AsyncMock()

        resp = await EndGameView(_hass(state, ws_handler)).post(_request())
        assert resp.status == 200
        await asyncio.wait_for(state._speaker_handback_task, timeout=1.0)

        assert speaker.queue_restored is True
        assert "Restoring the speaker volume after the game failed" in caplog.text


@pytest.mark.asyncio
class TestInlineEndGameIsUnchanged:
    async def test_plain_end_game_still_restores_inline(self, game_with_speaker):
        """Dismiss, force-reset and the END auto-clean keep the old contract."""
        state, speaker = game_with_speaker
        speaker.release.set()

        await state.end_game()

        assert speaker.queue_restored is True
        assert state._speaker_handback_task is None


@pytest.mark.asyncio
class TestNextGameWaitsForTheHandback:
    async def test_wait_returns_once_the_handback_is_done(self, game_with_speaker):
        state, speaker = game_with_speaker
        await state.end_game(defer_speaker_handback=True)

        waiter = asyncio.create_task(state.wait_for_speaker_handback())
        await asyncio.sleep(0.05)
        assert not waiter.done()

        speaker.release.set()
        assert await asyncio.wait_for(waiter, timeout=1.0) is True

    async def test_wait_gives_up_after_the_timeout(self, game_with_speaker):
        state, speaker = game_with_speaker
        await state.end_game(defer_speaker_handback=True)

        assert await state.wait_for_speaker_handback(timeout=0.05) is False
        # Giving up does not cancel the restore — the host still gets it back.
        speaker.release.set()
        await asyncio.wait_for(state._speaker_handback_task, timeout=1.0)
        assert speaker.queue_restored is True

    async def test_start_game_is_held_until_the_speaker_is_handed_back(
        self, start_game_env
    ):
        view, hass, body = start_game_env
        state = hass.data[DOMAIN]["game"]
        release = asyncio.Event()
        state._speaker_handback_task = asyncio.create_task(release.wait())

        start = asyncio.create_task(view.post(make_start_game_request(hass, body)))
        await asyncio.sleep(0.05)
        assert not start.done()
        assert state.game_id is None  # create_game has not run yet

        release.set()
        resp = await asyncio.wait_for(start, timeout=2.0)
        assert resp.status == 200
        assert state.game_id is not None
