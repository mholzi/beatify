"""The TTS resume watchdog: #2576 (do not undo a deliberate stop) and #2710
(the loop lives on the media-player port, so it can finally be run).

After every round start a watchdog walks a ~20 second window and pushes
`media_play` as soon as the player reports `paused`, or reports `idle` with a
title twice in a row. It checked neither the game phase nor `song_stopped`, so
it read two *wanted* states as a hang:

* the host taps "stop song" — `media_stop` leaves a Music Assistant player as
  `idle` WITH a title, which is exactly the stuck signature; the watchdog
  restarted the song the host had just stopped.
* the game pauses (host phone drops off the wifi) — `pause_game` stops the
  speaker, and the watchdog pushed play, so the music kept going under the
  PAUSED banner.

Until #2710 this file could only assert the *source text*: the watchdog was a
closure inside `_start_round_locked` that reached into `self._hass` directly,
so there was nothing to call and nothing to substitute. It is now
`MediaPlayerService.resume_after_announcement`, and the game hands it a
`should_continue` callback — which means the guard is testable as behaviour on
both sides of the seam: the game's callback with a fake speaker and no `hass`
at all, and the loop itself as an ordinary method.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.services.media_player import MediaPlayerService
from tests.conftest import make_game_state, make_songs

# ---------------------------------------------------------------------------
# The game side: what it hands the port, with no Home Assistant in sight
# ---------------------------------------------------------------------------


def _fake_speaker(handovers: list) -> MagicMock:
    """A speaker that records the watchdog handover instead of making one."""
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)

    async def _watch() -> None:
        return None

    def _resume(*, lead_seconds: float, should_continue):
        # Recorded synchronously, because that is when the game hands it over:
        # `create_task` binds the arguments now and runs the body later.
        handovers.append((lead_seconds, should_continue))
        return _watch()

    svc.resume_after_announcement = _resume
    return svc


async def _game_that_started_a_round(handovers: list):
    """A real ``GameState`` mid-round, wired to fakes for speaker and voice."""
    gs = make_game_state(
        media_player=lambda *_a, **_kw: _fake_speaker(handovers),
        tts=lambda **_kw: MagicMock(speak=AsyncMock()),
    )
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.esszimmer",
        base_url="http://h",
    )
    gs.platform = "music_assistant"
    gs.add_player("Alice", MagicMock())
    gs.add_player("Bob", MagicMock())
    for p in gs.players.values():
        p.connected = True
    await gs.configure_tts("tts.google")
    await gs.start_round()
    return gs


@pytest.mark.asyncio
class TestTheGameArmsTheWatchdogThroughThePort:
    async def test_a_round_start_hands_the_watch_to_the_speaker(self):
        """#2710: no `hass` stub anywhere — the fake from #2638 sees the call."""
        handovers: list = []
        gs = await _game_that_started_a_round(handovers)
        try:
            assert len(handovers) == 1
            lead, should_continue = handovers[0]
            assert lead >= 0.0
            assert should_continue() is True
        finally:
            if gs._tts_resume_task:
                gs._tts_resume_task.cancel()

    async def test_stopping_the_song_ends_the_watch(self):
        handovers: list = []
        gs = await _game_that_started_a_round(handovers)
        try:
            _, should_continue = handovers[0]
            gs.song_stopped = True
            assert should_continue() is False
        finally:
            if gs._tts_resume_task:
                gs._tts_resume_task.cancel()

    async def test_pausing_the_game_ends_the_watch(self):
        handovers: list = []
        gs = await _game_that_started_a_round(handovers)
        try:
            _, should_continue = handovers[0]
            await gs.pause_game("admin_disconnected")
            assert gs.phase is GamePhase.PAUSED
            assert should_continue() is False
        finally:
            if gs._tts_resume_task:
                gs._tts_resume_task.cancel()

    async def test_song_stopped_is_a_per_round_flag(self):
        """`song_stopped` belongs to the round — a stop in round 3 must not
        keep the watchdog disarmed in round 4."""
        state = make_game_state()
        state.song_stopped = True
        state._round_manager.reset()
        assert state.song_stopped is False


# ---------------------------------------------------------------------------
# The speaker side: the loop, now an ordinary method
# ---------------------------------------------------------------------------


def _state(kind: str = "playing", *, title: str = "Song", volume: float = 0.5):
    st = MagicMock()
    st.state = kind
    st.attributes = {"media_title": title, "volume_level": volume}
    return st


def _hass(script: list) -> MagicMock:
    """A `hass` whose `states.get` walks `script`, then repeats its last entry.

    Entry 0 is the pre-announcement volume snapshot; with `lead_seconds=0`
    every entry after it is one tick of the polling loop.
    """
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    seq = list(script)
    hass.states.get = MagicMock(
        side_effect=lambda _e: seq.pop(0) if len(seq) > 1 else seq[0]
    )
    return hass


def _service_calls(hass: MagicMock, service: str) -> list:
    return [c for c in hass.services.async_call.call_args_list if c.args[1] == service]


@pytest.mark.asyncio
class TestTheLoopItself:
    async def test_a_deliberate_stop_kicks_nothing(self):
        """The guard runs BEFORE the player is read: reading first and deciding
        afterwards would still fire one kick on the tick where the host
        stopped the song."""
        hass = _hass([_state("idle")])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: False
            )

        assert _service_calls(hass, "media_play") == []
        # one read for the volume snapshot, none from inside the loop
        assert hass.states.get.call_count == 1

    async def test_a_paused_player_is_kicked_three_times_then_left_alone(self):
        hass = _hass([_state("paused")])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert len(_service_calls(hass, "media_play")) == 3

    async def test_idle_with_a_title_counts_as_stuck_after_two_ticks(self):
        """MA voice satellites stick in 'idle' with a title loaded; HA never
        reports 'paused' for them, so 'paused' alone would never fire."""
        hass = _hass([_state("idle", title="Africa")])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert len(_service_calls(hass, "media_play")) == 3

    async def test_idle_without_a_title_is_not_stuck(self):
        hass = _hass([_state("idle", title=None)])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert _service_calls(hass, "media_play") == []

    async def test_the_anticipatory_kick_fires_once_the_lead_is_over(self):
        """v0.7.30: waiting for three idle ticks to confirm what we already
        expect meant 3-4s of silence after "…3, 2, 1, go"."""
        hass = _hass([_state("paused"), _state("paused"), _state("playing")])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=2.0, should_continue=lambda: True
            )

        assert len(_service_calls(hass, "media_play")) == 1

    async def test_a_vanished_entity_ends_the_watch(self):
        hass = _hass([_state("playing"), None])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert hass.states.get.call_count == 2


@pytest.mark.asyncio
class TestTheVolumeRatchetGuard:
    async def test_an_upward_drift_across_an_announcement_is_undone(self):
        """MA's announce duck/restore wrote back a HIGHER level each round on
        a ShieldTV feeding an AV receiver — painfully loud within a few
        rounds."""
        hass = _hass([_state(volume=0.30), _state(volume=0.60)])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        calls = _service_calls(hass, "volume_set")
        assert len(calls) == 1, "the guard must fire once per round, not per tick"
        assert calls[0].args[2]["volume_level"] == 0.30

    async def test_a_drift_after_the_window_is_the_host_turning_it_up(self):
        """The host's own volume buttons must keep working for the rest of the
        round, so the guard only looks inside the announcement window."""
        # snapshot + ticks 0..10 quiet, the rise lands on tick 11
        hass = _hass([_state(volume=0.30)] * 12 + [_state(volume=0.60)])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert _service_calls(hass, "volume_set") == []

    async def test_a_speaker_that_reports_no_level_is_left_alone(self):
        hass = _hass([_state(volume=None), _state(volume=0.90)])
        svc = MediaPlayerService(hass, "media_player.esszimmer")

        with patch("asyncio.sleep", new=AsyncMock()):
            await svc.resume_after_announcement(
                lead_seconds=0.0, should_continue=lambda: True
            )

        assert _service_calls(hass, "volume_set") == []
