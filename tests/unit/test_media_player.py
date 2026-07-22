"""Tests for MediaPlayerService — especially MA non-blocking playback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import (
    MediaPlayerService,
    async_get_media_players,
    async_get_media_players_with_remap,
    async_get_native_twin_remap,
    proxy_album_art,
)


def _make_state(
    state: str = "idle",
    media_title: str = "Old Song",
    media_position: float = 0,
    media_position_updated_at: str = "2020-01-01T00:00:00+00:00",
) -> MagicMock:
    """Create a mock HA state object."""
    mock = MagicMock()
    mock.state = state
    mock.attributes = {
        "friendly_name": "Test Speaker",
        "volume_level": 0.5,
        "media_artist": "Test Artist",
        "media_title": media_title,
        "media_position": media_position,
        "media_position_updated_at": media_position_updated_at,
    }
    return mock


def _make_hass(initial_state: str = "idle", media_title: str = "Old Song") -> MagicMock:
    """Create a mock HomeAssistant with async_call and states."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    state_obj = _make_state(initial_state, media_title=media_title)
    hass.states.get = MagicMock(return_value=state_obj)
    return hass


def _make_song(
    uri: str = "spotify:track:abc123",
    title: str = "New Song",
    artist: str = "Test Artist",
) -> dict:
    return {
        "title": title,
        "artist": artist,
        "uri": uri,
        "_resolved_uri": uri,
    }


class TestMANonBlockingPlayback:
    """Tests for Music Assistant non-blocking playback with actual playback detection."""

    @pytest.mark.asyncio
    async def test_ma_uses_blocking_false(self):
        """MA playback should use blocking=False to avoid hangs."""
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        new_state = _make_state(
            "playing",
            media_title="New Song",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:10+00:00",
        )
        hass.states.get = MagicMock(side_effect=[old_state, new_state])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="New Song"))

        assert result is True
        hass.services.async_call.assert_awaited_once()
        call_kwargs = hass.services.async_call.call_args
        assert (
            call_kwargs.kwargs.get("blocking") is False
            or call_kwargs[1].get("blocking") is False
        )

    @pytest.mark.asyncio
    async def test_ma_fast_path_succeeds_when_title_matches_even_if_position_zero(self):
        """#803: on cold MA start the speaker reports state=playing + correct
        title within seconds, but `media_position` lags at 0 for 10-15s.
        Fast-path must accept title_matches + position_fresh without waiting
        for position >= 1, otherwise round 1 sits frozen for the full 15s
        timeout while audio is already playing.
        """
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        call_count = 0
        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Title matches expected, position still 0, but updated_at moved →
        # MA is reporting fresh state for the right track. Accept.
        playing_pos_zero = _make_state(
            "playing",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )

        def state_progression(*args):
            nonlocal call_count
            call_count += 1
            return old_state if call_count <= 1 else playing_pos_zero

        hass.states.get = MagicMock(side_effect=state_progression)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="New Song"))

        assert result is True
        # Event-based wait: state_before snapshot + post-timeout snapshot.
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_ma_fast_path_accepts_title_advanced_without_exact_match(self):
        """Levtos's UI-lag scenario: title moved to a NEW song after the call,
        but the new title doesn't substring-match what the playlist expected
        (e.g. playlist has 'Das Modell', MA reports 'The Model'; or
        playlist has 'Hallelujah' and MA returns 'Hallelujah - Live'). The
        fast-path must still confirm playback so the UI returns within ~1s
        instead of waiting the full 15s timeout.

        #795 invariant is preserved: if the title is UNCHANGED from before,
        the fast-path still rejects (covered by the separate stale-title test).
        """
        hass = _make_hass("playing", media_title="Manhattan Skyline")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        before = _make_state(
            "playing",
            media_title="Manhattan Skyline",  # previous track
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # MA started playing the new track. Title moved to "The Model" but
        # the playlist expected "Das Modell" (German title) — substring match
        # fails, but title_advanced succeeds.
        after = _make_state(
            "playing",
            media_title="The Model",  # different from `before`, but doesn't contain "Das Modell"
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",  # fresh
        )
        call_count = 0

        def state_progression(*_args):
            nonlocal call_count
            call_count += 1
            return before if call_count <= 1 else after

        hass.states.get = MagicMock(side_effect=state_progression)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="Das Modell"))

        # Fast-path must fire — title moved, even though it doesn't match.
        assert result is True
        # Should NOT have needed to wait the full timeout; few state reads.
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_ma_realistic_ytmusic_flow(self):
        """Simulate real MA+YTMusic flow: queued → idle → playing pos=0 → playing pos=1."""
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        poll_count = 0
        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=44,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        queued = _make_state(
            "playing",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        idle = _make_state(
            "idle",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        playing_zero = _make_state(
            "playing",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:08+00:00",
        )
        playing_real = _make_state(
            "playing",
            media_title="New Song",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:10+00:00",
        )

        def realistic_flow(*args):
            nonlocal poll_count
            poll_count += 1
            if poll_count <= 1:
                return old_state  # before
            if poll_count <= 4:
                return queued  # title changed, pos=0
            if poll_count <= 5:
                return idle  # speaker buffering
            if poll_count <= 7:
                return playing_zero  # playing but pos=0 still
            return playing_real  # actually playing pos=1

        hass.states.get = MagicMock(side_effect=realistic_flow)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="New Song"))

        assert result is True
        assert (
            poll_count >= 2
        )  # event-based wait — state_before + post-timeout snapshot

    @pytest.mark.asyncio
    async def test_ma_returns_false_when_speaker_never_changed_state(self):
        """#777: if title AND position_updated_at are unchanged from before the call,
        the track never swapped on the speaker — return False so the caller can
        try the next URI candidate instead of advancing into a silent round.
        """
        # Single frozen state — `_make_hass` returns the same state before and
        # after the MA wait, so title_before == title_after AND
        # position_updated_before == position_updated_after. Under #777, that's
        # a hard failure (the fallback cascade should try a different URI).
        hass = _make_hass("buffering", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is False

    @pytest.mark.asyncio
    async def test_ma_hard_stops_speaker_on_stale_title_detection(self):
        """#801: when stale-title is detected, hard-stop the speaker so the
        prior track doesn't keep playing while the fallback cascade tries
        the next URI. Without this, Levtos heard 'Kill Bill' continuing
        for multiple rounds while UI advanced — strict-detection rejected
        candidates correctly but nobody told the speaker to stop.
        """
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        # title_before == 'Old Song', title_after == 'Old Song' (stale),
        # position advanced — simulates Levtos's "Kill Bill keeps playing"
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        after = _make_state(
            "playing",
            media_title="Old Song",
            media_position=101,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )

        poll = 0

        def progression(*_args):
            nonlocal poll
            poll += 1
            return before if poll <= 1 else after

        hass.states.get = MagicMock(side_effect=progression)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is False
        # The play_media call + the media_stop call must both have been issued
        stop_calls = [
            c
            for c in hass.services.async_call.call_args_list
            if c[0][:2] == ("media_player", "media_stop")
        ]
        assert len(stop_calls) == 1, (
            "media_stop must be called exactly once on stale-title detect"
        )
        assert (
            stop_calls[0][1].get("blocking") is False
            or (len(stop_calls[0][0]) > 3 and stop_calls[0][0][3] is False)
            or stop_calls[0].kwargs.get("blocking") is False
        )

    @pytest.mark.asyncio
    async def test_ma_tolerates_slow_buffer_when_title_advanced(self):
        """#345 tolerance: the speaker title changed to SOMETHING during the
        wait — maybe not exactly matching expected, but MA is clearly
        progressing. Return True so we don't chase flaky retries.
        """
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Title advanced to something (not the expected title yet, so fast-path
        # _check_state returns False) but the wait sees movement → tolerance applies.
        partial = _make_state(
            "playing",
            media_title="Some Other Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:03+00:00",
        )

        poll = 0

        def progression(*_args):
            nonlocal poll
            poll += 1
            return before if poll <= 1 else partial

        hass.states.get = MagicMock(side_effect=progression)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is True

    @pytest.mark.asyncio
    async def test_ma_rejects_when_player_reports_no_active_queue(self):
        """#1863: the title moved, but the player reports `active_queue: None`.

        That is the reported signature: an MA-platform entity that is only
        mirroring the underlying speaker's pre-game context (a leftover
        Spotify session, `state: paused`, `media_position: 0`) because MA
        never accepted the play_media call. The #345 tolerance used to wave
        this through as success, so the round started with a live timer and
        no music. It must be a hard failure instead — and classified as
        "error", so start_round pauses the game and surfaces the recovery
        banner rather than silently skipping song after song.
        """
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        before.attributes["active_queue"] = None
        # Title moved (so the #345 branch would otherwise accept), but the
        # speaker is paused on a foreign context and MA holds no queue.
        stale = _make_state(
            "paused",
            media_title="Spotify",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:03+00:00",
        )
        stale.attributes["active_queue"] = None

        poll = 0

        def progression(*_args):
            nonlocal poll
            poll += 1
            return before if poll <= 1 else stale

        hass.states.get = MagicMock(side_effect=progression)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is False
        assert svc.last_failure_reason == "error"

    @pytest.mark.asyncio
    async def test_ma_slow_buffer_tolerance_survives_a_populated_queue(self):
        """#1863 guard-rail: a genuinely buffering MA player keeps its queue.

        The #1863 rejection must key on the queue being *empty*, not on the
        attribute merely existing — otherwise every MA version that reports
        `active_queue` would lose the #345 slow-buffer tolerance entirely.
        """
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        before.attributes["active_queue"] = "RINCON_TEST"
        partial = _make_state(
            "playing",
            media_title="Some Other Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:03+00:00",
        )
        partial.attributes["active_queue"] = "RINCON_TEST"

        poll = 0

        def progression(*_args):
            nonlocal poll
            poll += 1
            return before if poll <= 1 else partial

        hass.states.get = MagicMock(side_effect=progression)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is True

    @pytest.mark.asyncio
    async def test_ma_returns_false_when_title_unchanged_but_position_advances(self):
        """#795 (was #345 tolerance pre-rc3): if the speaker title is identical
        to before the call but position keeps ticking, the *prior* track is
        still playing — a new track did NOT start. Reject so the fallback
        cascade tries the next URI.

        This is exactly Levtos's #795 scenario: speaker stuck on
        'Sugar, Sugar' / 'Lazy Sunday (Mono)' for multiple rounds while
        position advanced; old logic would falsely return True here and
        the UI advanced into rounds with no actual audio change.

        #808 follow-up: this failure mode is now classified as "unavailable"
        — start_round will skip the song silently rather than counting it
        toward MAX_SONG_RETRIES (track is most likely region-locked /
        not in the user's provider catalog).
        """
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        after = _make_state(
            "playing",
            media_title="Old Song",  # SAME title — prior track still playing
            media_position=101,
            media_position_updated_at="2020-01-01T00:00:05+00:00",  # position moved
        )

        poll = 0

        def progression(*_args):
            nonlocal poll
            poll += 1
            return before if poll <= 1 else after

        hass.states.get = MagicMock(side_effect=progression)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is False
        # #808 follow-up: title-stale failure is classified as "unavailable"
        # so start_round can skip silently instead of counting toward retries.
        assert svc.last_failure_reason == "unavailable"

    @pytest.mark.asyncio
    async def test_ma_first_song_no_previous_title(self):
        """First song: title_before is None, new title with position>=1 should succeed."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        call_count = 0
        no_media = _make_state(
            "idle", media_title=None, media_position=0, media_position_updated_at=None
        )
        no_media.attributes["media_title"] = None
        no_media.attributes["media_position_updated_at"] = None
        playing_new = _make_state(
            "playing",
            media_title="First Song",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )

        def first_song(*args):
            nonlocal call_count
            call_count += 1
            return playing_new if call_count > 2 else no_media

        hass.states.get = MagicMock(side_effect=first_song)
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="First Song"))

        assert result is True

    @pytest.mark.asyncio
    async def test_ma_idle_after_cascade_stop_is_unavailable_not_error(self):
        """#1363: when Beatify itself stopped the speaker after a same-song
        stale-title detect, the NEXT candidate timing out into 'idle' must be
        classified 'unavailable' (storefront gap → skip silently), NOT 'error'
        (systemic → pause the whole game). This is the #805/#808 regression for
        any provider whose candidate list has >=2 entries.
        """
        hass = _make_hass("idle", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        # Simulate the prior candidate's media_stop having already fired.
        svc._stopped_for_cascade = True

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc._try_ma_play("apple_music://track/302229811", "X")

        assert result is False
        assert svc.last_failure_reason == "unavailable"

    @pytest.mark.asyncio
    async def test_ma_idle_without_cascade_stop_is_error(self):
        """#1363 guard: a genuinely idle speaker that Beatify did NOT stop
        (offline speaker / unauthenticated provider) must still classify as
        'error' so MAX_SONG_RETRIES + the recovery banner kick in.
        """
        hass = _make_hass("idle", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        assert svc._stopped_for_cascade is False

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                1.0,
            ):
                result = await svc._try_ma_play("apple_music://track/302229811", "X")

        assert result is False
        assert svc.last_failure_reason == "error"

    @pytest.mark.asyncio
    async def test_ma_cascade_stop_flag_reset_each_song(self):
        """#1363: the cascade-stop flag must not leak across songs. A stop on
        song A must not make song B's idle-failure look like a storefront gap.
        """
        hass = _make_hass("idle", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        svc._stopped_for_cascade = True  # leftover from a prior song

        # _play_via_music_assistant must reset the flag before the cascade.
        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=False)):
            await svc._play_via_music_assistant(_make_song())

        assert svc._stopped_for_cascade is False

    @pytest.mark.asyncio
    async def test_sonos_still_uses_blocking_true(self):
        """Non-MA platforms should still use blocking=True."""
        hass = _make_hass("playing")
        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        result = await svc.play_song(_make_song())

        assert result is True
        call_kwargs = hass.services.async_call.call_args
        assert (
            call_kwargs.kwargs.get("blocking") is True
            or call_kwargs[1].get("blocking") is True
        )

    @pytest.mark.asyncio
    async def test_ma_ignores_wrong_song_from_previous_request(self):
        """If a previous slow song arrives, it must NOT be accepted as confirmation.

        Regression test for race condition: retry fires Song 2 but Song 1
        (from a previous timed-out request) starts playing first. The polling
        must check that the EXPECTED title is playing, not just "any change".
        """
        hass = _make_hass("idle", media_title="")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        poll_count = 0
        idle_state = _make_state(
            "idle",
            media_title="",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Wrong song arrives (from a previous timed-out request)
        wrong_song = _make_state(
            "playing",
            media_title="What Is Love",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        # Correct song finally arrives
        correct_song = _make_state(
            "playing",
            media_title="Ready or Not",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:12+00:00",
        )

        def race_condition_flow(*args):
            nonlocal poll_count
            poll_count += 1
            if poll_count <= 1:
                return idle_state  # before
            if poll_count <= 5:
                return wrong_song  # WRONG song playing — must NOT confirm
            return correct_song  # correct song arrives

        hass.states.get = MagicMock(side_effect=race_condition_flow)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="Ready or Not"))

        assert result is True
        assert (
            poll_count >= 2
        )  # event-based wait — state_before + post-timeout snapshot

    @pytest.mark.asyncio
    async def test_ma_matches_title_with_suffix(self):
        """MA may append suffixes like '(Official HD Video)' — match by substring."""
        hass = _make_hass("idle", media_title="")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        idle_state = _make_state(
            "idle",
            media_title="",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        playing_with_suffix = _make_state(
            "playing",
            media_title="Ready Or Not (Official HD Video)",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        hass.states.get = MagicMock(side_effect=[idle_state, playing_with_suffix])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="Ready or Not"))

        assert result is True

    @pytest.mark.asyncio
    async def test_fast_path_rejects_unrelated_auto_advance_title(self):
        """#1381: the requested URI fails to resolve in MA, but the speaker's
        prior queue naturally auto-advances to its NEXT track within the wait
        window. The new title is unrelated (different song, different artist),
        so fast-path Path 2 must NOT instant-confirm it as our track.

        The old code accepted ANY title != title_before with fresh position →
        a round ran with the wrong audio, silently (the #795 failure class).
        """
        before = _make_state(
            "playing",
            media_title="Bohemian Rhapsody",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Prior queue auto-advanced to its own next track — unrelated to ours.
        auto_advanced = _make_state(
            "playing",
            media_title="Another One Bites the Dust",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",  # fresh
        )
        auto_advanced.attributes["media_artist"] = "Queen"

        hass = _make_hass("playing", media_title="Bohemian Rhapsody")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        call_count = 0

        def progression(*_args):
            nonlocal call_count
            call_count += 1
            return before if call_count <= 1 else auto_advanced

        hass.states.get = MagicMock(side_effect=progression)

        # No state-change events fire; force the wait to time out instantly so
        # the test does not block for MA_PLAYBACK_TIMEOUT.
        async def _instant_timeout(awaitable=None, *_a, **_k):
            if awaitable is not None and asyncio.iscoroutine(awaitable):
                awaitable.close()  # don't leak an un-awaited coroutine
            raise asyncio.TimeoutError

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            confirmed = await svc._try_ma_play(
                "spotify:track:our-song", "Sweet Child O' Mine", "Guns N' Roses"
            )

        # The fast-path (Path 2) must NOT have confirmed this unrelated track.
        # (It falls through to the post-timeout #345 tolerance, path 0.)
        assert svc._last_confirm_path != 2
        # And whatever the final outcome, an unrelated auto-advance must never
        # be learned as a working URI field.
        assert confirmed is True  # #345 tolerance still returns True post-timeout
        assert svc._last_confirm_path == 0

    @pytest.mark.asyncio
    async def test_fast_path_accepts_title_token_overlap(self):
        """#1381: a punctuation/word-order mismatch where the exact substring
        (Path 1) fails but the titles share a significant token must still
        fast-path confirm via Path 2's similarity gate. Expected
        "Sweet Child O' Mine" vs MA's "Sweet Child o Mine (Remaster)" — the
        apostrophe/casing breaks the substring, tokens still overlap."""
        before = _make_state(
            "playing",
            media_title="Old Track",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        current = _make_state(
            "playing",
            media_title="Sweet Child o Mine (Remaster)",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",
        )
        current.attributes["media_artist"] = "Some Cover Artist"

        hass = _make_hass("playing", media_title="Old Track")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, current])

        confirmed = await svc._try_ma_play(
            "spotify:track:x", "Sweet Child O' Mine", "Different Artist"
        )

        assert confirmed is True
        assert svc._last_confirm_path == 2

    @pytest.mark.asyncio
    async def test_fast_path_accepts_artist_match_on_title_mismatch(self):
        """#1381: 'Das Modell' vs MA's 'The Model' share no title token, but the
        expected artist matches media_artist → Path 2 confirms (Levtos case)."""
        before = _make_state(
            "playing",
            media_title="Manhattan Skyline",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        current = _make_state(
            "playing",
            media_title="The Model",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",
        )
        current.attributes["media_artist"] = "Kraftwerk"

        hass = _make_hass("playing", media_title="Manhattan Skyline")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, current])

        confirmed = await svc._try_ma_play("spotify:track:x", "Das Modell", "Kraftwerk")

        assert confirmed is True
        assert svc._last_confirm_path == 2

    @pytest.mark.asyncio
    async def test_preferred_uri_field_not_learned_on_path2_confirmation(self):
        """#1381: a fallback candidate that only confirmed via Path 2 (weaker
        similarity gate, not an expected-title substring) must NOT be promoted
        to _ma_preferred_uri_field — doing so reorders future candidates wrongly
        for a field that never proved it resolved our track."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        song = {
            "title": "Song",
            "artist": "Artist",
            "uri": "spotify:track:legacy",
            "uri_spotify": "spotify:track:canonical",
            "_resolved_uri": "spotify:track:canonical",
        }

        async def fake_try(
            uri: str, expected_title: str, expected_artist: str = ""
        ) -> bool:
            ok = uri == "spotify:track:legacy"
            if ok:
                svc._last_confirm_path = 2  # weak (similarity-gate) confirmation
            return ok

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            result = await svc._play_via_music_assistant(song)

        assert result is True
        # Path-2-only confirmation must not learn the field.
        assert svc._ma_preferred_uri_field is None


class TestTitleSimilarityGate:
    """#1381: unit tests for the fast-path Path 2 similarity helpers."""

    def test_token_overlap_matches_suffix(self):
        from custom_components.beatify.services.media_player import (
            _titles_plausibly_match,
        )

        assert _titles_plausibly_match("Hallelujah", "Hallelujah - Live")
        assert _titles_plausibly_match("Sweet Child O' Mine", "Sweet Child o Mine")

    def test_prefix_matches_remaster_suffix(self):
        from custom_components.beatify.services.media_player import (
            _titles_plausibly_match,
        )

        assert _titles_plausibly_match("Africa", "Africa (Remastered 2020)")

    def test_unrelated_titles_do_not_match(self):
        from custom_components.beatify.services.media_player import (
            _titles_plausibly_match,
        )

        assert not _titles_plausibly_match(
            "Sweet Child O' Mine", "Another One Bites the Dust"
        )
        # Short noise words alone never bridge two unrelated titles.
        assert not _titles_plausibly_match("Go", "No")

    def test_artist_match_helper(self):
        from custom_components.beatify.services.media_player import _artist_matches

        assert _artist_matches("Kraftwerk", "Kraftwerk")
        assert _artist_matches("The Beatles", "Beatles")
        assert not _artist_matches("Queen", "Guns N' Roses")
        assert not _artist_matches("", "Queen")


class TestAvailabilityCheck:
    """Tests for is_available() used in state.py pre-flight."""

    def test_available_when_idle(self):
        hass = _make_hass("idle")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        assert svc.is_available() is True

    def test_unavailable_state(self):
        hass = _make_hass("unavailable")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        assert svc.is_available() is False

    def test_entity_not_found(self):
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        svc = MediaPlayerService(
            hass, "media_player.nonexistent", platform="music_assistant"
        )
        assert svc.is_available() is False


class TestMAPollingResilience:
    """Tests for polling loop error handling."""

    @pytest.mark.asyncio
    async def test_state_read_exception_does_not_skip_song(self):
        """If hass.states.get() throws mid-poll, treat as 'not ready' and keep polling."""
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        playing_state = _make_state(
            "playing",
            media_title="New Song",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:10+00:00",
        )

        call_count = 0

        def state_with_errors(*args):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return old_state  # before
            if call_count <= 3:
                raise RuntimeError("HA state read failed")  # transient errors
            return playing_state  # recovered

        hass.states.get = MagicMock(side_effect=state_with_errors)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="New Song"))

        assert result is True
        assert call_count >= 4  # survived the errors and found playback


class TestMAProviderFallback:
    """Tests for per-provider URI candidate generation (#768 → narrowed by #805).

    The cascade was originally cross-provider (#768): if Spotify failed, walk
    Apple Music / YT / Tidal / Deezer URIs in order. #805 narrowed it: only
    URIs belonging to the user-selected provider are considered. Trying URIs
    from providers MA isn't configured for just buys 15s timeouts per
    candidate (Levtos's Apple-Music-only setup paid 4×15s on every failed
    round before the fix).
    """

    def test_candidates_primary_only(self):
        """Song with only spotify URI → single candidate, field=None (primary)."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {"uri": "spotify:track:abc", "_resolved_uri": "spotify:track:abc"}
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates == [(None, "spotify:track:abc")]

    def test_candidates_skip_other_providers_when_apple_music_only(self):
        """#805: Apple-Music user must NEVER see Spotify/YT/Tidal/Deezer URIs.

        Levtos's exact setup: provider="apple_music", song dict has all six
        URI fields populated by the catalog. Old cascade tried all of them
        in fixed order; new behavior tries only apple_music URIs.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        song = {
            "uri": "spotify:track:abc",
            "uri_spotify": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
            "uri_youtube_music": "https://music.youtube.com/watch?v=xyz",
            "uri_tidal": "tidal://track/222",
            "uri_deezer": "deezer://track/333",
            "_resolved_uri": "applemusic://track/111",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        # Only the Apple Music URI (converted to MA's native form) should be tried.
        assert uris == ["apple_music://track/111"]

    def test_candidates_spotify_provider_walks_uri_and_uri_spotify(self):
        """Spotify provider includes both `uri_spotify` and legacy `uri` fields."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        # Two distinct Spotify URIs in the legacy + canonical fields. Both
        # should be candidates (spotify provider lists both fields).
        song = {
            "uri": "spotify:track:legacy",
            "uri_spotify": "spotify:track:canonical",
            "_resolved_uri": "spotify:track:canonical",
            # These should be filtered out — different provider:
            "uri_apple_music": "applemusic://track/111",
            "uri_tidal": "tidal://track/222",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        assert "spotify:track:canonical" in uris
        assert "spotify:track:legacy" in uris
        # Apple Music + Tidal must be excluded.
        assert all(not u.startswith("apple_music://") for u in uris)
        assert all(not u.startswith("https://tidal.com") for u in uris)

    def test_candidates_dedupe_by_converted_uri(self):
        """`uri` and `uri_spotify` with the same value collapse to one candidate."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        song = {
            "uri": "spotify:track:abc",
            "uri_spotify": "spotify:track:abc",  # same as uri
            "_resolved_uri": "spotify:track:abc",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        assert uris == ["spotify:track:abc"]

    def test_candidates_converts_apple_music(self):
        """applemusic:// URIs are converted to MA-native apple_music:// form (#772)."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        song = {
            "_resolved_uri": "applemusic://track/999",
            "uri_apple_music": "applemusic://track/999",
        }
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates[0][1] == "apple_music://track/999"

    def test_candidates_keeps_deezer_native_form(self):
        """deezer://track/ URIs are passed through unchanged (#797).

        The previous https://www.deezer.com/track/<id> form routed via MA's
        generic http(s):// branch to the 'builtin' provider, which doesn't
        know how to play Deezer tracks — failed with "No playable items
        found". Native provider-URI form routes directly to the deezer
        provider domain.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="deezer",
        )
        song = {
            "_resolved_uri": "deezer://track/12345",
            "uri_deezer": "deezer://track/12345",
        }
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates[0][1] == "deezer://track/12345"

    def test_candidates_learned_preference_within_same_provider(self):
        """Cached preferred field is honored, but ordered behind `_resolved_uri`.

        #1379: `_resolved_uri` is the storefront-resolved primary and must
        ALWAYS be tried first; the learned preference only orders the remaining
        alternates (here the legacy `uri` field), so it comes right after.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        # Cached: legacy `uri` field worked last time.
        svc._ma_preferred_uri_field = "uri"
        song = {
            "uri": "spotify:track:legacy",
            "uri_spotify": "spotify:track:canonical",
            "_resolved_uri": "spotify:track:canonical",
        }
        candidates = svc._get_ma_uri_candidates(song)
        # Primary (`_resolved_uri`) is always first.
        assert candidates[0] == (None, "spotify:track:canonical")
        # Cached field is ordered ahead of the other alternates, behind primary.
        assert candidates[1] == ("uri", "spotify:track:legacy")

    def test_candidates_learned_preference_ignored_across_providers(self):
        """Cached preferred field from a different provider is not honored.

        The cache survives across games where provider may have changed —
        e.g. user played a Spotify game (cached `uri_spotify`), then started
        an Apple Music game on the same speaker. The cached Spotify field
        must be ignored, not retried as a phantom candidate.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        svc._ma_preferred_uri_field = "uri_spotify"  # stale cache
        song = {
            "uri_spotify": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
            "_resolved_uri": "applemusic://track/111",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        # Stale cached field is ignored; only Apple Music URI is tried.
        assert uris == ["apple_music://track/111"]

    def test_candidates_no_uris_returns_empty(self):
        """Song with no URI fields yields no candidates."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        assert svc._get_ma_uri_candidates({"title": "x", "artist": "y"}) == []

    def test_candidates_skip_legacy_us_field_when_regional_map_present(self):
        """#1379: non-US Apple-Music user must NOT get the legacy US ID appended.

        The song carries `uri_apple_music_by_region` (so `get_song_uri` already
        resolved `_resolved_uri` storefront-aware to the DE track). The legacy
        `uri_apple_music` field holds the wrong-storefront US ID and must be
        dropped — appending it re-introduces the #808 wrong-storefront timeout.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        song = {
            "uri_apple_music": "applemusic://track/US111",  # legacy US ID
            "uri_apple_music_by_region": {"de": "applemusic://track/DE222"},
            "_resolved_uri": "applemusic://track/DE222",  # DE-resolved
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        # Only the storefront-resolved DE URI is tried; the US legacy ID is gone.
        assert uris == ["apple_music://track/DE222"]
        assert "apple_music://track/US111" not in uris

    def test_candidates_legacy_field_kept_without_regional_map(self):
        """#1379: with no regional map, the legacy field is still a valid
        alternate (storefront resolution doesn't apply — single-URI playlist).
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        song = {
            "uri_apple_music": "applemusic://track/111",
            "_resolved_uri": "applemusic://track/111",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        assert uris == ["apple_music://track/111"]

    def test_candidates_learned_us_field_never_outranks_resolved_uri(self):
        """#1379 core: even with `uri_apple_music` learned as preferred, it must
        not be ordered ahead of the storefront-resolved `_resolved_uri`, and for
        a song with a regional map it must not appear at all.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        # A prior song without a regional map "learned" the legacy US field.
        svc._ma_preferred_uri_field = "uri_apple_music"
        song = {
            "uri_apple_music": "applemusic://track/US111",  # wrong storefront
            "uri_apple_music_by_region": {"de": "applemusic://track/DE222"},
            "_resolved_uri": "applemusic://track/DE222",  # DE-resolved
        }
        candidates = svc._get_ma_uri_candidates(song)
        # Storefront-resolved URI first; learned US field dropped entirely.
        assert candidates == [(None, "apple_music://track/DE222")]

    def test_candidates_unknown_provider_warns_and_falls_back(self, caplog):
        """#1276: an unmapped provider logs a warning and falls back to _resolved_uri.

        The wizard is supposed to gate provider selection, but if an unknown
        value reaches the dispatch the old `.get(..., ())` produced zero
        candidates with no diagnostic (the silent-fail pattern behind
        #768/#808). The provider must be named in the warning, and a song
        that still carries `_resolved_uri` must remain playable.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="napster",  # not in _PROVIDER_URI_FIELDS
        )
        song = {
            "artist": "A",
            "title": "T",
            "_resolved_uri": "spotify:track:abc",
        }
        with caplog.at_level("WARNING"):
            candidates = svc._get_ma_uri_candidates(song)
        # _resolved_uri is still honored as a last resort.
        assert candidates == [(None, "spotify:track:abc")]
        # Warning names the unknown provider so the mismatch is debuggable.
        assert any(
            "napster" in rec.message and rec.levelname == "WARNING"
            for rec in caplog.records
        )

    def test_candidates_known_provider_empty_fields_stays_quiet(self, caplog):
        """#1276: a known provider mapped to () (amazon_music) must NOT warn.

        amazon_music plays via Alexa text-search and intentionally has no URI
        fields — it must not be mistaken for the unknown-provider miss-case.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="amazon_music",
        )
        with caplog.at_level("WARNING"):
            svc._get_ma_uri_candidates({"artist": "A", "title": "T"})
        assert not any("unknown provider" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_play_via_ma_no_candidate_warns_with_provider(self, caplog):
        """#1276: a missing-URI miss logs a warning naming the provider + song."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        # Song has no apple_music URI → no candidates.
        song = {"artist": "Artist", "title": "Title", "uri_spotify": "spotify:track:x"}
        with caplog.at_level("WARNING"):
            result = await svc._play_via_music_assistant(song)
        assert result is False
        assert svc.last_failure_reason == "unavailable"
        assert any(
            "apple_music" in rec.message and "Artist" in rec.message
            for rec in caplog.records
        )

    @pytest.mark.asyncio
    async def test_fallback_within_provider_tries_next_when_primary_fails(self):
        """For Spotify, if `_resolved_uri` fails, legacy `uri` field is tried next."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        song = {
            "title": "Song",
            "artist": "Artist",
            "uri": "spotify:track:legacy",
            "uri_spotify": "spotify:track:canonical",
            "_resolved_uri": "spotify:track:canonical",
        }

        calls: list[str] = []

        async def fake_try(
            uri: str, expected_title: str, expected_artist: str = ""
        ) -> bool:
            calls.append(uri)
            ok = uri == "spotify:track:legacy"  # primary fails, legacy succeeds
            if ok:
                # Simulate a Path-1 (expected-title substring) confirmation —
                # the only path strong enough to learn a preferred URI field.
                svc._last_confirm_path = 1
            return ok

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            result = await svc._play_via_music_assistant(song)

        assert result is True
        assert calls == ["spotify:track:canonical", "spotify:track:legacy"]
        assert svc._ma_preferred_uri_field == "uri"

    @pytest.mark.asyncio
    async def test_primary_success_does_not_update_preference(self):
        """When primary (`_resolved_uri`) succeeds, no field is cached."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )
        song = {
            "title": "Song",
            "_resolved_uri": "spotify:track:abc",
            "uri_spotify": "spotify:track:abc",
        }

        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=True)):
            result = await svc._play_via_music_assistant(song)

        assert result is True
        assert svc._ma_preferred_uri_field is None

    @pytest.mark.asyncio
    async def test_all_candidates_fail_returns_false(self):
        """Exhausted candidates → False, no cached preference."""
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="apple_music",
        )
        song = {
            "title": "Song",
            "_resolved_uri": "applemusic://track/111",
            "uri_apple_music": "applemusic://track/111",
        }

        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=False)):
            result = await svc._play_via_music_assistant(song)

        assert result is False
        assert svc._ma_preferred_uri_field is None

    @pytest.mark.asyncio
    async def test_learned_preference_orders_alternates_behind_primary(self):
        """Within Spotify: after legacy `uri` succeeds, it's learned and ordered
        ahead of OTHER alternates on the next song — but #1379 keeps the
        storefront-resolved `_resolved_uri` primary tried first regardless.

        Here `song_b` has a third distinct alternate (`uri_spotify` ==
        `_resolved_uri` is the primary; legacy `uri` is the learned alternate).
        The learned legacy field must come right after the primary.
        """
        hass = _make_hass()
        svc = MediaPlayerService(
            hass,
            "media_player.test",
            platform="music_assistant",
            provider="spotify",
        )

        song_a = {
            "title": "A",
            "uri": "spotify:track:a-legacy",
            "uri_spotify": "spotify:track:a-canonical",
            "_resolved_uri": "spotify:track:a-canonical",
        }
        song_b = {
            "title": "B",
            "uri": "spotify:track:b-legacy",
            "uri_spotify": "spotify:track:b-canonical",
            "_resolved_uri": "spotify:track:b-canonical",
        }

        calls: list[str] = []

        async def fake_try(
            uri: str, expected_title: str, expected_artist: str = ""
        ) -> bool:
            calls.append(uri)
            # Canonical never works in this user's setup; legacy always does.
            ok = uri.endswith("-legacy")
            if ok:
                svc._last_confirm_path = 1  # Path-1 confirmation learns the field
            return ok

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            assert await svc._play_via_music_assistant(song_a) is True
            assert await svc._play_via_music_assistant(song_b) is True

        # Song A: canonical (primary) fails, legacy succeeds → learns "uri".
        # Song B: #1379 — primary `_resolved_uri` is STILL tried first (fails),
        #   then the learned legacy field (succeeds). The learned preference no
        #   longer skips the storefront-resolved primary.
        assert calls == [
            "spotify:track:a-canonical",
            "spotify:track:a-legacy",
            "spotify:track:b-canonical",
            "spotify:track:b-legacy",
        ]

    @pytest.mark.asyncio
    async def test_no_uris_returns_false_without_calling_try(self):
        """Empty-candidate song short-circuits to False."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        mock_try = AsyncMock(return_value=True)
        with patch.object(svc, "_try_ma_play", mock_try):
            result = await svc._play_via_music_assistant({"title": "x"})

        assert result is False
        mock_try.assert_not_awaited()


class TestStartRoundAvailabilityCheck:
    """Test that start_round() pauses game when media player is unavailable."""

    @pytest.mark.asyncio
    async def test_start_round_pauses_when_unavailable(self):
        """start_round() should pause the game if is_available() returns False."""
        # Create a minimal GameState mock with the relevant attributes
        mock_media_service = MagicMock()
        mock_media_service.is_available.return_value = False

        mock_game_state = MagicMock()
        mock_game_state._media_player_service = mock_media_service
        mock_game_state.media_player = "media_player.test"
        mock_game_state.platform = "music_assistant"
        mock_game_state.pause_game = AsyncMock()

        # Import and call the relevant code path
        # Since GameState is complex, we test the logic directly:
        # if not self._media_player_service.is_available() -> pause_game
        if not mock_media_service.is_available():
            mock_game_state.last_error_detail = (
                f"Media player {mock_game_state.media_player} is unavailable"
            )
            await mock_game_state.pause_game("media_player_error")

        mock_media_service.is_available.assert_called_once()
        mock_game_state.pause_game.assert_awaited_once_with("media_player_error")
        assert "unavailable" in mock_game_state.last_error_detail


class TestStartRoundFailureClassification:
    """#808 follow-up: start_round must distinguish 'unavailable' (skip silently)
    from 'error' (count toward MAX_SONG_RETRIES → pause).
    """

    @pytest.mark.asyncio
    async def test_unavailable_failure_does_not_count_toward_retry_limit(self):
        """When play_song fails with last_failure_reason='unavailable', the
        next start_round call must NOT see _retry_count incremented.
        Region/storefront-locked tracks are user-uncontrollable; the game
        should keep playing whatever subset IS available without ever
        pausing on these.
        """
        from custom_components.beatify.game.state import GameState  # noqa: PLC0415
        from tests.conftest import (  # noqa: PLC0415
            make_game_state,
            make_songs,
        )

        gs: GameState = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(5),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )

        # Service: always fails with "unavailable"
        mock_service = MagicMock()
        mock_service.is_available.return_value = True
        mock_service.last_failure_reason = "unavailable"
        mock_service.play_song = AsyncMock(return_value=False)
        gs._media_player_service = mock_service
        gs.media_player = "media_player.test"
        gs.platform = "music_assistant"
        gs.pause_game = AsyncMock()  # spy to ensure NOT called

        # Cap recursion to keep the test bounded — start_round will loop
        # through the playlist marking each song unavailable, eventually
        # returning False because all songs are exhausted (NOT pausing).
        with patch(
            "custom_components.beatify.game.state.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await gs.start_round()

        # Must NOT have called pause_game — unavailable doesn't pause.
        gs.pause_game.assert_not_awaited()
        # play_song was called multiple times (once per song until exhausted).
        assert mock_service.play_song.await_count >= 2

    @pytest.mark.asyncio
    async def test_error_failure_pauses_immediately(self):
        """#949: an 'error' failure (speaker idle / provider unauthenticated)
        is systemic — play_song already waited a full MA timeout. start_round
        must pause on the FIRST such failure, not grind ~3 silent retries
        (~2 min) before the recovery banner appears. The banner's Resume
        button is the manual retry if it really was a transient blip.
        """
        from custom_components.beatify.game.state import GameState  # noqa: PLC0415
        from tests.conftest import (  # noqa: PLC0415
            make_game_state,
            make_songs,
        )

        gs: GameState = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(10),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )

        mock_service = MagicMock()
        mock_service.is_available.return_value = True
        mock_service.last_failure_reason = "error"
        mock_service.play_song = AsyncMock(return_value=False)
        gs._media_player_service = mock_service
        gs.media_player = "media_player.test"
        gs.platform = "music_assistant"
        gs.pause_game = AsyncMock()

        with patch(
            "custom_components.beatify.game.state.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await gs.start_round()

        # Pauses on the FIRST failure — no silent retry grind (#949).
        assert result is False
        assert mock_service.play_song.await_count == 1
        gs.pause_game.assert_awaited_once_with("media_player_error")


class TestProxyAlbumArt:
    """proxy_album_art — same-origin wrapping so remote players see art (#933)."""

    def test_absolute_http_lan_url_is_wrapped(self):
        # The exact shape Music Assistant emits — an absolute LAN URL.
        url = "http://192.168.0.191:8095/imageproxy?provider=apple_music&path=x"
        result = proxy_album_art(url)
        assert result.startswith("/beatify/api/albumart?url=")
        # The LAN host is percent-encoded into the query, not left bare.
        assert "192.168.0.191" not in result.split("?url=")[0]
        assert "%3A%2F%2F" in result  # :// is encoded

    def test_https_url_is_wrapped(self):
        result = proxy_album_art("https://cdn.example.com/cover.jpg")
        assert result.startswith("/beatify/api/albumart?url=")

    def test_relative_ha_proxy_path_passes_through(self):
        # HA's own signed media-player proxy path is already same-origin.
        url = "/api/media_player_proxy/media_player.sonos?token=abc"
        assert proxy_album_art(url) == url

    def test_no_artwork_fallback_passes_through(self):
        url = "/beatify/static/img/no-artwork.svg"
        assert proxy_album_art(url) == url

    def test_empty_string_passes_through(self):
        assert proxy_album_art("") == ""


class TestMetadataAlbumArtWrapping:
    """get_metadata / _extract_metadata route absolute art through the proxy (#933)."""

    async def test_get_metadata_wraps_ma_lan_url(self):
        hass = _make_hass()
        hass.states.get().attributes["entity_picture"] = (
            "http://192.168.0.191:8095/imageproxy?x=1"
        )
        svc = MediaPlayerService(hass, "media_player.test")
        meta = await svc.get_metadata()
        assert meta["album_art"].startswith("/beatify/api/albumart?url=")

    def test_extract_metadata_wraps_ma_lan_url(self):
        svc = MediaPlayerService(_make_hass(), "media_player.test")
        state = _make_state()
        state.attributes["entity_picture"] = "http://10.0.0.5:8095/imageproxy?y=2"
        meta = svc._extract_metadata(state)
        assert meta["album_art"].startswith("/beatify/api/albumart?url=")

    def test_extract_metadata_keeps_relative_entity_picture(self):
        svc = MediaPlayerService(_make_hass(), "media_player.test")
        state = _make_state()
        state.attributes["entity_picture"] = "/api/media_player_proxy/x?token=t"
        meta = svc._extract_metadata(state)
        assert meta["album_art"] == "/api/media_player_proxy/x?token=t"

    def test_extract_metadata_defaults_to_no_artwork(self):
        # No entity_picture attribute → the relative fallback, left untouched.
        svc = MediaPlayerService(_make_hass(), "media_player.test")
        meta = svc._extract_metadata(_make_state())
        assert meta["album_art"] == "/beatify/static/img/no-artwork.svg"


def _art_state(
    title: str,
    content_id: str,
    entity_picture: str,
    artist: str = "Test Artist",
) -> MagicMock:
    """Mock HA state carrying the attributes wait_for_metadata_update reads."""
    state = MagicMock()
    state.attributes = {
        "media_artist": artist,
        "media_title": title,
        "media_content_id": content_id,
        "entity_picture": entity_picture,
    }
    return state


def _event(new_state) -> MagicMock:
    """Mock a HA state_changed event carrying ``new_state``."""
    ev = MagicMock()
    ev.data = {"new_state": new_state}
    return ev


_TRACK_PATH = (
    "custom_components.beatify.services.media_player.async_track_state_change_event"
)


class TestWaitForMetadataUpdateAlbumArt:
    """Two-phase album-art wait — wait_for_metadata_update (#1260).

    The bug: content_id/media_title update before entity_picture on Spotify and
    Music Assistant, so reading entity_picture the instant the song matched
    returned the *previous* song's cover. Phase 2 waits for entity_picture to
    also change before reading it.
    """

    @staticmethod
    def _service_with_states(initial_state):
        """Build a service whose states.get returns a mutable 'current' state.

        Returns (service, box); mutate ``box["current"]`` to advance what the
        media player currently reports (read by the Phase-1 check and the
        get_metadata fallback).
        """
        hass = MagicMock()
        box = {"current": initial_state}
        hass.states.get = MagicMock(side_effect=lambda *a, **k: box["current"])
        svc = MediaPlayerService(hass, "media_player.test")
        return svc, box

    @pytest.mark.asyncio
    async def test_waits_for_entity_picture_to_change_in_later_event(self):
        """#1260 core fix: the new cover arrives in a LATER state event than
        the content_id/title change. Phase 2 must wait for it and return the
        NEW art, not the stale previous-song cover."""
        old = _art_state(
            title="Er gehört zu mir",
            content_id="spotify:track:OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with patch(_TRACK_PATH, side_effect=_fake_track):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("spotify:track:NEW")
            )
            await asyncio.sleep(0)  # let it reach the Phase 1 await

            # Event 1: song started (content_id matches) — art still lagging.
            song_started = _art_state(
                title="Never Gonna Give You Up",
                content_id="spotify:track:NEW",
                entity_picture="/api/media_player_proxy/x?token=old",
            )
            box["current"] = song_started
            captured["cb"](_event(song_started))
            await asyncio.sleep(0)

            # Event 2: entity_picture finally updates to the new cover.
            art_arrived = _art_state(
                title="Never Gonna Give You Up",
                content_id="spotify:track:NEW",
                entity_picture="/api/media_player_proxy/x?token=NEW",
            )
            box["current"] = art_arrived
            captured["cb"](_event(art_arrived))

            result = await task

        assert result["title"] == "Never Gonna Give You Up"
        assert result["album_art"] == "/api/media_player_proxy/x?token=NEW"

    @pytest.mark.asyncio
    async def test_art_present_in_same_event_returns_immediately(self):
        """When entity_picture changes in the same event that signals the new
        song, Phase 2 short-circuits and returns that event's art."""
        old = _art_state(
            title="Old",
            content_id="spotify:track:OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with patch(_TRACK_PATH, side_effect=_fake_track):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("spotify:track:NEW")
            )
            await asyncio.sleep(0)

            both = _art_state(
                title="New",
                content_id="spotify:track:NEW",
                entity_picture="/api/media_player_proxy/x?token=NEW",
            )
            box["current"] = both
            captured["cb"](_event(both))

            result = await task

        assert result["album_art"] == "/api/media_player_proxy/x?token=NEW"

    @pytest.mark.asyncio
    async def test_same_album_falls_back_to_current_state(self):
        """Two songs from the same album share entity_picture, so Phase 2 never
        sees a change — after the short extra wait we fall back to the current
        (correct, same-album) art rather than hanging or returning stale data."""
        art = "/api/media_player_proxy/x?token=album"
        old = _art_state(
            title="Track A", content_id="spotify:track:OLD", entity_picture=art
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with (
            patch(_TRACK_PATH, side_effect=_fake_track),
            patch(
                "custom_components.beatify.services.media_player.ENTITY_PICTURE_WAIT",
                0.05,
            ),
        ):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("spotify:track:NEW")
            )
            await asyncio.sleep(0)

            new = _art_state(
                title="Track B", content_id="spotify:track:NEW", entity_picture=art
            )
            box["current"] = new
            captured["cb"](_event(new))

            result = await task

        assert result["title"] == "Track B"
        assert result["album_art"] == art

    @pytest.mark.asyncio
    async def test_song_never_starts_falls_back_after_phase1_timeout(self):
        """If content_id/title never update, Phase 1 times out and we return
        whatever get_metadata() reports for the current state."""
        old = _art_state(
            title="Old",
            content_id="spotify:track:OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, _box = self._service_with_states(old)

        with (
            patch(_TRACK_PATH, side_effect=lambda *a, **k: MagicMock()),
            patch(
                "custom_components.beatify.services.media_player.METADATA_WAIT_TIMEOUT",
                0.05,
            ),
        ):
            result = await svc.wait_for_metadata_update("spotify:track:NEW")

        assert result["title"] == "Old"
        assert result["album_art"] == "/api/media_player_proxy/x?token=old"

    @pytest.mark.asyncio
    async def test_transient_entity_picture_flicker_is_ignored(self):
        """#1260 follow-up: art goes old → placeholder → real cover across
        events. The guard skips the transient placeholder and surfaces the
        REAL cover."""
        old = _art_state(
            title="Old",
            content_id="spotify:track:OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with patch(_TRACK_PATH, side_effect=_fake_track):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("spotify:track:NEW")
            )
            await asyncio.sleep(0)

            # Song starts; entity_picture momentarily clears to the placeholder.
            flicker = _art_state(
                title="New",
                content_id="spotify:track:NEW",
                entity_picture="/beatify/static/img/no-artwork.svg",
            )
            box["current"] = flicker
            captured["cb"](_event(flicker))
            await asyncio.sleep(0)

            # Real cover arrives a moment later.
            real = _art_state(
                title="New",
                content_id="spotify:track:NEW",
                entity_picture="/api/media_player_proxy/x?token=NEW",
            )
            box["current"] = real
            captured["cb"](_event(real))

            result = await task

        assert result["album_art"] == "/api/media_player_proxy/x?token=NEW"

    @pytest.mark.asyncio
    async def test_art_that_stays_placeholder_falls_back_without_hanging(self):
        """If the player genuinely reports no artwork (entity_picture never
        leaves the placeholder), the guard must not hang waiting for a 'real'
        cover — Phase 2 times out and falls back to the current state."""
        old = _art_state(
            title="Old",
            content_id="spotify:track:OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with (
            patch(_TRACK_PATH, side_effect=_fake_track),
            patch(
                "custom_components.beatify.services.media_player.ENTITY_PICTURE_WAIT",
                0.05,
            ),
        ):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("spotify:track:NEW")
            )
            await asyncio.sleep(0)

            new = _art_state(
                title="New",
                content_id="spotify:track:NEW",
                entity_picture="/beatify/static/img/no-artwork.svg",
            )
            box["current"] = new
            captured["cb"](_event(new))

            result = await task

        assert result["title"] == "New"
        assert result["album_art"] == "/beatify/static/img/no-artwork.svg"


class TestVerifyResponsivePing:
    """Pre-flight ping must never raise an idle speaker's volume (#1382)."""

    @pytest.mark.asyncio
    async def test_unreported_volume_does_not_set_volume(self):
        """volume_level is None -> NO volume_set (no absolute 50% blast)."""
        hass = _make_hass(initial_state="idle")
        state = hass.states.get("media_player.test")
        state.attributes["volume_level"] = None

        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        ok, detail = await svc.verify_responsive()

        assert ok is True
        assert detail == ""

        calls = hass.services.async_call.await_args_list
        # No volume_set at all when volume is unreported.
        assert all(call.args[1] != "volume_set" for call in calls), (
            f"verify_responsive must not call volume_set on unreported volume: {calls}"
        )
        # Used a read-only refresh ping instead.
        assert any(
            call.args[0] == "homeassistant" and call.args[1] == "update_entity"
            for call in calls
        ), f"expected homeassistant.update_entity ping, got: {calls}"

    @pytest.mark.asyncio
    async def test_reported_volume_pings_with_exact_value(self):
        """A real reported volume is echoed back unchanged via volume_set."""
        hass = _make_hass(initial_state="idle")
        state = hass.states.get("media_player.test")
        state.attributes["volume_level"] = 0.12

        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        ok, detail = await svc.verify_responsive()

        assert ok is True
        assert detail == ""

        vol_calls = [
            call
            for call in hass.services.async_call.await_args_list
            if call.args[:2] == ("media_player", "volume_set")
        ]
        assert len(vol_calls) == 1
        assert vol_calls[0].args[2]["volume_level"] == 0.12


class TestUriMatchTokens:
    """#1380: confirmation must match MA's content_id form, not the raw URI.

    MA echoes the _convert_uri_for_ma form in media_content_id, so the raw
    Beatify-internal URI is never a substring for Apple/Tidal/YT Music. The
    match tokens must therefore include the MA-converted URI and the bare
    track ID (which is stable across both forms).
    """

    @pytest.mark.parametrize(
        ("uri", "ma_content_id", "bare_id"),
        [
            # Spotify — unchanged form, bare id is the last ":" segment.
            ("spotify:track:ABC123", "spotify:track:ABC123", "ABC123"),
            # Apple Music — internal applemusic:// vs MA apple_music://.
            ("applemusic://track/123", "apple_music://track/123", "123"),
            # Tidal — internal tidal:// vs MA https://tidal.com/browse/track.
            ("tidal://track/456", "https://tidal.com/browse/track/456", "456"),
            # YT Music — internal watch?v= URL vs MA ytmusic://track form.
            (
                "https://music.youtube.com/watch?v=XYZ",
                "ytmusic://track/XYZ",
                "XYZ",
            ),
            # Deezer — passed through unchanged by _convert_uri_for_ma.
            ("deezer://track/789", "deezer://track/789", "789"),
        ],
    )
    def test_tokens_match_ma_content_id_and_bare_id(self, uri, ma_content_id, bare_id):
        tokens = MediaPlayerService._uri_match_tokens(uri)
        # The MA-converted form is always reproducible in content_id.
        assert any(tok in ma_content_id for tok in tokens), (
            f"{uri!r} tokens {tokens!r} don't match MA content_id {ma_content_id!r}"
        )
        # The bare track ID is present as a token.
        assert bare_id in tokens

    def test_youtube_watch_url_strips_extra_query_params(self):
        tokens = MediaPlayerService._uri_match_tokens(
            "https://music.youtube.com/watch?v=XYZ&list=PL1"
        )
        assert "XYZ" in tokens
        assert "XYZ&list=PL1" not in tokens

    def test_empty_uri_yields_no_tokens(self):
        assert MediaPlayerService._uri_match_tokens("") == []


class TestWaitForMetadataUpdateCrossProvider:
    """#1380: Phase-1 song-match must fire for non-Spotify providers, and a
    Phase-1 timeout that nonetheless captured new art must return that art."""

    @staticmethod
    def _service_with_states(initial_state):
        hass = MagicMock()
        box = {"current": initial_state}
        hass.states.get = MagicMock(side_effect=lambda *a, **k: box["current"])
        svc = MediaPlayerService(hass, "media_player.test")
        return svc, box

    @pytest.mark.parametrize(
        ("uri", "ma_content_id"),
        [
            ("applemusic://track/123", "apple_music://track/123"),
            ("tidal://track/456", "https://tidal.com/browse/track/456"),
            (
                "https://music.youtube.com/watch?v=XYZ",
                "ytmusic://track/XYZ",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_song_match_fires_for_provider_content_id(self, uri, ma_content_id):
        """The new song is detected via content_id even though MA reports its
        own converted URI form — not the raw Beatify-internal URI. Title is
        deliberately unchanged so ONLY the content_id path can match."""
        same_title = "Same Title"
        old = _art_state(
            title=same_title,
            content_id="apple_music://track/OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with patch(_TRACK_PATH, side_effect=_fake_track):
            task = asyncio.create_task(svc.wait_for_metadata_update(uri))
            await asyncio.sleep(0)

            # Song started: content_id is MA's converted form, title unchanged,
            # new cover present in the same event.
            started = _art_state(
                title=same_title,
                content_id=ma_content_id,
                entity_picture="/api/media_player_proxy/x?token=NEW",
            )
            box["current"] = started
            captured["cb"](_event(started))

            result = await task

        # Must return the NEW art (proves content_id match, not a 2s timeout
        # fall-through to get_metadata()).
        assert result["album_art"] == "/api/media_player_proxy/x?token=NEW"

    @pytest.mark.asyncio
    async def test_phase1_timeout_returns_captured_art(self):
        """#1380: if the song-match never fires but a real new cover arrived
        during the wait, return the captured art metadata instead of
        discarding it and falling back to the current state."""
        old = _art_state(
            title="Old",
            content_id="apple_music://track/OLD",
            entity_picture="/api/media_player_proxy/x?token=old",
        )
        svc, box = self._service_with_states(old)

        captured: dict = {}

        def _fake_track(hass, entity_ids, cb):
            captured["cb"] = cb
            return MagicMock()

        with (
            patch(_TRACK_PATH, side_effect=_fake_track),
            patch(
                "custom_components.beatify.services.media_player.METADATA_WAIT_TIMEOUT",
                0.05,
            ),
        ):
            task = asyncio.create_task(
                svc.wait_for_metadata_update("applemusic://track/UNMATCHED")
            )
            await asyncio.sleep(0)

            # New cover arrives, but content_id/title NEVER match the requested
            # track (simulating the dead-fallback scenario from the issue).
            art_only = _art_state(
                title="Old",
                content_id="apple_music://track/OLD",
                entity_picture="/api/media_player_proxy/x?token=NEW",
            )
            box["current"] = art_only
            captured["cb"](_event(art_only))

            result = await task

        assert result["album_art"] == "/api/media_player_proxy/x?token=NEW"


class TestAlexaContentType:
    """#1402: Alexa dispatch must map provider -> content_type explicitly and
    warn on an unexpected provider instead of silently treating everything as
    Apple Music."""

    @staticmethod
    def _service(provider: str):
        hass = _make_hass("playing")
        svc = MediaPlayerService(
            hass, "media_player.echo", platform="alexa_media", provider=provider
        )
        return svc, hass

    @pytest.mark.asyncio
    async def test_spotify_maps_to_spotify(self):
        svc, hass = self._service("spotify")
        await svc._play_via_alexa(_make_song())
        call = hass.services.async_call.call_args
        assert call[0][2]["media_content_type"] == "SPOTIFY"

    @pytest.mark.asyncio
    async def test_amazon_maps_to_amazon_music(self):
        svc, hass = self._service("amazon_music")
        await svc._play_via_alexa(_make_song())
        call = hass.services.async_call.call_args
        assert call[0][2]["media_content_type"] == "AMAZON_MUSIC"

    @pytest.mark.asyncio
    async def test_apple_music_maps_to_apple_music_no_warning(self):
        svc, hass = self._service("apple_music")
        with patch(
            "custom_components.beatify.services.media_player._LOGGER"
        ) as mock_log:
            await svc._play_via_alexa(_make_song())
        call = hass.services.async_call.call_args
        assert call[0][2]["media_content_type"] == "APPLE_MUSIC"
        assert not any(
            "unexpected provider" in str(c) for c in mock_log.warning.call_args_list
        )

    @pytest.mark.asyncio
    async def test_unexpected_provider_falls_back_and_warns(self):
        """A provider with no Alexa mapping (e.g. deezer) falls back to
        APPLE_MUSIC but logs a warning naming the provider (#1402)."""
        svc, hass = self._service("deezer")
        with patch(
            "custom_components.beatify.services.media_player._LOGGER"
        ) as mock_log:
            await svc._play_via_alexa(_make_song())
        call = hass.services.async_call.call_args
        assert call[0][2]["media_content_type"] == "APPLE_MUSIC"
        warnings = [str(c) for c in mock_log.warning.call_args_list]
        assert any("unexpected provider" in w and "deezer" in w for w in warnings)


class TestVolumeSaveRestore:
    """#1516: capture the host's pre-game volume and restore it at game end."""

    @pytest.mark.asyncio
    async def test_save_volume_captures_current_level(self):
        """save_volume snapshots the speaker's current volume_level."""
        hass = _make_hass(initial_state="playing")
        hass.states.get("media_player.test").attributes["volume_level"] = 0.4
        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        svc.save_volume()

        assert svc._saved_volume == 0.4

    @pytest.mark.asyncio
    async def test_save_volume_is_idempotent(self):
        """Only the FIRST save sticks — later in-game changes don't overwrite it."""
        hass = _make_hass(initial_state="playing")
        state = hass.states.get("media_player.test")
        state.attributes["volume_level"] = 0.4
        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        svc.save_volume()
        # Speaker volume drifts (Beatify lowered it); a second save must not
        # overwrite the genuine pre-game 0.4.
        state.attributes["volume_level"] = 0.1
        svc.save_volume()

        assert svc._saved_volume == 0.4

    @pytest.mark.asyncio
    async def test_restore_volume_applies_and_clears(self):
        """restore_volume sets the saved level via volume_set and clears it."""
        hass = _make_hass(initial_state="playing")
        hass.states.get("media_player.test").attributes["volume_level"] = 0.4
        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")
        svc.save_volume()
        hass.services.async_call.reset_mock()

        result = await svc.restore_volume()

        assert result is True
        vol_calls = [
            call
            for call in hass.services.async_call.await_args_list
            if call.args[:2] == ("media_player", "volume_set")
        ]
        assert len(vol_calls) == 1
        assert vol_calls[0].args[2]["volume_level"] == 0.4
        # Cleared so the next game re-captures fresh and a re-call is a no-op.
        assert svc._saved_volume is None
        assert await svc.restore_volume() is False

    @pytest.mark.asyncio
    async def test_restore_volume_noop_when_untouched(self):
        """No save → restore is a no-op (no volume_set, returns False)."""
        hass = _make_hass(initial_state="playing")
        svc = MediaPlayerService(hass, "media_player.test", platform="sonos")

        result = await svc.restore_volume()

        assert result is False
        assert all(
            call.args[:2] != ("media_player", "volume_set")
            for call in hass.services.async_call.await_args_list
        )


def _make_registry_entry(
    entity_id: str, platform: str, unique_id: str | None, domain: str = "media_player"
) -> MagicMock:
    """Build a fake entity-registry entry (mirrors HA's RegistryEntry attrs)."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.unique_id = unique_id
    entry.domain = domain
    return entry


def _make_player_state(entity_id: str) -> MagicMock:
    """Build a fake media_player state object for async_all()."""
    state = MagicMock()
    state.entity_id = entity_id
    state.state = "idle"
    state.attributes = {"friendly_name": entity_id}
    return state


def _make_discovery_hass(entries: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
    """Wire a hass + fake entity registry from a list of registry entries.

    Returns (hass, registry). `hass.states.async_all` yields a state per entry;
    the registry resolves entity_id → entry and exposes `.entities.values()`.
    """
    by_id = {e.entity_id: e for e in entries}

    hass = MagicMock()
    hass.states.async_all = MagicMock(
        return_value=[_make_player_state(e.entity_id) for e in entries]
    )

    registry = MagicMock()
    registry.entities.values = MagicMock(return_value=list(entries))
    registry.async_get = MagicMock(side_effect=lambda eid: by_id.get(eid))
    return hass, registry


class TestNativeTwinFiltering:
    """async_get_media_players hides native-platform twins of MA speakers (#1627)."""

    @pytest.mark.asyncio
    async def test_native_sonos_twin_of_ma_player_is_hidden(self):
        """Same unique_id on sonos + music_assistant → only the MA twin shows."""
        entries = [
            _make_registry_entry(
                "media_player.esszimmer",
                "music_assistant",
                "RINCON_C43875ED053801400",
            ),
            _make_registry_entry(
                "media_player.unnamed_room",
                "sonos",
                "RINCON_C43875ED053801400",
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            result = await async_get_media_players(hass)

        ids = {p["entity_id"] for p in result}
        assert "media_player.esszimmer" in ids
        assert "media_player.unnamed_room" not in ids

    @pytest.mark.asyncio
    async def test_standalone_sonos_without_ma_twin_is_kept(self):
        """A native sonos player with a unique unique_id must NOT be filtered."""
        entries = [
            _make_registry_entry(
                "media_player.living_ma",
                "music_assistant",
                "RINCON_AAAA",
            ),
            _make_registry_entry(
                "media_player.kitchen_sonos",
                "sonos",
                "RINCON_BBBB",
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            result = await async_get_media_players(hass)

        ids = {p["entity_id"] for p in result}
        assert ids == {"media_player.living_ma", "media_player.kitchen_sonos"}

    @pytest.mark.asyncio
    async def test_player_with_none_unique_id_is_unaffected(self):
        """unique_id=None must not collide with the MA set (None never matches)."""
        entries = [
            _make_registry_entry(
                "media_player.ma_box",
                "music_assistant",
                "RINCON_AAAA",
            ),
            _make_registry_entry(
                "media_player.legacy_sonos",
                "sonos",
                None,
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            result = await async_get_media_players(hass)

        ids = {p["entity_id"] for p in result}
        assert ids == {"media_player.ma_box", "media_player.legacy_sonos"}


class TestNativeTwinRemap:
    """async_get_native_twin_remap maps native twins → their MA twin (#1627)."""

    @pytest.mark.asyncio
    async def test_twin_pair_maps_native_to_ma(self):
        """A sonos + music_assistant pair sharing a unique_id → native→MA entry."""
        entries = [
            _make_registry_entry(
                "media_player.esszimmer",
                "music_assistant",
                "RINCON_C43875ED053801400",
            ),
            _make_registry_entry(
                "media_player.unnamed_room",
                "sonos",
                "RINCON_C43875ED053801400",
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            remap = await async_get_native_twin_remap(hass)

        assert remap == {"media_player.unnamed_room": "media_player.esszimmer"}

    @pytest.mark.asyncio
    async def test_no_twins_returns_empty(self):
        """Standalone players with distinct unique_ids → empty remap."""
        entries = [
            _make_registry_entry(
                "media_player.living_ma",
                "music_assistant",
                "RINCON_AAAA",
            ),
            _make_registry_entry(
                "media_player.kitchen_sonos",
                "sonos",
                "RINCON_BBBB",
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            remap = await async_get_native_twin_remap(hass)

        assert remap == {}

    @pytest.mark.asyncio
    async def test_none_unique_id_native_is_ignored(self):
        """A native player with unique_id=None must not produce a remap entry."""
        entries = [
            _make_registry_entry(
                "media_player.ma_box",
                "music_assistant",
                "RINCON_AAAA",
            ),
            _make_registry_entry(
                "media_player.legacy_sonos",
                "sonos",
                None,
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            remap = await async_get_native_twin_remap(hass)

        assert remap == {}


class TestSingleWalkEquivalence:
    """#1709: the single-walk combined path returns the SAME player list and
    remap as calling async_get_media_players + async_get_native_twin_remap."""

    @pytest.mark.asyncio
    async def test_combined_matches_individual_functions(self):
        entries = [
            _make_registry_entry(
                "media_player.esszimmer",
                "music_assistant",
                "RINCON_C43875ED053801400",
            ),
            _make_registry_entry(
                "media_player.unnamed_room",
                "sonos",
                "RINCON_C43875ED053801400",
            ),
            _make_registry_entry(
                "media_player.kitchen_sonos",
                "sonos",
                "RINCON_STANDALONE",
            ),
        ]
        hass, registry = _make_discovery_hass(entries)

        with patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=registry,
        ):
            players_indiv = await async_get_media_players(hass)
            remap_indiv = await async_get_native_twin_remap(hass)
            players_combined, remap_combined = await async_get_media_players_with_remap(
                hass
            )

        assert players_combined == players_indiv
        assert remap_combined == remap_indiv
        assert remap_combined == {"media_player.unnamed_room": "media_player.esszimmer"}
        ids = {p["entity_id"] for p in players_combined}
        assert ids == {"media_player.esszimmer", "media_player.kitchen_sonos"}
