"""Ein echter Trackwechsel darf nicht am gleichen Titel scheitern (#2616).

Seit #2333 verlangen beide Bestaetigungswege in ``_check_state``, dass sich
``media_title`` gegenueber dem Stand vor dem ``play_media``-Aufruf geaendert
hat, und der Zweig nach dem Timeout wertet einen unveraenderten Titel als
„Lautsprecher haengt auf dem alten Track": er ruft ``media_stop`` und meldet
``unavailable``.

Der Titel ist aber keine Identitaet. Runde N spielt „Hello" (Adele), Runde N+1
zieht „Hello" (Lionel Richie). Music Assistant wechselt korrekt, ``media_title``
bleibt „Hello" — und Beatify stoppt nach der vollen Wartezeit den Lautsprecher,
markiert den Song als nicht verfuegbar und springt weiter. Im Raum hoert man
15 Sekunden den richtigen Song, dann Stille, dann einen anderen.

``media_content_id`` ist die Identitaet, und ``_uri_match_tokens`` erkennt
unsere URI darin bereits (#1380) — ``wait_for_metadata_update`` nutzt genau
das. ``_check_state`` hat es nie herangezogen.

Die #2333-Invariante bleibt: dort wechselt MA gar nicht, also bewegt sich auch
die content id nicht. Die Faelle stehen in
``test_ma_path1_requires_title_change_2333.py`` und muessen gruen bleiben.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from tests.unit.test_media_player import _make_hass, _make_state

ADELE_URI = "spotify:track:1Yc9Q4KJPZa8bxJqQx7WYr"
RICHIE_URI = "spotify:track:6Y1CnB7ZeF9EAVUCPQpaGF"


async def _instant_timeout(awaitable=None, *_a, **_k):
    """Die Wartezeit sofort ablaufen lassen — der Zweig nach dem Timeout."""
    if awaitable is not None and asyncio.iscoroutine(awaitable):
        awaitable.close()
    raise asyncio.TimeoutError


def _state_with_content_id(
    content_id: str,
    *,
    state: str = "playing",
    media_title: str = "Hello",
    media_position: float = 5,
    media_position_updated_at: str = "2020-01-01T00:00:00+00:00",
) -> MagicMock:
    """``_make_state`` plus die content id, die der Lautsprecher meldet."""
    mock = _make_state(
        state,
        media_title=media_title,
        media_position=media_position,
        media_position_updated_at=media_position_updated_at,
    )
    mock.attributes["media_content_id"] = content_id
    return mock


class TestTitleCollisionBetweenRounds:
    """„Hello" folgt auf „Hello" — zwei verschiedene Songs."""

    @pytest.mark.asyncio
    async def test_new_track_with_identical_title_confirms(self):
        """Der Wechsel ist echt: die content id traegt die angeforderte URI."""
        before = _state_with_content_id(
            ADELE_URI,
            media_title="Hello",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        after = _state_with_content_id(
            RICHIE_URI,
            media_title="Hello",
            media_position=2,
            media_position_updated_at="2020-01-01T00:00:03+00:00",
        )
        hass = _make_hass("playing", media_title="Hello")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, after])

        confirmed = await svc._strategy.try_play(RICHIE_URI, "Hello", "Lionel Richie")

        assert confirmed is True, (
            "Gleicher Titel, andere content id — der Wechsel hat stattgefunden"
        )
        assert svc._strategy._last_confirm_path == 1
        assert svc.last_failure_reason is None

    @pytest.mark.asyncio
    async def test_the_speaker_is_not_stopped_after_the_timeout(self):
        """Der hoerbare Teil des Fehlers: nach der vollen Wartezeit rief
        Beatify ``media_stop`` und meldete ``unavailable``. Hier steht die
        angeforderte URI in der content id — der Lautsprecher spielt richtig
        und muss weiterspielen."""
        before = _state_with_content_id(
            ADELE_URI,
            media_title="Hello",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        # Nach dem Timeout: richtiger Track, identischer Titel. Die Position
        # steht noch, damit der schnelle Weg nicht schon vorher greift.
        after = _state_with_content_id(
            RICHIE_URI,
            media_title="Hello",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        hass = _make_hass("playing", media_title="Hello")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, after, after])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            confirmed = await svc._strategy.try_play(
                RICHIE_URI, "Hello", "Lionel Richie"
            )

        assert confirmed is True
        assert svc.last_failure_reason != "unavailable"
        stop_calls = [
            call
            for call in hass.services.async_call.call_args_list
            if call.args[:2] == ("media_player", "media_stop")
        ]
        assert not stop_calls, (
            "Beatify hat den Lautsprecher gestoppt, obwohl der richtige Song lief"
        )


class TestTheInvariantFrom2333StillHolds:
    """Die content id darf den Titelvergleich nur ergaenzen, nie ersetzen."""

    @pytest.mark.asyncio
    async def test_prior_track_still_playing_is_still_rejected(self):
        """#2333: MA wechselt nicht, der Vorgaenger laeuft weiter. Titel und
        content id stehen beide — keine Bestaetigung ueber Weg 1."""
        before = _state_with_content_id(
            ADELE_URI,
            media_title="Stay With Me",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        still_playing = _state_with_content_id(
            ADELE_URI,
            media_title="Stay With Me",
            media_position=126,
            media_position_updated_at="2020-01-01T00:00:06+00:00",
        )
        hass = _make_hass("playing", media_title="Stay With Me")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, still_playing, still_playing])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            confirmed = await svc._strategy.try_play(RICHIE_URI, "Stay", "Rihanna")

        assert confirmed is False
        assert svc._strategy._last_confirm_path != 1
        assert svc.last_failure_reason == "unavailable"

    @pytest.mark.asyncio
    async def test_a_foreign_content_id_does_not_confirm(self):
        """Die alte Warteschlange schaltet auf einen fremden Track weiter: die
        content id bewegt sich, traegt aber nicht unsere URI. Der Titel bleibt
        gleich (Namensgleichheit auch hier) — das darf nicht reichen."""
        foreign = "spotify:track:0000000000000000000000"
        before = _state_with_content_id(
            ADELE_URI,
            media_title="Hello",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        auto_advanced = _state_with_content_id(
            foreign,
            media_title="Hello",
            media_position=3,
            media_position_updated_at="2020-01-01T00:00:03+00:00",
        )
        hass = _make_hass("playing", media_title="Hello")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, auto_advanced, auto_advanced])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            confirmed = await svc._strategy.try_play(
                RICHIE_URI, "Hello", "Lionel Richie"
            )

        assert confirmed is False
        assert svc._strategy._last_confirm_path != 1

    @pytest.mark.asyncio
    async def test_a_speaker_without_content_id_is_unaffected(self):
        """Meldet die Plattform keine content id, entscheidet weiterhin allein
        der Titelvergleich — der Stand von #2333, unveraendert."""
        before = _make_state(
            "playing",
            media_title="Hello",
            media_position=120,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        still_playing = _make_state(
            "playing",
            media_title="Hello",
            media_position=126,
            media_position_updated_at="2020-01-01T00:00:06+00:00",
        )
        hass = _make_hass("playing", media_title="Hello")
        svc = MediaPlayerService(hass, "media_player.test", platform="music_assistant")
        hass.states.get = MagicMock(side_effect=[before, still_playing, still_playing])

        with patch(
            "custom_components.beatify.services.media_player.asyncio.wait_for",
            new=_instant_timeout,
        ):
            confirmed = await svc._strategy.try_play(
                RICHIE_URI, "Hello", "Lionel Richie"
            )

        assert confirmed is False
        assert svc.last_failure_reason == "unavailable"
