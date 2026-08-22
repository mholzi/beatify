"""``--youtube-first``: nicht noch einmal ueber Boden laufen, der schon abgesucht ist (#2301).

Der YouTube-Backfill meldete taeglich „0 URIs" und sah damit aus wie ein
konvergierter Katalog. Zwei Laeufe am 22.08.2026 zeigen etwas anderes: sieben
bzw. fuenf Scheiben, ``spent_today`` vor und nach dem Lauf **0/90** — die
YouTube-Phase hatte zwoelf Aufrufe frei und machte keinen.

Die Ursache ist der Resume-Cursor. Songs davor hat die YouTube-Phase in einem
frueheren Lauf schon gesehen, aber die Schleife lief trotzdem ueber sie und
zahlte je einen Odesli-Aufruf. Odesli ist auf ``--odesli-sleep`` gedrosselt
(6 s), eine Fuenf-Minuten-Scheibe kauft also rund 50 Songs Anlauf. Bei
Cursor-Staenden wie edm-anthems 234 oder 80er-hits 153 endet das Fenster,
bevor je neuer Boden erreicht wird.

Diese Tests halten die Bedingung fest, unter der ein Song uebersprungen wird —
und ebenso die drei Faelle, in denen er es NICHT werden darf.

``scripts/`` ist kein Package, das Modul wird daher per Pfad geladen.
"""

from __future__ import annotations

from pathlib import Path

# Das Skript wird NICHT importiert: es zieht beim Import Netz-Abhaengigkeiten
# und argparse-Aufbau nach sich, und die Bedingung, um die es hier geht, ist
# eine Zeile. Geprueft wird sie einmal als nachgebildetes Praedikat und einmal
# als Textprobe am echten Quelltext, damit ein Umbau nicht stillschweigend an
# den Tests vorbeigeht.
_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "provider-uri-backfill"
    / "scripts"
    / "backfill_provider_uris.py"
)


def skips(youtube_first: bool, yt_gap: bool, idx: int, cursor: int) -> bool:
    """Die Bedingung aus dem Song-Loop, isoliert nachgebildet."""
    return youtube_first and yt_gap and idx < cursor


class TestFastForward:
    def test_skips_a_song_the_cursor_has_already_passed(self):
        # Der eigentliche Fall: tomorrowland stand auf Cursor 46, die Schleife
        # begann bei 0 und verbrannte das Fenster auf dem Weg dorthin.
        assert skips(True, yt_gap=True, idx=0, cursor=46) is True
        assert skips(True, yt_gap=True, idx=45, cursor=46) is True

    def test_does_not_skip_at_or_after_the_cursor(self):
        # Genau hier faengt die Arbeit an, fuer die der Lauf existiert.
        assert skips(True, yt_gap=True, idx=46, cursor=46) is False
        assert skips(True, yt_gap=True, idx=47, cursor=46) is False

    def test_does_not_skip_a_song_without_a_youtube_gap(self):
        # Ein Song ohne YouTube-Luecke hat mit dem Cursor nichts zu tun; seine
        # Apple/Deezer/Tidal-Luecken bleiben normal erreichbar.
        assert skips(True, yt_gap=False, idx=0, cursor=46) is False

    def test_does_nothing_when_the_flag_is_off(self):
        # Die anderen Agenten (Apple, Deezer, Tidal) rufen dasselbe Skript ohne
        # das Flag auf. Fuer sie darf sich nichts aendern.
        assert skips(False, yt_gap=True, idx=0, cursor=46) is False
        assert skips(False, yt_gap=True, idx=45, cursor=999) is False

    def test_a_fresh_playlist_is_untouched(self):
        # Cursor 0 heisst: noch nie angesehen. Dann wird nichts uebersprungen.
        assert skips(True, yt_gap=True, idx=0, cursor=0) is False


class TestOptionExists:
    def test_the_flag_exists_and_is_opt_in(self):
        src = _SCRIPT.read_text()
        assert '"--youtube-first"' in src
        # store_true heisst: ohne das Flag bleibt alles, wie es war. Genau
        # darauf verlassen sich die Apple-, Deezer- und Tidal-Agenten.
        idx = src.index('"--youtube-first"')
        assert 'action="store_true"' in src[idx : idx + 400]

    def test_the_condition_is_wired_into_the_song_loop(self):
        src = _SCRIPT.read_text()
        assert (
            "if args.youtube_first and yt_gap and this_global_idx < yt_state.cursor:"
            in src
        )

    def test_odesli_still_runs_before_the_youtube_search(self):
        # Die Reihenfolge im Quelltext bleibt, wie sie war — geaendert wurde
        # nur, WANN Odesli ueberhaupt gefragt wird (siehe TestOdesliSkip).
        # Fuer jeden Lauf ohne ``--youtube-first`` gilt unveraendert: Odesli
        # liefert den YouTube-Link gratis mit (0 Quota), und der Aufruf steht
        # deshalb vor der Suche, die 100 Einheiten kostet.
        src = _SCRIPT.read_text()
        odesli_at = src.index("---- Odesli (apple/tidal/deezer")
        youtube_at = src.index("---- YouTube Data API search.list")
        assert odesli_at < youtube_at


def wants_odesli(
    non_yt_gaps: list[str], yt_gap: bool, yt_key: bool, youtube_first: bool
) -> bool:
    """Die ``want_odesli``-Bedingung aus dem Song-Loop, isoliert nachgebildet."""
    return bool(non_yt_gaps) or (yt_gap and yt_key and not youtube_first)


class TestOdesliSkip:
    """Der Gratis-Vorabtreffer ist unter ``--youtube-first`` nicht gratis (#2301).

    Er kostet ``--odesli-sleep`` Sekunden pro Song, und die YouTube-Suche steht
    im selben Schleifendurchgang dahinter. Der Zeitdeckel nimmt also zuerst die
    Suche. Gemessen am 22.08.2026 um 15:32: fuenf Scheiben, drei davon erreichten
    ``search.list`` kein einziges Mal, der Lauf endete am 25-Minuten-Deckel mit
    24 von 90 erlaubten Suchen.
    """

    def test_youtube_only_gap_skips_odesli_under_the_flag(self):
        # Der Fall, um den es geht: nichts ausser YouTube fehlt, also gibt es
        # nichts, wofuer sich die Wartezeit noch lohnen wuerde.
        assert wants_odesli([], yt_gap=True, yt_key=True, youtube_first=True) is False

    def test_youtube_only_gap_still_asks_odesli_without_the_flag(self):
        # Apple-, Deezer- und Tidal-Agenten rufen dasselbe Skript ohne das Flag
        # auf. Fuer sie bleibt der Gratis-Vorabtreffer unveraendert erhalten.
        assert wants_odesli([], yt_gap=True, yt_key=True, youtube_first=False) is True

    def test_a_second_gap_still_needs_odesli_even_under_the_flag(self):
        # Apple/Deezer/Tidal kommen NUR ueber Odesli. Fehlt einer davon mit,
        # muss der Aufruf stattfinden — sonst repariert der YouTube-Lauf eine
        # Luecke und reisst eine andere auf.
        for extra in (["apple_music"], ["deezer"], ["tidal"]):
            assert (
                wants_odesli(extra, yt_gap=True, yt_key=True, youtube_first=True)
                is True
            )

    def test_without_a_youtube_key_nothing_changes(self):
        # Ohne Key gibt es keine Suche, die man vorziehen koennte. Dann haengt
        # alles allein an den Nicht-YouTube-Luecken — mit Flag wie ohne.
        assert wants_odesli([], yt_gap=True, yt_key=False, youtube_first=True) is False
        assert wants_odesli([], yt_gap=True, yt_key=False, youtube_first=False) is False

    def test_the_condition_is_wired_into_the_song_loop(self):
        src = _SCRIPT.read_text()
        assert "yt_gap and yt_key and not args.youtube_first" in src
