"""#3278: a start Beatify gave up on must not replace the current round's song.

Music Assistant can finish a play request long after Beatify's budget ran out
and the round moved on (Spotify rate limiter, v4.8.6-rc2 live test). The #3101
cancel does not reach a request MA is still resolving, so the abandoned track
landed on the speaker one second after the next round was confirmed and stayed
there through the reveal — the room heard one song and was scored on another.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback import music_assistant as ma
from custom_components.beatify.services.playback.context import PlayerContext
from custom_components.beatify.services.playback.music_assistant import (
    MusicAssistantStrategy,
)

ENTITY = "media_player.esszimmer"
SKIPPED = "spotify:track:eSZiUGjU"  # "Bello e impossibile"
CURRENT = "spotify:track:q2h9Au8V"  # "The Riddle"


def _state(state, title, content_id="", stamp="t0", artist="Someone"):
    mock = MagicMock()
    mock.state = state
    mock.attributes = {
        "media_title": title,
        "media_artist": artist,
        "media_content_id": content_id,
        "media_position_updated_at": stamp,
    }
    return mock


def _event(new_state):
    ev = MagicMock()
    ev.data = {"new_state": new_state}
    return ev


class _Harness:
    """A Music Assistant strategy over a mock hass whose state we steer."""

    def __init__(self) -> None:
        self.hass = MagicMock()
        self.hass.services.async_call = AsyncMock()
        self.tasks: list = []
        self.hass.async_create_task = MagicMock(side_effect=self.tasks.append)
        self.current = _state("idle", "")
        self.hass.states.get = MagicMock(side_effect=lambda _e: self.current)
        self.context = PlayerContext(
            self.hass, ENTITY, platform="music_assistant", provider="spotify"
        )
        self.strategy = MusicAssistantStrategy(self.context)
        self.subs: list = []

    def track(self, _hass, _entities, cb):
        unsub = MagicMock()
        self.subs.append((cb, unsub))
        return unsub

    async def run_tasks(self) -> None:
        while self.tasks:
            await self.tasks.pop(0)

    def calls(self, domain, service):
        return [
            c
            for c in self.hass.services.async_call.await_args_list
            if c.args[:2] == (domain, service)
        ]


def _reads(first, then):
    """states.get: ``first`` for the pre-call snapshot, ``then`` afterwards."""
    seen = []

    def get(_e):
        seen.append(1)
        return first if len(seen) == 1 else then

    return get


def _song(uri, title, artist="Someone"):
    return {"title": title, "artist": artist, "uri": uri, "_resolved_uri": uri}


async def _skip_then_play(h: _Harness, *, second_title="The Riddle") -> None:
    """Round N+1: the first song times out (abandoned), the next one starts."""
    with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
        assert await h.strategy.play(_song(SKIPPED, "Bello e impossibile")) is False
        # The next song confirms on the first read after the request.
        h.hass.states.get = MagicMock(
            side_effect=_reads(
                _state("idle", ""),
                _state(
                    "playing", second_title, f"spotify://track/{CURRENT[-8:]}", "t1"
                ),
            )
        )
        assert await h.strategy.play(_song(CURRENT, second_title)) is True


@pytest.mark.asyncio
async def test_late_abandoned_start_is_replaced_by_the_current_song():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, _ = h.subs[-1]
        plays_before = len(h.calls("music_assistant", "play_media"))

        # 1 s later MA finishes the abandoned request and swaps the speaker.
        guard(_event(_state("playing", "Bello e impossibile", SKIPPED, "t2")))
        await h.run_tasks()

    plays = h.calls("music_assistant", "play_media")
    assert len(plays) == plays_before + 1
    assert plays[-1].args[2]["media_id"] == CURRENT
    assert plays[-1].args[2]["enqueue"] == "replace"
    # Nothing silenced: the round is meant to be audible.
    assert not h.calls("media_player", "media_stop")[2:]


@pytest.mark.asyncio
async def test_current_song_updates_never_trigger_a_correction():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, _ = h.subs[-1]
        plays_before = len(h.calls("music_assistant", "play_media"))
        guard(_event(_state("playing", "The Riddle", CURRENT, "t3")))
        guard(_event(_state("paused", "Bello e impossibile", SKIPPED, "t4")))
        await h.run_tasks()
    assert len(h.calls("music_assistant", "play_media")) == plays_before


@pytest.mark.asyncio
async def test_no_guard_without_an_abandoned_start():
    """The normal path subscribes to nothing beyond its own confirmation."""
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        h.hass.states.get = MagicMock(
            side_effect=_reads(
                _state("idle", ""), _state("playing", "The Riddle", CURRENT, "t1")
            )
        )
        assert await h.strategy.play(_song(CURRENT, "The Riddle")) is True
    # Only try_play's own confirmation listener — and it is already gone.
    assert len(h.subs) == 1
    h.subs[0][1].assert_called_once()
    assert h.strategy._stale_guard_unsub is None


@pytest.mark.asyncio
async def test_correction_while_stopped_is_silenced_again():
    """A late arrival during a sample stop or pause must not leave the old
    song queued for the reveal's resume, nor make the room audible."""
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, _ = h.subs[-1]
        h.context.audio_wanted = False  # shell.stop() — sample stop
        stops_before = len(h.calls("media_player", "media_stop"))

        guard(_event(_state("playing", "Bello e impossibile", SKIPPED, "t2")))
        await h.run_tasks()
        assert h.calls("music_assistant", "play_media")[-1].args[2]["media_id"] == (
            CURRENT
        )
        # The corrected start loads → stopped again.
        guard(_event(_state("playing", "The Riddle", CURRENT, "t3")))
        await h.run_tasks()

    assert len(h.calls("media_player", "media_stop")) == stops_before + 1


@pytest.mark.asyncio
async def test_late_start_of_the_same_song_is_left_alone():
    """Another URI candidate of the song being played is the right music."""
    h = _Harness()
    other_uri = "spotify:track:altCand1"
    with patch.object(ma, "async_track_state_change_event", h.track):
        with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
            assert await h.strategy.play(_song(other_uri, "The Riddle")) is False
            h.hass.states.get = MagicMock(
                side_effect=_reads(
                    _state("idle", ""), _state("playing", "The Riddle", CURRENT, "t1")
                )
            )
            assert await h.strategy.play(_song(CURRENT, "The Riddle")) is True
    assert h.strategy._stale_guard_unsub is None


@pytest.mark.asyncio
async def test_game_end_stops_the_guard():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, unsub = h.subs[-1]
        h.strategy.forget_pending_starts()
        unsub.assert_called_once()
        plays_before = len(h.calls("music_assistant", "play_media"))
        guard(_event(_state("playing", "Bello e impossibile", SKIPPED, "t2")))
        await h.run_tasks()
    assert len(h.calls("music_assistant", "play_media")) == plays_before


@pytest.mark.asyncio
async def test_expired_abandoned_start_is_ignored():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, _ = h.subs[-1]
        with patch.object(ma, "MA_STALE_START_WINDOW", -1.0):
            guard(_event(_state("playing", "Bello e impossibile", SKIPPED, "t2")))
        await h.run_tasks()
    assert h.calls("music_assistant", "play_media")[-1].args[2]["media_id"] == CURRENT
    assert len(h.calls("music_assistant", "play_media")) == 2


@pytest.mark.asyncio
async def test_corrections_are_capped():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        guard, _ = h.subs[-1]
        for i in range(ma.MA_STALE_START_MAX_CORRECTIONS + 2):
            # Each arrival counts once; re-add so the guard sees it again.
            h.strategy._note_abandoned_start(SKIPPED, "x|y")
            guard(_event(_state("playing", "Bello", SKIPPED, f"t{i + 5}")))
        await h.run_tasks()
    assert len(h.calls("music_assistant", "play_media")) == (
        2 + ma.MA_STALE_START_MAX_CORRECTIONS
    )


@pytest.mark.asyncio
async def test_abandoned_track_arriving_during_the_wait_does_not_confirm():
    """Same artist would pass the #1381 Path 2 gate — the content id says no."""
    h = _Harness()
    with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
        assert await h.strategy.play(_song(SKIPPED, "Faith", "George Michael")) is (
            False
        )
        h.hass.states.get = MagicMock(
            side_effect=_reads(
                _state("playing", "Old song", "spotify://track/oldsong", "t0"),
                _state(
                    "playing", "Faith (Remastered)", SKIPPED, "t1", "George Michael"
                ),
            )
        )
        result = await h.strategy.play(
            _song(CURRENT, "Careless Whisper", artist="George Michael")
        )
    assert result is False
    assert h.context.last_failure_reason == "unavailable"


@pytest.mark.asyncio
async def test_stale_track_is_not_accepted_by_the_345_tolerance():
    """Title moved, so #345 would say "continuing anyway" — but it moved to
    the abandoned song, not to ours."""
    h = _Harness()
    with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
        assert (
            await h.strategy.play(
                _song(SKIPPED, "Bello e impossibile", "Gianna Nannini")
            )
            is False
        )
        h.hass.states.get = MagicMock(
            side_effect=_reads(
                _state("playing", "Old song", "spotify://track/oldsong", "t0"),
                _state(
                    "playing", "Bello e impossibile", SKIPPED, "t9", "Gianna Nannini"
                ),
            )
        )
        result = await h.strategy.play(_song(CURRENT, "The Riddle", "Nik Kershaw"))
    assert result is False
    assert h.context.last_failure_reason == "unavailable"


@pytest.mark.asyncio
async def test_shell_tracks_whether_audio_is_wanted_and_forgets_on_game_end():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    svc = MediaPlayerService(hass, ENTITY, platform="music_assistant")
    assert svc._context.audio_wanted is True
    await svc.stop()
    assert svc._context.audio_wanted is False
    await svc.play()
    assert svc._context.audio_wanted is True

    svc._strategy.forget_pending_starts = MagicMock()
    await svc.restore_queue()
    svc._strategy.forget_pending_starts.assert_called_once()
    svc._strategy.forget_pending_starts.reset_mock()
    svc.snapshot_saved_states()
    svc._strategy.forget_pending_starts.assert_called_once()


@pytest.mark.asyncio
async def test_late_start_of_the_same_song_still_confirms_during_the_wait():
    """Another URI of the song being started, arriving late, is our music."""
    h = _Harness()
    other_uri = "spotify:track:altCand1"
    with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
        assert await h.strategy.play(_song(other_uri, "The Riddle")) is False
        h.hass.states.get = MagicMock(
            side_effect=_reads(
                _state("playing", "Old song", "spotify://track/oldsong", "t0"),
                _state("playing", "The Riddle", other_uri, "t1"),
            )
        )
        assert await h.strategy.play(_song(CURRENT, "The Riddle")) is True
