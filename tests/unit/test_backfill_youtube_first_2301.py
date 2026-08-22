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
        # Bewusst NICHT umgedreht: der Odesli-Aufruf liefert den YouTube-Link
        # gratis mit (0 Quota). Liefe die Suche zuerst, wuerde jeder Treffer
        # 100 Quota-Einheiten kosten, die Odesli verschenkt haette.
        src = _SCRIPT.read_text()
        odesli_at = src.index("---- Odesli (apple/tidal/deezer")
        youtube_at = src.index("---- YouTube Data API search.list")
        assert odesli_at < youtube_at
