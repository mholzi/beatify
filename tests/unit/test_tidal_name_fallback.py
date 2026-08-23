"""Tidal name fallback: a safety net behind the stored URIs, not a replacement.

Odesli retired its public API on 2026-07-31 — it was the only source Beatify
ever had for Tidal ids, so a missing ``uri_tidal`` can no longer be filled. This
lets Music Assistant resolve such a track from name + artist instead.

The risk that buys is a *wrong edition*, and it is not hypothetical: measured
against ~2000 catalogue tracks with a known Deezer id, a plain "artist title"
search returned a different recording for 2 % of mainstream tracks and 19 % of
the EDM ones. The cases in ``test_edition_gate_rejects_measured_failures`` are
verbatim from that measurement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import (
    MediaPlayerService,
    _edition_matches,
)


def _make_hass() -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    return hass


def _svc(provider: str) -> MediaPlayerService:
    return MediaPlayerService(
        _make_hass(),
        "media_player.test",
        platform="music_assistant",
        provider=provider,
    )


def _playing(title: str, artist: str = "Artist") -> MagicMock:
    state = MagicMock()
    state.state = "playing"
    state.attributes = {"media_title": title, "media_artist": artist}
    return state


# --------------------------------------------------------------- edition gate


class TestEditionGate:
    @pytest.mark.parametrize(
        ("expected", "played"),
        [
            ("Satisfaction", "Satisfaction (Uk Radio Edit)"),
            ("Booyah", "Booyah (Radio Edit)"),
            (
                "Scary Monsters and Nice Sprites",
                "Scary Monsters and Nice Sprites (Zedd Remix)",
            ),
            ("Without You (feat. Usher)", "Without You (feat. Usher) (Extended)"),
            ("Burn", "Burn [Ellie Goulding vs. Aybsent Mynded] (Aybsent Mynded Remix)"),
            ("No Broke Boys", "No Broke Boys (Lee Foss Remix)"),
            ("A-Ba-Ni-Bi", "A Ba Ni Bi (1978) - Karaoke Playback Avec Choeurs"),
            ("Hotel California", "Hotel California - Live"),
        ],
    )
    def test_edition_gate_rejects_measured_failures(self, expected, played):
        """Every one of these came back from a real "artist title" search."""
        assert _edition_matches(expected, played) is False

    @pytest.mark.parametrize(
        ("expected", "played"),
        [
            # The provider dropping a suffix we carry is fine — the gate is
            # deliberately one-directional.
            ("Waves - Robin Schulz Radio Edit", "Waves"),
            ("Waves - Robin Schulz Radio Edit", "Waves (Robin Schulz Radio Edit)"),
            ("Ghosts 'n' Stuff (feat. Rob Swire)", "Ghosts 'n' Stuff"),
            # #1381 must keep working: a translated title shares no tokens and
            # carries no edition marker.
            ("Das Modell", "The Model"),
            # A remaster is the same recording, not a different edition.
            ("Bohemian Rhapsody", "Bohemian Rhapsody - Remastered 2011"),
            ("Satisfaction", "Satisfaction"),
        ],
    )
    def test_edition_gate_passes_legitimate_titles(self, expected, played):
        assert _edition_matches(expected, played) is True

    def test_missing_titles_do_not_reject(self):
        """Nothing to compare is not evidence of a wrong edition."""
        assert _edition_matches("", "anything") is True
        assert _edition_matches("Satisfaction", "") is True


# ------------------------------------------------------------- fallback wiring


class TestTidalNameFallback:
    @pytest.mark.asyncio
    async def test_stored_uri_wins_and_fallback_never_runs(self):
        """The whole point: this is a net *behind* the URIs, not instead of them."""
        svc = _svc("tidal")
        song = {
            "title": "Song",
            "artist": "Artist",
            "uri_tidal": "tidal://track/12345",
        }
        calls: list[str] = []

        async def fake_try(uri, expected_title, expected_artist="", artist_filter=None):
            calls.append(uri)
            return True

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            assert await svc._play_via_music_assistant(song) is True

        # The stored id is normalised to a browse URL on the way out; what
        # matters is that exactly one call happened and it was not the name.
        assert len(calls) == 1
        assert "999" not in calls[0] and calls[0] != "Song"
        assert "12345" in calls[0]

    @pytest.mark.asyncio
    async def test_missing_uri_reaches_the_fallback(self):
        """Without the fallback this returned False before trying anything."""
        svc = _svc("tidal")
        svc._hass.states.get = MagicMock(return_value=_playing("Song"))
        song = {"title": "Song", "artist": "Artist"}
        calls: list[str] = []

        async def fake_try(uri, expected_title, expected_artist="", artist_filter=None):
            calls.append(uri)
            return True

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            assert await svc._play_via_music_assistant(song) is True

        assert calls == ["Song"]

    @pytest.mark.asyncio
    async def test_fallback_runs_after_a_dead_uri(self):
        svc = _svc("tidal")
        svc._hass.states.get = MagicMock(return_value=_playing("Song"))
        song = {"title": "Song", "artist": "Artist", "uri_tidal": "tidal://track/999"}
        calls: list[str] = []

        async def fake_try(uri, expected_title, expected_artist="", artist_filter=None):
            calls.append(uri)
            return uri == "Song"  # the stored URI is dead, the name works

        with patch.object(svc, "_try_ma_play", side_effect=fake_try):
            assert await svc._play_via_music_assistant(song) is True

        assert len(calls) == 2
        assert "999" in calls[0]  # stored URI first, normalised to a browse URL
        assert calls[1] == "Song"  # then, and only then, the name

    @pytest.mark.asyncio
    async def test_wrong_edition_is_rejected_even_though_ma_accepted_it(self):
        """`_try_ma_play` says yes — its title gate accepts a prefix. We say no."""
        svc = _svc("tidal")
        svc._hass.states.get = MagicMock(
            return_value=_playing("Satisfaction (Uk Radio Edit)")
        )
        song = {"title": "Satisfaction", "artist": "Benny Benassi"}

        with patch.object(svc, "_try_ma_play", AsyncMock(return_value=True)):
            assert await svc._play_via_music_assistant(song) is False

        assert svc.last_failure_reason == "wrong_track"

    @pytest.mark.asyncio
    async def test_other_providers_keep_the_old_hard_failure(self):
        """Only ma_library and tidal opt in; Spotify must not start guessing."""
        svc = _svc("spotify")
        song = {"title": "Song", "artist": "Artist"}
        try_ma = AsyncMock(return_value=True)

        with patch.object(svc, "_try_ma_play", try_ma):
            assert await svc._play_via_music_assistant(song) is False

        try_ma.assert_not_called()
        assert svc.last_failure_reason == "unavailable"

    @pytest.mark.asyncio
    async def test_no_artist_means_no_fallback(self):
        """A name search needs both halves, and so does verifying its answer."""
        svc = _svc("tidal")
        song = {"title": "Song"}
        try_ma = AsyncMock(return_value=True)

        with patch.object(svc, "_try_ma_play", try_ma):
            assert await svc._play_via_music_assistant(song) is False

        try_ma.assert_not_called()
        assert svc.last_failure_reason == "unavailable"
