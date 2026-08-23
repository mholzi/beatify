"""`/beatify/api/status` darf die Antwort der Runde nicht herausgeben (#2332).

`StatusView` steht bewusst auf ``requires_auth = False``: `wizard.js` und
`playlist-hub.js` holen den Endpunkt mit einem nackten ``fetch`` ohne Token,
ein harter Auth-Gate wuerde Einrichtung und Playlist-Picker lahmlegen.

Was daran aber offen stand, war der Inhalt. ``build_status_response`` legte
``game_state.get_state()`` **ungefiltert** unter ``active_game`` ab, und darin
sitzt ``admin_song.year`` — das gesuchte Jahr. Die Schwaerzung aus #1366
existierte, war aber ausschliesslich in den WebSocket-Pfad verdrahtet
(``websocket.py``, ``ws_handlers/_helpers.py``); ein HTTP-GET ging daran vorbei.

Spieler sind per Design unauthentifiziert und im selben Netz. Ein zweiter Tab
genuegte, und im Log stand nichts.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import build_status_response
from tests.conftest import make_game_state, make_songs


def _hass_with_game(*, title_artist_mode: bool = False):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        title_artist_mode=title_artist_mode,
    )
    gs.phase = GamePhase.PLAYING
    gs.current_song = {
        "year": 1984,
        "title": "Geheim",
        "artist": "Unbekannt",
        "album_art": "/art.png",
    }
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": gs}}
    hass.config_entries.async_entries.return_value = []
    return hass, gs


def _status(hass, *, redact: bool):
    return build_status_response(
        hass,
        version="0.0.0-test",
        media_players=[],
        playlists=[],
        redact_answers=redact,
    )


class TestUnauthorizedCaller:
    def test_the_year_is_gone(self):
        # Der Kern: das gesuchte Jahr darf nicht in der Antwort stehen.
        hass, _ = _hass_with_game()
        assert "admin_song" not in _status(hass, redact=True)["active_game"]

    def test_title_and_artist_are_hidden_in_title_artist_mode(self):
        # Im Title-&-Artist-Modus SIND Titel und Interpret die Antwort.
        hass, _ = _hass_with_game(title_artist_mode=True)
        song = _status(hass, redact=True)["active_game"]["song"]
        assert song["title"] != "Geheim"
        assert song["artist"] != "Unbekannt"

    def test_the_rest_of_the_payload_survives(self):
        # Der Endpunkt bleibt brauchbar — das ist der Grund, ihn zu schwaerzen
        # statt zu sperren. Wizard und Playlist-Hub holen ihn ohne Token.
        s = _status(_hass_with_game()[0], redact=True)
        assert "playlists" in s
        assert "media_players" in s
        assert s["active_game"] is not None
        assert s["active_game"]["phase"] == GamePhase.PLAYING.value


class TestAuthorizedCaller:
    def test_the_admin_screen_still_gets_the_answer(self):
        # Ohne diesen Fall waere die Reparatur ein neuer Fehler: der
        # Spielleiter-Bildschirm zeigt Jahr und Fun Facts.
        ag = _status(_hass_with_game()[0], redact=False)["active_game"]
        assert ag["admin_song"]["year"] == 1984

    def test_default_is_unredacted_for_existing_callers(self):
        # ``redact_answers`` ist opt-in. Jeder bestehende Aufrufer, der den
        # Parameter nicht kennt, verhaelt sich wie vorher.
        hass, _ = _hass_with_game()
        s = build_status_response(
            hass, version="0.0.0-test", media_players=[], playlists=[]
        )
        assert s["active_game"]["admin_song"]["year"] == 1984


class TestNoGameRunning:
    def test_redaction_is_harmless_without_a_game(self):
        # Kein Spiel -> ``active_game`` ist None, und die Schwaerzung darf
        # daran nicht scheitern.
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        hass.config_entries.async_entries.return_value = []
        assert _status(hass, redact=True)["active_game"] is None
