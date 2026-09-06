"""#2624 — the reveal's year thresholds must stay the scoring table's.

``player-reveal.js`` used to split "so close" from "way off" at fixed distances
of 2 and 5 years while the server awarded points from ``DIFFICULTY_SCORING``
(``close_range`` 7/3/2, ``near_range`` 10/5/0). The two only agreed on Normal:
on Easy a six-year miss scored 5 points under the "way off" face, on Hard a
three-year miss scored nothing under "so close".

The frontend now classifies through ``classifyYearsOff`` in ``player-utils.js``,
which carries a copy of the table — the browser cannot import ``const.py``. A
copy is only safe while something fails when it drifts, and that is this test:
it parses the JS literal and compares it to the Python dict, key for key and
number for number.

The precedent it fixes is right next door: ``wizard.js`` has carried a
"keep in sync" comment over the same numbers since Story 14.1, with nothing
behind the comment.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.beatify.const import DIFFICULTY_DEFAULT, DIFFICULTY_SCORING

PLAYER_UTILS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "js"
    / "player-utils.js"
)

_TABLE = re.compile(r"export\s+var\s+DIFFICULTY_SCORING\s*=\s*\{(.*?)\n\};", re.DOTALL)
_DEFAULT = re.compile(r"export\s+var\s+DIFFICULTY_DEFAULT\s*=\s*'([a-z]+)'")


def _js_table() -> dict[str, dict[str, int]]:
    """Read the DIFFICULTY_SCORING object literal out of player-utils.js."""
    src = PLAYER_UTILS.read_text(encoding="utf-8")
    match = _TABLE.search(src)
    assert match, "DIFFICULTY_SCORING literal not found in player-utils.js"

    body = "{" + match.group(1) + "}"
    # JS object literal -> JSON: quote the bare keys, drop the trailing commas.
    body = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', body)
    body = re.sub(r",(\s*[}\]])", r"\1", body)
    return json.loads(body)


def test_frontend_table_matches_const_py() -> None:
    """Every difficulty, every band, same numbers on both sides."""
    assert _js_table() == DIFFICULTY_SCORING


def test_frontend_default_difficulty_matches() -> None:
    """An unknown difficulty must fall back to the same level in both."""
    src = PLAYER_UTILS.read_text(encoding="utf-8")
    match = _DEFAULT.search(src)
    assert match, "DIFFICULTY_DEFAULT not found in player-utils.js"
    assert match.group(1) == DIFFICULTY_DEFAULT


def test_no_hardcoded_year_thresholds_left_in_the_reveal() -> None:
    """The reveal must not re-derive a band from a literal year count.

    Guard against the exact shape that shipped the bug: a comparison of
    ``years_off`` (or the duel's ``yearsOff``) against a bare number.
    """
    reveal = (PLAYER_UTILS.parent / "player-reveal.js").read_text(encoding="utf-8")
    offenders = re.findall(r"yearsOff\s*<=?\s*\d+", reveal)
    assert not offenders, (
        f"hard-coded year threshold(s) back in player-reveal.js: {offenders}"
    )
