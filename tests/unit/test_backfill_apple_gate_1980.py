"""Gate rules of ``scripts/backfill_apple.py`` (#1980).

These cover the two matcher rules added on 2026-08-05, both of which were found
against real iTunes responses rather than invented:

* **Suffix comparison.** ``title_similarity`` also compares a
  parenthetical-stripped form, so a one-sided suffix costs no similarity at all.
  ``The Night`` and ``The Night (Extended Mix)`` therefore both score 1.00 —
  no threshold can separate them, so the suffix has to be inspected directly.
  Without this rule a 20-track sample of ``divorced-dad-rock`` accepted two live
  recordings and one censored edit as if they were the studio versions.

* **Artist membership.** Apple orders multi-artist credits differently than the
  catalogue ("Tatanka, Zatox & Wild Motherfuckers" for our "Zatox"), which the
  old lead-vs-lead equality rejected.

``scripts/`` is not a package, so the module is loaded by path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_apple.py"
_spec = importlib.util.spec_from_file_location("backfill_apple", _SCRIPT)
backfill_apple = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_apple)

artist_set = backfill_apple.artist_set
evaluate = backfill_apple.evaluate
normalise = backfill_apple.normalise
primary_artist = backfill_apple.primary_artist
suffix_conflict = backfill_apple.suffix_conflict


@pytest.mark.parametrize(
    ("catalogue", "apple", "expected"),
    [
        # A suffix naming a different take must be caught — both score 1.00.
        ("The Night", "The Night (Extended Mix)", "extended mix"),
        (
            "Strike As A Die Hard (Q-Base Anthem 2017)",
            "Strike as a Die Hard (Q - Base Anthem 2017) [Pro Mix]",
            "pro mix",
        ),
        ("Smooth Criminal", "Smooth Criminal (Live)", "live"),
        (
            "Be Yourself",
            "Be Yourself (Live from Sessions@AOL Music)",
            "live from sessions aol music",
        ),
        ("Crazy Bitch", "Crazy B*tch (Amended Version)", "amended version"),
        # Same words, different punctuation — not a conflict.
        ("The Afterlife - Radio Edit", "The Afterlife (Radio Edit)", None),
        ("Let Go (Album Edit)", "Let Go (Album Edit)", None),
        ("Hemorrhage (In My Hands)", "Hemorrhage (In My Hands)", None),
        # Recording-neutral suffixes stay allowed, which is why the rule exists
        # as an allowlist rather than a blanket ban.
        ("Kryptonite", "Kryptonite (2000 Remaster)", None),
        ("Wonderwall", "Wonderwall (Remastered)", None),
        ("Last Resort", "Last Resort (Explicit)", None),
        # A featured guest is not a different recording.
        ("Teenage Dirtbag", "Teenage Dirtbag (feat. Bobby John)", None),
        ("Drift Away", "Drift Away", None),
    ],
)
def test_suffix_conflict(catalogue: str, apple: str, expected: str | None) -> None:
    assert suffix_conflict(catalogue, apple) == expected


@pytest.mark.parametrize(
    ("catalogue", "apple", "accepted"),
    [
        # Apple reorders the credit; the artist is present, just not first.
        ("Zatox", "Tatanka, Zatox & Wild Motherfuckers", True),
        # Apple moves the featured guest into the title, so only the *primary*
        # catalogue artist may be required — not the whole catalogue set.
        (
            "Harris & Ford, BassWar & CaoX, Bobby John",
            "Harris & Ford & BassWar & CaoX",
            True,
        ),
        ("Endymion", "Endymion & GLDY LX", True),
        ("Noisecontrollers", "Noisecontrollers", True),
        # Genuinely different artists stay rejected.
        ("Sub Zero Project", "E-Force", False),
        ("Artifact", "Saif Shraideh", False),
    ],
)
def test_artist_membership(catalogue: str, apple: str, accepted: bool) -> None:
    # Ruft seit #2030 `artist_matches` statt den alten Ausdruck nachzubauen:
    # das Gate benutzt `artist_set` nicht mehr, und ein Test, der die frühere
    # Formel prüft, schützt den Produktionspfad nicht. Alle sechs Erwartungen
    # gelten unter der neuen Regel unverändert.
    assert backfill_apple.artist_matches(primary_artist(catalogue), apple) is accepted


def test_evaluate_rejects_extended_mix_with_matching_artist_and_year() -> None:
    """The regression that motivated #1980: everything else about this match is
    perfect, so only rule 4 can stop it."""
    track = {"artist": "Noisecontrollers", "title": "The Night", "year": 2018}
    result = {
        "artistName": "Noisecontrollers",
        "trackName": "The Night (Extended Mix)",
        "releaseDate": "2018-06-01T00:00:00Z",
    }
    accepted, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is False
    assert reason.startswith("suffix ")
    assert "extended mix" in reason


def test_evaluate_accepts_plain_version_of_same_track() -> None:
    track = {"artist": "Noisecontrollers", "title": "The Night", "year": 2018}
    result = {
        "artistName": "Noisecontrollers",
        "trackName": "The Night",
        "releaseDate": "2018-06-01T00:00:00Z",
    }
    accepted, _ = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is True


def test_evaluate_accepts_reordered_multi_artist_credit() -> None:
    track = {"artist": "Zatox", "title": "Hard Bass", "year": 2014}
    result = {
        "artistName": "Tatanka, Zatox & Wild Motherfuckers",
        "trackName": "Hard Bass",
        "releaseDate": "2014-03-01T00:00:00Z",
    }
    accepted, _ = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is True


def test_evaluate_still_rejects_a_different_artist() -> None:
    track = {"artist": "Artifact", "title": "Aftermath", "year": 2019}
    result = {
        "artistName": "Saif Shraideh",
        "trackName": "Aftermath",
        "releaseDate": "2019-01-01T00:00:00Z",
    }
    accepted, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    assert accepted is False
    assert reason.startswith("artist ")


def test_reject_reason_kinds_stay_parseable() -> None:
    """The wave counter derives its histogram key from the second word of the
    reason (``de: suffix ...`` -> ``suffix``). A reason phrased differently
    would silently produce a junk bucket."""
    track = {"artist": "Noisecontrollers", "title": "The Night", "year": 2018}
    result = {
        "artistName": "Noisecontrollers",
        "trackName": "The Night (Extended Mix)",
        "releaseDate": "2018-06-01T00:00:00Z",
    }
    _, reason = evaluate(track, result, title_threshold=0.87, year_tolerance=1)
    detail = f"de: {reason}"
    assert detail.split(" ", 1)[1].split(" ")[0] == "suffix"
