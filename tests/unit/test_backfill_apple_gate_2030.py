"""Artist-Varianten und Soundtrack-Herkunft im Gate von ``scripts/backfill_apple.py``.

Alle Faelle hier stammen aus dem Probe-Lauf vom 09.08.2026 ueber 861 fehlende
Apple-URIs in 54 Playlists (``/tmp/beatify-2030-probe.log``), nicht aus der
Vorstellung. Von 137 Ablehnungen waren:

* 56 Jahr (41 %) — nicht Gegenstand dieser Tests, siehe #2030 und die offene
  Jahres-Konvention,
* 38 Artist (28 %) — jede davon eine Schreibweise, keine andere Band,
* 19 Suffix (14 %), davon 4 dieselbe deutsche Soundtrack-Zuschreibung.

Der zweite Block ist deshalb so wichtig wie der erste: zwei der 38
Artist-Ablehnungen waren **echte Fehltreffer** von iTunes. Eine Lockerung, die
die durchlaesst, ist schlechter als die alte Strenge.

``scripts/`` ist kein Package, das Modul wird daher per Pfad geladen.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_apple.py"
_spec = importlib.util.spec_from_file_location("backfill_apple", _SCRIPT)
backfill_apple = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_apple)

artist_matches = backfill_apple.artist_matches
suffix_conflict = backfill_apple.suffix_conflict
evaluate = backfill_apple.evaluate


# --------------------------------------------------------------- Artist: JA
@pytest.mark.parametrize(
    ("ours", "apple"),
    [
        # Fuehrender Artikel — 2x im Probe-Lauf
        ("The Jackson 5", "Jackson 5"),
        ("Jackson 5", "The Jackson 5"),
        # Apostroph
        ("MadHouse", "Mad'House"),
        ("Mad'House", "MadHouse"),
        # Punkte in der Abkuerzung. Der angehaengte Remixer ("& Jason Nevins")
        # wird schon von `primary_artist` abgeschnitten — der End-to-End-Test
        # unten belegt diesen Pfad; hier steht deshalb der primaere Kuenstler.
        ("Run-DMC", "Run–D.M.C."),
        # Umgestellte Mehrfach-Credits
        ("Frozen - Cast", "Cast - Frozen"),
        # Unser Kuenstler steckt als zusammenhaengender Token-Lauf im Apple-Credit
        ("Jimi Hendrix", "The Jimi Hendrix Experience"),
        # Bestehendes Verhalten darf nicht kaputtgehen: Membership im Mehrfach-Credit
        ("Zatox", "Tatanka, Zatox & Wild Motherfuckers"),
    ],
)
def test_artist_variants_accepted(ours: str, apple: str) -> None:
    assert artist_matches(ours, apple) is True


# -------------------------------------------------------------- Artist: NEIN
@pytest.mark.parametrize(
    ("ours", "apple"),
    [
        # Die zwei echten Fehltreffer aus dem Probe-Lauf. Sie sind der Grund,
        # warum die Containment-Regel zwei Token verlangt und einseitig ist.
        ("Paul Kalkbrenner", "The Parachute Club"),
        (
            "Phil Collins",
            "Anton Zetterholm, Elisabeth Hübert & Ensemble Stage Theater Neue Flora",
        ),
        # Ein einzelnes Token darf NIE per Containment greifen, sonst passt
        # "Cast" in jeden zweiten Soundtrack-Credit.
        ("Cast", "Johnny Cash & The Tennessee Two"),
        # Diakritika bleiben unterscheidend (Kommentar in `normalise`).
        ("Böhse Onkelz", "Bohse Onkel"),
        # Leere Seite
        ("", "Irgendwer"),
    ],
)
def test_artist_mismatches_still_rejected(ours: str, apple: str) -> None:
    assert artist_matches(ours, apple) is False


def test_artist_containment_is_one_directional() -> None:
    """Apples Credit darf nicht in unserem stecken, nur umgekehrt.

    Sonst wuerde ein zu knapper Apple-Credit ("Cast") auf einen langen
    Katalog-Eintrag passen und die Pruefung waere in beide Richtungen weich.
    """
    assert (
        artist_matches("The Jimi Hendrix Experience", "Jimi Hendrix Experience") is True
    )
    assert artist_matches("Die Toten Hosen und Freunde", "Freunde") is False


# ----------------------------------------------------------- Soundtrack-Suffix
@pytest.mark.parametrize(
    "apple_title",
    [
        'Zwei Seelen (aus "Die Schöne und das Biest" deutscher Film-Soundtrack)',
        'Endlich sehe ich das Licht'
        ' (aus "Rapunzel – Neu verföhnt" deutscher Film-Soundtrack)',
        'Ich kann es kaum erwarten (aus "Hercules" deutscher Film-Soundtrack)',
        'Sei ein Mann (aus "Mulan" deutscher Film-Soundtrack)',
        "Circle of Life (from The Lion King Soundtrack)",
        "Let It Go (Original Motion Picture Soundtrack)",
    ],
)
def test_soundtrack_origin_is_neutral(apple_title: str) -> None:
    """Eine Herkunftsangabe sagt WO die Aufnahme herkommt, nicht WELCHE es ist."""
    bare = apple_title.split(" (")[0]
    assert suffix_conflict(bare, apple_title) is None


@pytest.mark.parametrize(
    "apple_title",
    [
        # Version statt Herkunft — kann sehr wohl eine andere Einspielung sein.
        "Let It Go (Motion Picture Version)",
        "One More Time (Short Radio Edit)",
        "Hard Bass (Extended Mix)",
        # "soundtrack" allein, ohne "aus"/"from", ist keine Herkunftsangabe.
        "Some Song (Soundtrack)",
    ],
)
def test_version_suffixes_still_rejected(apple_title: str) -> None:
    bare = apple_title.split(" (")[0]
    assert suffix_conflict(bare, apple_title) is not None


# ------------------------------------------------------------- Gate insgesamt
def test_gate_accepts_article_difference_end_to_end() -> None:
    track = {"artist": "The Jackson 5", "title": "I'll Be There", "year": 1970}
    result = {
        "artistName": "Jackson 5",
        "trackName": "I'll Be There",
        "releaseDate": "1970-08-28T07:00:00Z",
    }
    accepted, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is True, reason


def test_gate_still_rejects_the_parachute_club_end_to_end() -> None:
    """Der Fehltreffer bleibt ein Fehltreffer, auch mit den neuen Varianten."""
    track = {"artist": "Paul Kalkbrenner", "title": "Sky and Sand", "year": 2009}
    result = {
        "artistName": "The Parachute Club",
        "trackName": "Sky and Sand",
        "releaseDate": "1983-01-01T07:00:00Z",
    }
    accepted, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is False
    assert "artist" in reason


def test_gate_accepts_dotted_abbreviation_with_appended_remixer() -> None:
    """Der ganze Pfad, nicht nur der Vergleich.

    Unsere Seite fuehrt ``Run-DMC & Jason Nevins``; ``primary_artist`` schneidet
    den Remixer ab, die punktfreie Variante faltet Apples ``Run–D.M.C.``. Der
    Test faehrt bewusst ``evaluate``, weil genau das Zusammenspiel der beiden
    Schritte im Probe-Lauf gescheitert ist.
    """
    track = {
        "artist": "Run-DMC & Jason Nevins",
        "title": "It's Like That",
        "year": 1997,
    }
    result = {
        "artistName": "Run–D.M.C.",
        "trackName": "It's Like That",
        "releaseDate": "1997-03-25T08:00:00Z",
    }
    accepted, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is True, reason
