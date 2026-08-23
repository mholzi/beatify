"""Weg 1 darf nicht bestaetigen, solange der Titel derselbe ist (#2333).

``_check_state`` in ``_try_ma_play`` bestaetigt den Playback-Start ueber zwei
Wege. Weg 2 verlangte seit #1381 ausdruecklich ``current_title != title_before``.
Weg 1 verlangte es **nicht** — er nahm einen Teilzeichenketten-Treffer gegen
das, was gerade lief, und das schliesst den Song der **vorigen Runde** ein, der
einfach weiterspielt. Die Docstring darueber versprach die Invariante fuer
*beide* Wege.

``position_fresh`` faengt das nicht ab: ein Track, der weiterlaeuft, schiebt
seine eigene Position ohnehin vor.

**Warum das schwerer wiegt als ein Fehlalarm**: nur eine Bestaetigung ueber
Weg 1 ist stark genug, ein URI-Feld als ``_ma_preferred_uri_field`` zu lernen.
Eine falsche Bestaetigung merkt sich also genau das Feld, das gerade nichts
abgespielt hat, und probiert es fuer den Rest der Sitzung zuerst — der Fehler
macht sich selbst wahrscheinlicher.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from tests.unit.test_media_player import _make_hass, _make_state


async def _instant_timeout(awaitable=None, *_a, **_k):
    if awaitable is not None and asyncio.iscoroutine(awaitable):
        awaitable.close()
    raise asyncio.TimeoutError


class TestSubstringOfTheStillPlayingTrack:
    @pytest.mark.asyncio
    async def test_stay_does_not_confirm_against_stay_with_me(self):
        """Der Fall aus dem Issue: Runde N spielt „Stay With Me", Runde N+1
        zieht „Stay", dessen URI im Storefront fehlt. MA wechselt nie."""
        unchanged = _make_state(
            "playing",
            media_title="Stay With Me",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Derselbe Track laeuft weiter — nur die Position tickt.
        still_playing = _make_state(
            "playing",
            media_title="Stay With Me",
            media_position=126,
            media_position_updated_at="2020-01-01T00:00:06+00:00",
        )
        hass = _make_hass("playing", media_title="Stay With Me")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[unchanged, still_playing])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            await svc._try_ma_play("spotify:track:x", "Stay", "Rihanna")

        assert svc._last_confirm_path != 1, (
            "Weg 1 hat den weiterlaufenden Vorgaenger bestaetigt"
        )

    @pytest.mark.asyncio
    async def test_the_failing_uri_field_is_not_learned(self):
        """Die Folge, die schwerer wiegt als die falsche Runde: das Feld, das
        gerade nichts abgespielt hat, darf nicht als bevorzugt gelernt werden.
        Das Lernen haengt an ``_last_confirm_path == 1``."""
        unchanged = _make_state(
            "playing",
            media_title="One More Time",
            media_position=90,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        still_playing = _make_state(
            "playing",
            media_title="One More Time",
            media_position=96,
            media_position_updated_at="2020-01-01T00:00:06+00:00",
        )
        hass = _make_hass("playing", media_title="One More Time")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[unchanged, still_playing])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            await svc._try_ma_play("spotify:track:x", "One", "Metallica")

        assert svc._last_confirm_path != 1


class TestWhatMustKeepWorking:
    @pytest.mark.asyncio
    async def test_a_real_track_change_still_confirms_via_path_1(self):
        """Der Normalfall darf nicht mit repariert werden: der Titel wechselt
        wirklich und enthaelt den erwarteten — Weg 1 bestaetigt weiterhin."""
        before = _make_state(
            "playing",
            media_title="Old Track",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        current = _make_state(
            "playing",
            media_title="Stay (Radio Edit)",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",
        )
        hass = _make_hass("playing", media_title="Old Track")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, current])

        confirmed = await svc._try_ma_play("spotify:track:x", "Stay", "Rihanna")

        assert confirmed is True
        assert svc._last_confirm_path == 1

    @pytest.mark.asyncio
    async def test_the_cold_start_still_confirms(self):
        """Nichts lief vorher: ``title_before`` ist leer, der neue Titel ist
        gegenueber „nichts" ein echter Wechsel. Ohne diesen Fall wuerde die
        erste Runde jedes Spiels nicht mehr bestaetigen."""
        before = _make_state(
            "idle",
            media_title="",
            media_position=0,
            media_position_updated_at=None,
        )
        current = _make_state(
            "playing",
            media_title="Stay",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:01+00:00",
        )
        hass = _make_hass("idle", media_title="")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, current])

        confirmed = await svc._try_ma_play("spotify:track:x", "Stay", "Rihanna")

        assert confirmed is True
        assert svc._last_confirm_path == 1
