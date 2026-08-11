"""Das gemeinsame Verify-Gate (``scripts/uri_gate.py``) und seine zwei Nutzer.

Anlass ist eine Messung vom 11.08.2026: `backfill_provider_uris.py` — das Skript,
auf dem der **Apple-Backfill-Agent** läuft — konnte einen Remix nicht vom Original
unterscheiden. Sein `normalize_title` entfernt Klammerzusätze, bevor es
vergleicht, also sind ``The Night`` und ``The Night (Extended Mix)`` für sein Gate
identisch. Genau diese Regression hatte #1980 im Apple-Skript behoben, nur eben
im anderen Skript.

Die Tests hier sichern drei Dinge:

1. Das gemeinsame Modul verhält sich wie die Regeln, die aus `backfill_apple.py`
   dorthin gewandert sind.
2. Der All-rounder **benutzt** es und lehnt seitdem ab, was er vorher annahm.
3. Fehlt das Modul, degradiert er **laut** und arbeitet weiter.

Punkt 3 ist kein Beiwerk: eine stille Verschlechterung auf die schwächere Regel
ist genau die Fehlerart, die dieses Projekt mehrfach Arbeit gekostet hat.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gate = _load("uri_gate_under_test", _ROOT / "scripts" / "uri_gate.py")
allrounder = _load(
    "allrounder_under_test",
    _ROOT
    / ".claude"
    / "skills"
    / "provider-uri-backfill"
    / "scripts"
    / "backfill_provider_uris.py",
)


def _itunes_hit(title: str, artist: str, r_title: str, r_artist: str):
    """Ein einzelner iTunes-Treffer durch das Gate des All-rounders."""
    return allrounder._pick_itunes_match(
        [{"trackId": 123, "trackName": r_title, "artistName": r_artist}],
        title,
        artist,
        [],
    )


# --------------------------------------------------------- gemeinsames Modul
def test_gate_is_importable_from_the_allrounder() -> None:
    """Der All-rounder findet das Modul über die Verzeichnissuche.

    Der erste Entwurf riet eine Ebenenzahl (`parents[3]`) und landete auf
    `.claude/scripts/uri_gate.py`. Aufgefallen ist das nur, weil der Fallback
    eine Warnung schreibt — deshalb ist dieser Test hier.
    """
    assert allrounder._gate() is not None


@pytest.mark.parametrize(
    ("ours", "apple", "expected"),
    [
        ("Jackson 5", "The Jackson 5", True),
        ("MadHouse", "Mad'House", True),
        ("Run-DMC", "Run–D.M.C.", True),
        ("Jimi Hendrix", "The Jimi Hendrix Experience", True),
        ("Frozen - Cast", "Cast - Frozen", True),
        ("Zatox", "Tatanka, Zatox & Wild Motherfuckers", True),
        # Die zwei echten Fehltreffer aus dem Probe-Lauf vom 09.08.
        ("Paul Kalkbrenner", "The Parachute Club", False),
        ("Phil Collins", "Anton Zetterholm & Ensemble Stage Theater", False),
        ("Cast", "Johnny Cash & The Tennessee Two", False),
    ],
)
def test_artist_matches_unchanged_after_move(
    ours: str, apple: str, expected: bool
) -> None:
    assert gate.artist_matches(ours, apple) is expected


@pytest.mark.parametrize(
    ("bare", "decorated", "accepted"),
    [
        ("The Night", "The Night (2000 Remaster)", True),
        ("The Night", "The Night (Extended Mix)", False),
        ("One More Time", "One More Time (Short Radio Edit)", False),
        (
            "Zwei Seelen",
            'Zwei Seelen (aus "Die Schöne und das Biest" Film-Soundtrack)',
            True,
        ),
        ("Let It Go", "Let It Go (Motion Picture Version)", False),
    ],
)
def test_suffix_conflict_unchanged_after_move(
    bare: str, decorated: str, accepted: bool
) -> None:
    assert (gate.suffix_conflict(bare, decorated) is None) is accepted


# ------------------------------------------------- All-rounder benutzt es auch
@pytest.mark.parametrize(
    ("title", "hit_title", "accepted"),
    [
        # Was er schon vorher richtig machte
        ("The Night", "The Night", True),
        ("The Night", "The Night (2000 Remaster)", True),
        # Was er vorher FALSCH machte: alle drei wurden angenommen
        ("The Night", "The Night (Extended Mix)", False),
        ("One More Time", "One More Time (Short Radio Edit)", False),
        ("Hard Bass - Ran-D Remix", "Hard Bass (Xtreme Sound Mix)", False),
        # Herkunftsangabe ist kein Take-Merkmal
        (
            "Zwei Seelen",
            'Zwei Seelen (aus "Die Schöne und das Biest" deutscher Film-Soundtrack)',
            True,
        ),
    ],
)
def test_allrounder_itunes_gate_checks_suffixes(
    title: str, hit_title: str, accepted: bool
) -> None:
    got = _itunes_hit(title, "Noisecontrollers", hit_title, "Noisecontrollers")
    assert (got is not None) is accepted


@pytest.mark.parametrize(
    ("ours", "hit_artist", "accepted"),
    [
        # Diese beiden scheitern an der Editierdistanz und gehen erst mit den
        # Varianten durch — der eigentliche Zugewinn fuer den All-rounder.
        ("Run-DMC", "Run–D.M.C.", True),
        ("Jimi Hendrix", "The Jimi Hendrix Experience", True),
        # Was die Editierdistanz schon konnte, bleibt
        ("Jackson 5", "The Jackson 5", True),
        # Und die Fehltreffer bleiben draussen
        ("Paul Kalkbrenner", "The Parachute Club", False),
        ("Phil Collins", "Anton Zetterholm & Ensemble Stage Theater", False),
    ],
)
def test_allrounder_itunes_gate_uses_artist_variants(
    ours: str, hit_artist: str, accepted: bool
) -> None:
    got = _itunes_hit("Some Song", ours, "Some Song", hit_artist)
    assert (got is not None) is accepted


def test_allrounder_still_rejects_a_different_song() -> None:
    """Die Grundregel bleibt: ein anderer Titel wird nicht akzeptiert."""
    assert (
        _itunes_hit(
            "Sky and Sand",
            "Paul Kalkbrenner",
            "Völlig anderes Lied",
            "Paul Kalkbrenner",
        )
        is None
    )


# ------------------------------------------------------------ lauter Fallback
def test_missing_gate_degrades_loudly_and_keeps_working(monkeypatch, capsys) -> None:
    """Ohne Modul arbeitet der All-rounder weiter — aber sichtbar schwächer.

    Geprüft wird beides: dass eine Warnung auf stderr landet (und *warum* sie
    dort landet, steht im Text), und dass der Lauf nicht abbricht.
    """
    monkeypatch.setattr(allrounder, "_GATE", None, raising=False)
    monkeypatch.setattr(allrounder, "_GATE_WARNED", False, raising=False)
    monkeypatch.setattr(
        allrounder.importlib.util, "spec_from_file_location", lambda *a, **k: None
    )
    got = _itunes_hit(
        "The Night", "Noisecontrollers", "The Night (Extended Mix)", "Noisecontrollers"
    )
    err = capsys.readouterr().err
    assert "WARNUNG" in err
    assert "Remix" in err
    # Ohne Gate faellt er auf die alte, schwaechere Regel zurueck — genau das
    # macht die Warnung noetig.
    assert got is not None
    monkeypatch.setattr(allrounder, "_GATE", None, raising=False)
