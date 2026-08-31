"""Handler-Fehler sind keine Parse-Fehler (#2336).

Parsen und Dispatch lagen in **einem** ``try``, und der ``except`` darunter
loggte beides als ``Failed to parse WebSocket message``. Das beschreibt den
Fehler nicht nur ungenau — es **zeigt auf die falsche Partei**. Wer die Zeile
liest, schliesst auf einen Client, der kaputtes JSON schickt, und sucht dort.

Sichtbar wurde es an ``finalize_and_end``: das wirft **absichtlich** weiter
(#1754), damit der Game-End-Claim freigegeben wird und ein zweiter Versuch die
Endsequenz erneut fahren kann. Der Entwurf stimmt — aber der Admin bekam kein
Frame zurueck, also war „Spiel beenden" ein toter Knopf mit einer irrefuehrenden
Log-Zeile daneben. Ein Retry hilft nur dem, der weiss, dass er einen braucht.

Die Tests fahren die **echte** ``handle``-Schleife: ``web.WebSocketResponse``
wird im Modul durch eine Attrappe ersetzt, die eine Nachricht liefert und
mitschreibt, was zurueckgeht.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from aiohttp import WSMsgType

from custom_components.beatify.const import ERR_INTERNAL, ERR_INVALID_ACTION
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler


class _FakeWS:
    """Liefert genau eine TEXT-Nachricht und schreibt Antworten mit."""

    def __init__(self, msg):
        self._msgs = [msg]
        self.sent: list[dict] = []
        self.send_should_fail = False
        # `handle`'s finally-block inspects these on teardown.
        self.closed = False
        self.close_code = None
        self.beatify_request_meta: dict = {}

    def __aiter__(self):
        async def gen():
            for m in self._msgs:
                yield m

        return gen()

    async def prepare(self, _request):
        return None

    async def send_json(self, payload):
        if self.send_should_fail:
            raise ConnectionResetError("socket already gone")
        self.sent.append(payload)

    async def close(self):
        return None

    def exception(self):
        return None


def _text(payload=None, *, broken=False):
    m = MagicMock()
    m.type = WSMsgType.TEXT
    if broken:
        m.json.side_effect = ValueError("Expecting value: line 1 column 1")
    else:
        m.json.return_value = payload
    return m


def _request():
    r = MagicMock()
    r.remote = "127.0.0.1"
    r.path = "/beatify/ws"
    r.headers = {"User-Agent": "pytest"}
    return r


async def _run(handler, ws):
    with patch(
        "custom_components.beatify.server.websocket.web.WebSocketResponse",
        return_value=ws,
    ):
        await handler.handle(_request())


def _handler(on_message=None):
    h = BeatifyWebSocketHandler(MagicMock())
    if on_message is not None:
        h._handle_message = on_message
    return h


class TestARaisingHandler:
    @pytest.mark.asyncio
    async def test_the_sender_gets_an_error_frame(self):
        async def boom(_ws, _data):
            raise RuntimeError("advance_to_end blew up")

        ws = _FakeWS(_text({"type": "end_game"}))
        await _run(_handler(boom), ws)

        assert ws.sent, (
            "der Sender bekam gar nichts zurueck — der urspruengliche Fehler"
        )
        frame = ws.sent[-1]
        assert frame["type"] == "error"
        assert frame["code"] == ERR_INTERNAL

    @pytest.mark.asyncio
    async def test_it_is_logged_with_a_traceback(self, caplog):
        async def boom(_ws, _data):
            raise RuntimeError("advance_to_end blew up")

        with caplog.at_level("ERROR"):
            await _run(_handler(boom), _FakeWS(_text({"type": "end_game"})))

        assert any(r.exc_info for r in caplog.records), (
            "ohne Traceback bleibt nur Raten, welcher Handler geworfen hat"
        )
        assert not any("Failed to parse" in r.getMessage() for r in caplog.records), (
            "ein Handler-Fehler darf sich nicht als Parse-Fehler ausgeben"
        )

    @pytest.mark.asyncio
    async def test_the_code_is_distinct_from_invalid_action(self):
        # INVALID_ACTION heisst „verstanden und abgelehnt". Ein abgestuerzter
        # Handler ist etwas anderes, und der Client soll es unterscheiden.
        assert ERR_INTERNAL != ERR_INVALID_ACTION


class TestBrokenJson:
    @pytest.mark.asyncio
    async def test_still_reported_as_a_parse_failure(self, caplog):
        with caplog.at_level("WARNING"):
            await _run(_handler(), _FakeWS(_text(broken=True)))

        assert any("Failed to parse" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_error_frame_for_malformed_input(self):
        # Wer kaputtes JSON schickt, kann mit einer strukturierten Antwort
        # ohnehin nichts anfangen — und der Ablauf soll sich hier nicht
        # aendern.
        ws = _FakeWS(_text(broken=True))
        await _run(_handler(), ws)
        assert ws.sent == []


class TestTheConnectionSurvives:
    @pytest.mark.asyncio
    async def test_a_failing_send_does_not_propagate(self):
        # Das Fehler-Frame ist eine Hoeflichkeit, keine Pflicht. Ist der
        # Socket schon weg, darf der Zustellversuch nicht die Schleife
        # mitreissen — sonst repariert man das Log und bricht die Sitzung.
        async def boom(_ws, _data):
            raise RuntimeError("handler down")

        ws = _FakeWS(_text({"type": "end_game"}))
        ws.send_should_fail = True

        await _run(_handler(boom), ws)  # darf nicht werfen
