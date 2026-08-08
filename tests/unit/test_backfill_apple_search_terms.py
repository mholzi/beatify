"""Two-stage search-term construction in ``scripts/backfill_apple.py``.

The gate can only judge what the search returns. Until 2026-08-08 the query was
the primary artist plus the **full** title, and iTunes ranks on the whole
string — so a distinctive parenthetical outweighed the song title.

The case this was built from is real, not invented: searching
``Sub Zero Project Stand Strong (Q-BASE 2017 Hangar OST)`` returned two
``E-Force – Salute (Q-Base 2018 Hangar Ost)`` rows in ``de`` and ``us``, and the
correct recording did not appear at all. It was therefore recorded as
``artist 'E-Force' != 'Sub Zero Project'`` — a rejection that reads like "Apple
credits it differently" but means "the search returned something else".

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

search_terms = backfill_apple.search_terms
strip_parentheticals = backfill_apple.strip_parentheticals


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Stand Strong (Q-BASE 2017 Hangar OST)", "Stand Strong"),
        ("Strike As A Die Hard (Q-Base Anthem 2017)", "Strike As A Die Hard"),
        ("Dragonblood (Defqon.1 Chile Anthem 2016)", "Dragonblood"),
        # Two groups and a dangling dash between them — the naive strip leaves
        # "Lost in Dreams -" and carries the dash into the query.
        (
            "Lost in Dreams (Q-BASE 2017 Warehouse OST) - (D-Fence Remix)",
            "Lost in Dreams",
        ),
        ("The Night [Extended Mix]", "The Night"),
        # Nothing to strip — must come back untouched.
        ("Aftermath", "Aftermath"),
        ("", ""),
    ],
)
def test_strip_parentheticals(title: str, expected: str) -> None:
    assert strip_parentheticals(title) == expected


def test_second_term_drops_the_parenthetical() -> None:
    track = {"artist": "Sub Zero Project", "title": "Stand Strong (Q-BASE 2017 Hangar OST)"}
    assert search_terms(track) == [
        "Sub Zero Project Stand Strong (Q-BASE 2017 Hangar OST)",
        "Sub Zero Project Stand Strong",
    ]


def test_stage_one_is_unchanged() -> None:
    """The historical term stays first, so an existing hit cannot move."""
    for track in (
        {"artist": "Zatox", "title": "Hard Bass - Ran-D Remix"},
        {"artist": "Sub Zero Project", "title": "Stand Strong (Q-BASE 2017 Hangar OST)"},
        {"artist": "Artifact", "title": "Aftermath"},
    ):
        first = search_terms(track)[0]
        expected = (
            f"{backfill_apple.primary_artist(track['artist'])} {track['title']}".strip()
        )
        assert first == expected


def test_no_parenthetical_means_no_second_request() -> None:
    """Titles without a group must not cost an extra query."""
    assert search_terms({"artist": "Artifact", "title": "Aftermath"}) == [
        "Artifact Aftermath"
    ]


def test_only_the_lead_artist_is_searched() -> None:
    """Unchanged behaviour: search results carry the lead artist only."""
    track = {"artist": "Tatanka, Zatox & Wild Motherfuckers", "title": "Bassleader (Anthem 2012)"}
    terms = search_terms(track)
    assert terms[0].startswith("Tatanka ")
    assert terms[-1] == "Tatanka Bassleader"


def test_a_title_that_is_only_a_parenthetical_yields_one_term() -> None:
    """Stripping must not produce an artist-only query that matches anything."""
    track = {"artist": "Frontliner", "title": "(Defqon.1 Chile Anthem 2016)"}
    assert search_terms(track) == ["Frontliner (Defqon.1 Chile Anthem 2016)"]


def test_no_artist_and_no_title_yields_nothing() -> None:
    assert search_terms({"artist": "", "title": ""}) == []
