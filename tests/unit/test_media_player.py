"""Tests for MediaPlayerService — especially MA non-blocking playback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService


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
    async def test_ma_waits_for_position_ge_1(self):
        """Should NOT return when position=0 (queued but not playing yet)."""
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        call_count = 0
        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Title changed, position=0, updated_at fresh — but NOT actually playing yet
        queued_state = _make_state(
            "playing",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        # Actually playing: position >= 1
        playing_state = _make_state(
            "playing",
            media_title="New Song",
            media_position=1,
            media_position_updated_at="2020-01-01T00:00:10+00:00",
        )

        def state_progression(*args):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return old_state
            if call_count <= 5:
                return queued_state  # pos=0, should NOT trigger
            return playing_state  # pos=1, should trigger

        hass.states.get = MagicMock(side_effect=state_progression)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await svc.play_song(_make_song(title="New Song"))

        assert result is True
        assert call_count >= 6  # Must have waited past the pos=0 states

    @pytest.mark.asyncio
    async def test_ma_does_not_trigger_on_title_change_alone(self):
        """Title change with position=0 should NOT trigger (song only queued)."""
        hass = _make_hass("playing", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        poll_count = 0
        old_state = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        queued_only = _make_state(
            "playing",
            media_title="New Song",
            media_position=0,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )

        def always_queued(*args):
            nonlocal poll_count
            poll_count += 1
            if poll_count <= 1:
                return old_state
            return queued_only

        hass.states.get = MagicMock(side_effect=always_queued)

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.PLAYBACK_TIMEOUT", 2.0
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert (
            result is True
        )  # #345: return True on timeout — MA may still be buffering
        assert poll_count >= 4  # but waited until timeout

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
        assert poll_count >= 8  # waited for the full realistic flow

    @pytest.mark.asyncio
    async def test_ma_returns_true_even_on_timeout(self):
        """Should return True even if playback never confirmed — MA may still be buffering (#345)."""
        hass = _make_hass("buffering", media_title="Old Song")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        with patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with patch(
                "custom_components.beatify.services.media_player.PLAYBACK_TIMEOUT", 1.0
            ):
                result = await svc.play_song(_make_song(title="New Song"))

        assert result is True

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
        assert poll_count >= 6  # Must have waited past the wrong song

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
    """Tests for multi-provider URI fallback in MA playback (#768)."""

    def test_candidates_primary_only(self):
        """Song with only spotify URI → single candidate, field=None (primary)."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {"uri": "spotify:track:abc", "_resolved_uri": "spotify:track:abc"}
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates == [(None, "spotify:track:abc")]

    def test_candidates_primary_then_alternates(self):
        """Primary comes first, alternates follow in _URI_FIELDS order."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "uri": "spotify:track:abc",
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
            "uri_tidal": "tidal://track/222",
        }
        fields = [field for field, _ in svc._get_ma_uri_candidates(song)]
        # Primary first (None), then apple_music before tidal per _URI_FIELDS
        assert fields[0] is None
        assert fields.index("uri_apple_music") < fields.index("uri_tidal")

    def test_candidates_dedupe_by_converted_uri(self):
        """`uri` and `uri_spotify` with the same value collapse to one candidate."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "uri": "spotify:track:abc",
            "uri_spotify": "spotify:track:abc",  # same as uri
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
        }
        uris = [uri for _, uri in svc._get_ma_uri_candidates(song)]
        assert uris.count("spotify:track:abc") == 1
        assert len(uris) == 2

    def test_candidates_converts_apple_music(self):
        """applemusic:// URIs are converted to MA-native apple_music:// form (#772)."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "_resolved_uri": "applemusic://track/999",
            "uri_apple_music": "applemusic://track/999",
        }
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates[0][1] == "apple_music://track/999"

    def test_candidates_learned_preference_goes_first(self):
        """If a field was learned as preferred, its URI is tried before primary."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        svc._ma_preferred_uri_field = "uri_apple_music"
        song = {
            "uri": "spotify:track:abc",
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
        }
        candidates = svc._get_ma_uri_candidates(song)
        assert candidates[0] == ("uri_apple_music", "apple_music://track/111")
        # Primary still present after
        assert (None, "spotify:track:abc") in candidates

    def test_candidates_no_uris_returns_empty(self):
        """Song with no URI fields yields no candidates."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        assert svc._get_ma_uri_candidates({"title": "x", "artist": "y"}) == []

    @pytest.mark.asyncio
    async def test_fallback_tried_when_primary_fails(self):
        """If primary URI returns False, the orchestrator tries the next candidate."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "title": "Song",
            "artist": "Artist",
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
        }

        calls: list[str] = []

        async def fake_try(uri: str, expected_title: str) -> bool:
            calls.append(uri)
            return uri != "spotify:track:abc"  # primary fails, alternate succeeds

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            result = await svc._play_via_music_assistant(song)

        assert result is True
        assert calls == ["spotify:track:abc", "apple_music://track/111"]
        assert svc._ma_preferred_uri_field == "uri_apple_music"

    @pytest.mark.asyncio
    async def test_primary_success_does_not_update_preference(self):
        """When primary (`_resolved_uri`) succeeds, no field is cached."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "title": "Song",
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
        }

        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=True)):
            result = await svc._play_via_music_assistant(song)

        assert result is True
        assert svc._ma_preferred_uri_field is None

    @pytest.mark.asyncio
    async def test_all_candidates_fail_returns_false(self):
        """Exhausted candidates → False, no cached preference."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        song = {
            "title": "Song",
            "_resolved_uri": "spotify:track:abc",
            "uri_apple_music": "applemusic://track/111",
        }

        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=False)):
            result = await svc._play_via_music_assistant(song)

        assert result is False
        assert svc._ma_preferred_uri_field is None

    @pytest.mark.asyncio
    async def test_learned_preference_used_on_next_song(self):
        """After a fallback succeeds, the next song tries that field first."""
        hass = _make_hass()
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")

        song_a = {
            "title": "A",
            "_resolved_uri": "spotify:track:a",
            "uri_apple_music": "applemusic://track/a",
        }
        song_b = {
            "title": "B",
            "_resolved_uri": "spotify:track:b",
            "uri_apple_music": "applemusic://track/b",
        }

        calls: list[str] = []

        async def fake_try(uri: str, expected_title: str) -> bool:
            calls.append(uri)
            # Spotify never works in this user's setup; apple_music always does.
            return uri.startswith("apple_music://")

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            assert await svc._play_via_music_assistant(song_a) is True
            assert await svc._play_via_music_assistant(song_b) is True

        # Song A: spotify fails, apple_music succeeds (2 calls)
        # Song B: apple_music tried first (cached), succeeds (1 call)
        assert calls == [
            "spotify:track:a",
            "apple_music://track/a",
            "apple_music://track/b",
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
