"""#2930 — game_views and library_views must not import each other again.

The two modules used to form a cycle, held open by imports placed inside
functions. That is not a style question: neither import could be lifted to the
top of its file without raising ImportError while Home Assistant loads the
integration, so the most ordinary tidy-up in the codebase — moving an import to
where imports go — broke startup, and broke it at HA boot rather than in review.

It also hid a live defect. ``LibraryPlaylistGenerateView`` unpacked three of the
five values ``parse_library_config`` returns and raised ``ValueError`` on every
call (#2935); the call site imported the helper inside the function, so the
mismatch was in nobody's view when the helper grew.

The cycle is gone because the two things that crossed it moved to where they
belong: the host's Store-backed settings to ``server/setup_state.py``, and the
config parser to ``library/config.py``. This test keeps it gone. It reads the
source rather than importing, so it states the rule even when the modules cannot
be imported outside Home Assistant.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BEATIFY = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"

#: Pairs that must never import one another, in either direction.
FORBIDDEN = [
    ("server/game_views.py", "library_views"),
    ("server/library_views.py", "game_views"),
]


@pytest.mark.parametrize(("module", "forbidden"), FORBIDDEN)
def test_no_edge_between_the_two_view_modules(module: str, forbidden: str):
    src = (BEATIFY / module).read_text(encoding="utf-8")
    hits = re.findall(rf"^\s*from[^\n]*\b{forbidden}\b[^\n]*import", src, re.M)
    assert not hits, (
        f"{module} imports {forbidden} again: {hits}. "
        "The cycle these two formed could only be dodged with imports inside "
        "functions, which is how #2935 stayed invisible."
    )


def test_the_shared_pieces_live_outside_both():
    """Where the two things that used to cross the cycle ended up."""
    setup_state = (BEATIFY / "server" / "setup_state.py").read_text(encoding="utf-8")
    assert "async_load_game_output_settings" in setup_state
    assert "async_save_game_output_settings" in setup_state

    config = (BEATIFY / "library" / "config.py").read_text(encoding="utf-8")
    assert "def parse_library_config" in config


def test_the_year_gates_have_one_definition():
    """They existed twice, once in each side of the cycle.

    Two copies of the same mapping in two modules that could not import each
    other is what the cycle cost in practice, so the single definition is worth
    holding onto.
    """
    defined_in = [
        path.relative_to(BEATIFY).as_posix()
        for path in BEATIFY.rglob("*.py")
        if re.search(
            r"^YEAR_GATES\s*=|^_LIBRARY_YEAR_GATES\s*=",
            path.read_text(encoding="utf-8"),
            re.M,
        )
    ]
    assert defined_in == ["library/config.py"], defined_in
