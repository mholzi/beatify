"""Nach einem Reload muss der Client die eigene Abgabe wiederfinden (#2340).

Beim Reload steht `state.currentRoundNumber` auf 0. Der naechste
PLAYING-Broadcast traegt die echte Rundennummer, `newRound !== 0` ist wahr,
und `resetSubmissionState()` laeuft: `hasSubmitted` faellt auf false, der
Regler springt auf den Startwert, der Knopf lebt wieder.

Im **selben Frame** steht `players[mich].submitted === true`. Gelesen wurde es
nie — `findMe()` gibt es seit langem, und `player.submitted` wird fuer
*andere* Spieler mehrfach ausgewertet; der eigene Zustand war die Luecke.

Der Preis: der Spieler sieht einen aktiven Regler auf dem Startjahr statt
seiner 1987, haelt die Abgabe fuer verloren, tippt erneut — und bekommt
`ALREADY_SUBMITTED`. **Der Weg zurueck in den richtigen Zustand fuehrte ueber
eine Fehlermeldung.**

**Das Jahr wird NICHT wiederhergestellt**, und das ist kein Versaeumnis.
`guess` reist nur im REVEAL-Payload (`get_reveal_players_state`). Der
PLAYING-Broadcast (`get_players_state`) laesst es bewusst weg: ein Frame geht
an alle, und die Tipps aller Spieler mitten in der Runde zu verschicken wuerde
dem Raum die laufenden Antworten geben. Sperren ohne die Zahl ist die ehrliche
Haelfte.
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
_SERIALIZER = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "game"
    / "serializers.py"
)


def _src() -> str:
    return _JS.read_text()


def _fn(name: str) -> str:
    src = _src()
    start = src.index(f"function {name}(")
    nxt = re.search(r"\n(?:export )?function ", src[start + 10 :])
    return src[start : start + 10 + nxt.start()] if nxt else src[start:]


class TestTheGapIsClosed:
    def test_the_reconciliation_runs_on_every_state_frame(self):
        assert "reconcileOwnSubmission(data)" in _fn("updateGameView")

    def test_it_reads_the_servers_verdict_for_the_local_player(self):
        body = _fn("reconcileOwnSubmission")
        assert "findMe(" in body
        assert "me.submitted" in body

    def test_it_restores_the_locked_state_via_the_real_ack_path(self):
        # `handleSubmitAck()` statt einer zweiten Kopie der Sperr-Logik —
        # sonst driften die beiden Wege auseinander.
        assert "handleSubmitAck()" in _fn("reconcileOwnSubmission")

    def test_it_does_not_try_to_restore_the_year(self):
        # Der PLAYING-Broadcast traegt `guess` nicht, und das mit Absicht:
        # ein Frame geht an alle. Wer hier das Jahr setzen wollte, muesste
        # es erst senden — und wuerde damit die laufenden Tipps verteilen.
        body = _fn("reconcileOwnSubmission")
        assert "me.guess" not in body


class TestItDoesNotFightThePlayer:
    def test_it_returns_early_when_the_client_already_knows(self):
        # updateGameView laeuft bei JEDER Abgabe irgendeines Mitspielers.
        # Ohne diesen Ausstieg wuerde die Sperr-Logik pro Frame erneut
        # laufen, den ganzen Rest der Runde.
        body = _fn("reconcileOwnSubmission")
        first = body.index("{")
        assert "if (hasSubmitted) return;" in body[first : first + 200]

    def test_nothing_happens_when_the_server_says_not_submitted(self):
        body = _fn("reconcileOwnSubmission")
        assert "if (!me || !me.submitted) return;" in body


class TestWhatTheWireActuallyCarries:
    def test_the_playing_payload_ships_submitted_but_not_guess(self):
        # Die Zusicherung, auf der die Entscheidung oben steht. Kaeme `guess`
        # eines Tages in den PLAYING-Broadcast, waere das ein Leck und dieser
        # Test die Stelle, an der es auffaellt.
        reg = (
            Path(__file__).resolve().parents[2]
            / "custom_components"
            / "beatify"
            / "game"
            / "player_registry.py"
        ).read_text()
        start = reg.index("def get_players_state(")
        block = reg[start : start + 2000]
        assert '"submitted": p.submitted' in block
        assert '"guess"' not in block
