"""Ending the game over REST must not swallow the podium announcement (#2724).

``advance_to_end`` does not SPEAK the winner and podium phrases — it queues
them. ``_tts_announce`` reserves a slot on the estimated speaker timeline and
hands each phrase to a background task that sleeps until its turn, so the
podium is typically still waiting out the winner's estimate when
``advance_to_end`` returns.

``EndGameView`` called ``end_game()`` right after. That runs ``disable_tts()``
(``_tts_service = None``) and then resets the round counter, so the podium task
woke to either a ``None`` service — the exception swallowed as "TTS
announcement failed" — or the staleness guard. Nothing reached the speaker, and
nothing said so.

The WebSocket path is unaffected: it leaves the game in END and only tears down
on Dismiss. Which means the loss happened exactly on the fallback path — the
one taken when the admin socket is closed and the host is not looking at a
screen, so the spoken podium is all there is.

These tests run the real ``GameState`` with a recording TTS service and assert
on the phrases that actually reached ``speak()``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.game.state_tts import TtsAnnouncerMixin
from custom_components.beatify.server.game_views import EndGameView
from tests.conftest import make_game_state, make_player, make_songs

# Long enough that end_game() would comfortably finish first on origin/main,
# short enough to keep the test instant. The real values are seconds.
_FAKE_PHRASE_SECONDS = 0.25


class _RecordingTts:
    """Stands in for TTSService; remembers what actually reached the speaker."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, message: str, language: str | None = None) -> None:
        self.spoken.append(message)


@pytest.fixture
def game_with_tts():
    """A running game with three scoring players and a recording TTS."""
    tts = _RecordingTts()
    state = make_game_state(tts=lambda **_kwargs: tts)
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.players = {
        "p1": make_player("Alice", 30),
        "p2": make_player("Bob", 20),
        "p3": make_player("Cara", 10),
    }
    state._set_phase(GamePhase.PLAYING)
    return state, tts


def _hass(state):
    hass = MagicMock()
    # No ws_handler: the closed-admin-socket case this endpoint exists for.
    hass.data = {DOMAIN: {"game": state}}
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


@pytest.fixture
def fast_phrases():
    """Shrink the estimated speech time so the queue drains in milliseconds."""
    with patch.object(
        TtsAnnouncerMixin,
        "_estimate_speech_seconds",
        classmethod(lambda cls, message: _FAKE_PHRASE_SECONDS),
    ):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("authorized", "fast_phrases")
class TestRestEndGameKeepsThePodium:
    async def test_both_ceremony_phrases_reach_the_speaker(self, game_with_tts):
        """The regression: on origin/main only the winner phrase arrives."""
        state, tts = game_with_tts
        await state.configure_tts("tts.google_en")

        resp = await EndGameView(_hass(state)).post(_request())

        assert resp.status == 200
        assert len(tts.spoken) == 2, f"only these were spoken: {tts.spoken}"
        winner, podium = tts.spoken
        assert "Alice" in winner
        # Bottom-up, the way a host reads an awards list: Cara, Bob, Alice.
        assert "Cara" in podium
        assert "Bob" in podium
        assert "Alice" in podium

    async def test_the_game_is_still_torn_down(self, game_with_tts):
        """Waiting for the podium must not leave a live game behind."""
        state, _tts = game_with_tts
        await state.configure_tts("tts.google_en")

        resp = await EndGameView(_hass(state)).post(_request())

        assert resp.status == 200
        assert state.game_id is None
        assert state.phase is GamePhase.LOBBY
        assert state._tts_service is None

    async def test_no_tts_configured_still_ends_promptly(self, game_with_tts):
        """Nothing queued, nothing to wait for."""
        state, tts = game_with_tts

        resp = await EndGameView(_hass(state)).post(_request())

        assert resp.status == 200
        assert tts.spoken == []
        assert state.game_id is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("fast_phrases")
class TestDrainAnnouncements:
    async def test_drain_waits_for_a_queued_phrase(self, game_with_tts):
        state, tts = game_with_tts
        await state.configure_tts("tts.google_en")

        await state.announce_winner()
        await state.announce_podium()
        # Both are still only queued at this point.
        assert tts.spoken == []

        assert await state.drain_announcements() is True
        assert len(tts.spoken) == 2

    async def test_drain_is_a_no_op_with_an_empty_queue(self, game_with_tts):
        state, _tts = game_with_tts
        assert await state.drain_announcements() is True

    async def test_drain_reports_a_timeout_instead_of_hanging(self, game_with_tts):
        """A wedged provider must not hold the HTTP request open forever."""
        state, tts = game_with_tts
        await state.configure_tts("tts.google_en")

        with patch.object(
            TtsAnnouncerMixin,
            "_estimate_speech_seconds",
            classmethod(lambda cls, message: 30.0),
        ):
            # The first phrase goes out at once; the second one reserves the
            # speaker for half a minute and is what the drain waits on.
            await state.announce_winner()
            await state.announce_podium()
            assert await state.drain_announcements(timeout=0.01) is False
        assert len(tts.spoken) < 2
        state.async_shutdown()
