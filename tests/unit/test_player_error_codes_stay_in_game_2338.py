"""Ein unbekannter Fehlercode darf den Spieler nicht aus dem Spiel werfen (#2338).

`player-core.js` prueft im `error`-Zweig eine Handvoll Codes einzeln und fiel
danach auf `showView('join-view')` samt `clearStoredPlayerName()` zurueck. Der
Server schickt **17** Codes an Spieler, der Client kannte **8**.

Sieben der unbekannten sind im normalen Spielverlauf erreichbar. Der greifbarste
Fall: ein sabotierter Spieler tippt auf Abgeben, waehrend sein lokales
Freeze-Fenster und das des Servers um Millisekunden auseinanderliegen, der
Server antwortet `FROZEN` — und statt „du bist eingefroren" liegt das
Beitrittsformular vor ihm, sein Name geloescht, mitten in der Runde.

**#934 hat genau das schon einmal repariert**, aber nur fuer `INVALID_ACTION`.
Die Form blieb, also brachte der naechste unbekannte Code den Absturz zurueck.
Deshalb pruefen diese Tests die **Form**, nicht eine Liste: wer kuenftig einen
Servercode hinzufuegt, soll nichts kaputtmachen koennen.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"
_CLIENT = _ROOT / "www" / "js" / "player-core.js"
_CONST = _ROOT / "const.py"
_HANDLERS = _ROOT / "server" / "ws_handlers"

# Die einzigen drei, die wirklich das Ende der Sitzung bedeuten.
SESSION_ENDING = {"SESSION_TAKEOVER", "SESSION_NOT_FOUND", "GAME_ENDED"}


def _error_block() -> str:
    """Der `data.type === 'error'`-Zweig aus player-core.js."""
    src = _CLIENT.read_text()
    start = src.index("data.type === 'error'")
    end = src.index("data.type === 'song_stopped'", start)
    return src[start:end]


def _server_codes_sent_to_players() -> set[str]:
    """Die ERR_*-Konstanten, die ein ws_handler als `code` an Clients schickt."""
    names: set[str] = set()
    for f in _HANDLERS.glob("*.py"):
        names.update(re.findall(r'"code":\s*(ERR_[A-Z_]+)', f.read_text()))
    consts = dict(
        re.findall(
            r'^(ERR_[A-Z_]+)\s*=\s*\(?\s*"([A-Z_]+)"', _CONST.read_text(), re.MULTILINE
        )
    )
    return {consts[n] for n in names if n in consts}


def _branch_for(block: str, code: str) -> str:
    """Der Rumpf des Zweigs fuer ``code`` — bis zum naechsten Code-Vergleich.

    Ein Fenster fester Laenge greift hier nicht: es laeuft in den naechsten
    Zweig hinein und meldet dessen ``showView()`` als Treffer. Das ist beim
    ersten Lauf genau passiert.
    """
    m = re.search(rf"data\.code === '{code}'", block)
    if not m:
        return ""
    rest = block[m.start() :]
    nxt = re.search(r"\n\s*if \(data\.code === ", rest[1:])
    return rest[: nxt.start() + 1] if nxt else rest


class TestTheShapeCannotRegress:
    def test_the_error_branch_no_longer_wipes_the_session(self):
        # `clearStoredPlayerName()` im Fehlerzweig war der Kern des Schadens:
        # nicht nur die Ansicht wechselte, der Name war weg.
        assert "clearStoredPlayerName()" not in _error_block()

    def test_an_unrecognised_code_is_surfaced_inline(self):
        # Der neue Ausgang: alles, was durchfaellt, bleibt im Spiel.
        block = _error_block()
        tail = block[block.rindex("}") - 300 :]
        assert "handleSubmitError(data)" in tail

    def test_only_session_codes_can_leave_the_view(self):
        # `showView(` im Fehlerzweig ist erlaubt — aber nur in den Zweigen der
        # drei Codes, die eine Sitzung wirklich beenden.
        block = _error_block()
        for m in re.finditer(r"showView\(", block):
            before = block[: m.start()]
            last_code = re.findall(r"data\.code === '([A-Z_]+)'", before)
            assert last_code, "showView() vor jedem Code-Vergleich"
            assert last_code[-1] in SESSION_ENDING, (
                f"showView() haengt an {last_code[-1]}, das keine Sitzung beendet"
            )


class TestTheCodesThatBrokeIt:
    def test_the_seven_reachable_ones_have_no_branch_that_leaves(self):
        # Sie brauchen keinen eigenen Zweig mehr — sie duerfen nur nicht
        # hinausfuehren. Nach der Umkehr ist beides dasselbe.
        block = _error_block()
        for code in (
            "FROZEN",
            "ELIMINATED",
            "NOT_IN_GAME",
            "NO_SABOTAGE_AVAILABLE",
            "NO_ARTIST_CHALLENGE",
            "NO_MOVIE_CHALLENGE",
            "NO_TITLE_ARTIST_CHALLENGE",
        ):
            assert "showView(" not in _branch_for(block, code), (
                f"{code} fuehrt aus dem Spiel"
            )

    def test_every_server_code_is_either_session_ending_or_harmless(self):
        # Der eigentliche Wert: diese Zusicherung gilt auch fuer Codes, die es
        # heute noch nicht gibt. Genau daran ist #934 gescheitert.
        block = _error_block()
        for code in _server_codes_sent_to_players() - SESSION_ENDING:
            assert "showView(" not in _branch_for(block, code), (
                f"{code} fuehrt aus dem Spiel"
            )

    def test_the_server_really_sends_more_codes_than_the_client_lists(self):
        # Die Zahl, die das Issue traegt — als Test, damit sie nicht driftet.
        listed = set(re.findall(r"data\.code === '([A-Z_]+)'", _error_block()))
        assert len(_server_codes_sent_to_players()) > len(listed)
