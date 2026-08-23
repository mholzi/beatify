"""Ein verlorener Submit darf den Knopf nicht fuer die Runde toeten (#2339).

`handleSubmitGuess` schaltete den Knopf ab und sendete. Kam kein `submit_ack`,
schaltete ihn **nichts** wieder ein: `handleSubmitAck` lief nicht, und
`resetSubmissionState` wird nur beim Rundenwechsel gerufen.

Das braucht keinen Netzabbruch. Bei einem halboffenen Socket — Wechsel des
Access Points, aufwachendes iPhone — steht `readyState` weiter auf `OPEN`,
`send()` schreibt in einen Puffer, der nirgendwo hingeht, und der Heartbeat
merkt es erst nach `HEARTBEAT_INTERVAL_MS` + `HEARTBEAT_TIMEOUT_MS`, also bis
zu **55 Sekunden**. Laenger als eine Runde.

Derselbe Waechter existiert seit #1663 fuer das **Beitreten**
(`startJoinTimeout`). Fuer das Abgeben gab es ihn nicht.

Geprueft wird die Verdrahtung am Quelltext: die Datei laeuft im Browser als
ES-Modul und laesst sich hier nicht ausfuehren, aber die Bedingungen, auf die
es ankommt, sind ablesbar — und genau sie waren vorher nicht da.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "js"
    / "player-game.js"
)


def _src() -> str:
    return _JS.read_text()


def _fn(name: str) -> str:
    """Der Rumpf einer Top-Level-Funktion, bis zur naechsten."""
    src = _src()
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n(?:export )?function ", src[start + 10 :])
    return src[start : start + 10 + nxt.start()] if nxt else src[start:]


class TestTheWatchdogIsArmed:
    def test_a_timeout_is_started_after_sending(self):
        # Ohne diese Zeile bleibt der Knopf fuer immer aus.
        body = _fn("handleSubmitGuess")
        assert "submitAckTimeoutId = setTimeout(" in body

    def test_it_re_enables_the_button(self):
        body = _fn("handleSubmitGuess")
        assert "btn.disabled = false" in body
        assert "showSubmitError(" in body

    def test_five_seconds(self):
        # Kurz genug, um innerhalb der Runde zu greifen — der Heartbeat
        # braucht bis zu 55 s und ist damit als Netz zu langsam.
        assert re.search(r"SUBMIT_ACK_TIMEOUT_MS\s*=\s*5000", _src())


class TestTheRaceIsHandled:
    def test_the_ack_clears_the_timer(self):
        body = _fn("handleSubmitAck")
        assert "clearSubmitAckTimeout()" in body

    def test_the_ack_sets_hassubmitted_before_anything_else(self):
        # Der Fall, den das Issue nicht nennt: ein Ack, das bei 5,01 s
        # eintrifft. Der Timer laeuft dann schon — er darf keinen Knopf
        # freigeben, den das Ack gerade gesperrt hat, sonst gibt der Spieler
        # zweimal ab.
        body = _fn("handleSubmitAck")
        assert body.index("clearSubmitAckTimeout()") < body.index("hasSubmitted = true")

    def test_the_timer_checks_hassubmitted_before_acting(self):
        body = _fn("handleSubmitGuess")
        assert "if (hasSubmitted) return;" in body

    def test_a_new_round_disarms_it(self):
        # Ein Waechter aus der Vorrunde darf keinem Spieler einen Fehler
        # zeigen, der noch gar nichts getippt hat.
        assert "clearSubmitAckTimeout()" in _fn("resetSubmissionState")


class TestWhatMustNotChange:
    def test_the_closed_socket_path_is_untouched(self):
        # Der bereits vorhandene Zweig fuer einen erkennbar toten Socket
        # bleibt, wie er war — der Watchdog ist fuer den Fall, in dem der
        # Socket sich gesund stellt.
        body = _fn("handleSubmitGuess")
        assert "errors.connectionLost" in body
        assert body.count("submitBtn.disabled = false") >= 1
