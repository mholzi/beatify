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
    return not (youtube_first and yt_gap) and (bool(non_yt_gaps) or (yt_gap and yt_key))


class TestOdesliSkip:
    """Der Gratis-Vorabtreffer ist unter ``--youtube-first`` nicht gratis (#2301).

    Er kostet ``--odesli-sleep`` Sekunden pro Song, und die YouTube-Suche steht
    im selben Schleifendurchgang dahinter. Der Zeitdeckel nimmt also zuerst die
    Suche.

    **Der erste Anlauf war zu eng.** Er sprang nur, wenn YouTube die *einzige*
    Luecke war — und diese Bedingung ist auf diesem Katalog praktisch nie wahr:
    tomorrowland-top-1000 hat 779 YouTube-Luecken, allen 779 fehlt auch Tidal;
    musica-italiana 73 von 73. Die 04:00-Welle zaehlt **1063** Tracks ohne Tidal
    ueber 58 Playlists. Gemessen: 15:32-Lauf 24 Suchen, 19:32-Lauf mit dem engen
    Fix **4** Suchen und vier von fuenf Scheiben ohne eine einzige.

    Deshalb faellt Odesli jetzt fuer **jeden** Song mit YouTube-Luecke weg.
    """

    def test_a_youtube_gap_alone_skips_odesli_under_the_flag(self):
        # Der Normalfall im Katalog: YouTube fehlt, Tidal fehlt mit. Frueher
        # zwang das den 6-Sekunden-Aufruf, jetzt nicht mehr.
        assert wants_odesli([], yt_gap=True, yt_key=True, youtube_first=True) is False
        for extra in (
            ["tidal"],
            ["apple_music"],
            ["deezer"],
            ["apple_music", "deezer", "tidal"],
        ):
            assert (
                wants_odesli(extra, yt_gap=True, yt_key=True, youtube_first=True)
                is False
            ), extra

    def test_the_key_does_not_matter_under_the_flag(self):
        # Ohne API-Key gibt es zwar keine Suche, aber auch keinen Grund, in
        # einem YouTube-Lauf auf Odesli zu warten. Die Entscheidung haengt
        # allein an Flag und Luecke.
        assert (
            wants_odesli(["tidal"], yt_gap=True, yt_key=False, youtube_first=True)
            is False
        )

    def test_a_song_without_a_youtube_gap_is_untouched(self):
        # Das Flag sagt nur, welchen Job dieser Lauf macht. Songs ohne
        # YouTube-Luecke gehen ihren gewohnten Weg — sonst wuerde ein
        # YouTube-Lauf fremde Luecken stillschweigend ueberspringen.
        assert (
            wants_odesli(["tidal"], yt_gap=False, yt_key=True, youtube_first=True)
            is True
        )
        assert wants_odesli([], yt_gap=False, yt_key=True, youtube_first=True) is False

    def test_without_the_flag_everything_is_as_before(self):
        # Apple-, Deezer- und Tidal-Agenten rufen dasselbe Skript ohne das
        # Flag auf. Fuer sie darf sich nichts aendern.
        assert wants_odesli([], yt_gap=True, yt_key=True, youtube_first=False) is True
        assert (
            wants_odesli(["tidal"], yt_gap=True, yt_key=True, youtube_first=False)
            is True
        )
        assert wants_odesli([], yt_gap=True, yt_key=False, youtube_first=False) is False
        assert wants_odesli([], yt_gap=False, yt_key=True, youtube_first=False) is False

    def test_the_narrow_first_attempt_is_gone(self):
        # Die alte Bedingung darf nicht zurueckkommen: sie war syntaktisch
        # gueltig, gruen getestet — und feuerte auf echten Daten nie.
        src = _SCRIPT.read_text()
        assert "yt_gap and yt_key and not args.youtube_first" not in src

    def test_the_condition_is_wired_into_the_song_loop(self):
        src = _SCRIPT.read_text()
        assert "want_odesli = not (args.youtube_first and yt_gap) and (" in src


def is_skipped_outright(yt_gap: bool, youtube_first: bool) -> bool:
    """Die #2301-Vorab-Bedingung aus dem Song-Loop, isoliert nachgebildet."""
    return youtube_first and not yt_gap


class TestSkipSongsWithoutAYouTubeGap:
    """Die Mautstelle, an der zwei Fixes vorbeigefahren sind (#2301).

    Gemessen am 23.08.2026 in ``tomorrowland-top-1000``: die **46** Songs, die
    bereits eine YouTube-URI tragen, stehen auf den Indizes **0 bis 45**; die
    erste echte Luecke sitzt auf **46**. Allen 46 fehlt Tidal, also ist
    ``yt_gap`` fuer jeden von ihnen **falsch** und jeder kostet die vollen
    6 Sekunden ``--odesli-sleep`` — **276 von 300 Sekunden** einer Scheibe,
    verbraucht bevor die erste Luecke ueberhaupt erreicht ist. Die naechste
    Scheibe faengt bei 0 an und zahlt denselben Zoll; daher zwei leere
    Scheiben hintereinander, jedes Mal.

    Beide frueheren Anlaeufe haengen an ``yt_gap`` (#2310 Cursor-Sprung,
    #2320 Odesli-Verzicht) und konnten diese Songs **per Konstruktion** nie
    sehen.
    """

    def test_a_song_with_its_youtube_uri_is_skipped_under_the_flag(self):
        # Der Fall, um den es geht: nichts zu tun fuer diesen Lauf.
        assert is_skipped_outright(yt_gap=False, youtube_first=True) is True

    def test_a_song_with_a_youtube_gap_is_never_skipped(self):
        # Das ist die Arbeit, fuer die der Lauf existiert.
        assert is_skipped_outright(yt_gap=True, youtube_first=True) is False

    def test_without_the_flag_nothing_is_skipped(self):
        # Apple-, Deezer- und Tidal-Agenten rufen dasselbe Skript ohne das
        # Flag auf und muessen weiterhin JEDEN Song sehen.
        assert is_skipped_outright(yt_gap=False, youtube_first=False) is False
        assert is_skipped_outright(yt_gap=True, youtube_first=False) is False

    def test_the_skip_sits_before_the_cursor_fast_forward(self):
        # Reihenfolge ist wesentlich: der Cursor-Sprung fragt ``yt_gap`` ab
        # und kann diese Songs nicht abfangen. Stuende der neue Sprung
        # dahinter, aendert das nichts — stuende er hinter dem Odesli-Block,
        # waere der Zoll schon gezahlt.
        src = _SCRIPT.read_text()
        new_skip = src.index("if args.youtube_first and not yt_gap:")
        cursor_skip = src.index(
            "if args.youtube_first and yt_gap and this_global_idx < yt_state.cursor:"
        )
        odesli = src.index("---- Odesli (apple/tidal/deezer")
        assert new_skip < cursor_skip < odesli

    def test_the_condition_is_wired_into_the_song_loop(self):
        src = _SCRIPT.read_text()
        assert "if args.youtube_first and not yt_gap:" in src
