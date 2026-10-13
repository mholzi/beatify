"""#3158 — every end-screen award has a title and every value a unit.

``scoring.py`` emits an award as ``_award(id, emoji, name, value, value_label)``.
The frontend titles it with ``t('superlatives.' + id)`` and looks the unit up
in ``AWARD_VALUE_UNITS`` (``www/js/utils.js``). Both lookups are dynamic, so the
i18n key test (#2507) tolerates the whole ``superlatives.`` prefix and saw
neither gap: ``last_one_standing`` shipped without a title in any locale, and
five of the fourteen labels rendered as a bare number.

This is the cross-reference: the award calls are read from scoring.py's syntax
tree, the table from utils.js, and both are checked against all six locales.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[2] / "custom_components" / "beatify"
SCORING = ROOT / "game" / "scoring.py"
UTILS_JS = ROOT / "www" / "js" / "utils.js"
I18N = ROOT / "www" / "i18n"
LOCALES = ("en", "de", "es", "fr", "it", "nl")

_TABLE = re.compile(r"var AWARD_VALUE_UNITS = \{\n(.*?)\n    \};", re.S)
_ROW = re.compile(r"^\s*(\w+): \{(.*)\},?$", re.M)
_KEY = re.compile(r"'superlatives\.(\w+)'")


def _awards() -> list[tuple[str, str]]:
    """(award id, value label) for every ``_award(...)`` call in scoring.py."""
    found = []
    for node in ast.walk(ast.parse(SCORING.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_award"
        ):
            award_id, label = node.args[0], node.args[4]
            assert isinstance(award_id, ast.Constant), ast.dump(node)
            assert isinstance(label, ast.Constant), ast.dump(node)
            found.append((award_id.value, label.value))
    return found


def _unit_table() -> dict[str, list[str]]:
    """value label -> the ``superlatives`` leaves its row in utils.js names."""
    block = _TABLE.search(UTILS_JS.read_text(encoding="utf-8"))
    assert block, "AWARD_VALUE_UNITS not found in utils.js"
    return {label: _KEY.findall(row) for label, row in _ROW.findall(block.group(1))}


def _superlatives(locale: str) -> dict:
    data = json.loads((I18N / f"{locale}.json").read_text(encoding="utf-8"))
    return data["superlatives"]


def test_the_scan_actually_finds_the_awards():
    """Guard the guard: a renamed helper would make the rest vacuously pass."""
    awards = _awards()
    assert len(awards) >= 14, awards
    assert ("last_one_standing", "eliminated") in awards
    assert ("comeback_king", "improvement") in awards
    assert len(_unit_table()) >= 14


def test_every_award_id_has_a_title_in_every_locale():
    missing = [
        f"{locale}: superlatives.{award_id}"
        for locale in LOCALES
        for award_id, _ in _awards()
        if not str(_superlatives(locale).get(award_id, "")).strip()
    ]
    assert not missing, missing


def test_every_value_label_has_a_row_in_the_unit_table():
    table = _unit_table()
    missing = sorted({label for _, label in _awards()} - set(table))
    assert not missing, f"scoring.py emits labels utils.js has no unit for: {missing}"


def test_the_unit_table_has_no_row_scoring_never_emits():
    stale = sorted(set(_unit_table()) - {label for _, label in _awards()})
    assert not stale, f"AWARD_VALUE_UNITS rows without an award: {stale}"


def test_every_unit_key_exists_in_every_locale():
    missing = []
    for label, leaves in _unit_table().items():
        assert leaves, f"{label}: row names no superlatives key"
        for locale in LOCALES:
            block = _superlatives(locale)
            missing += [
                f"{locale}: superlatives.{leaf} ({label})"
                for leaf in leaves
                if not str(block.get(leaf, "")).strip()
            ]
    assert not missing, missing


def test_neither_screen_keeps_its_own_switch():
    """The two switches drifted apart once; the table is the only place."""
    for name in ("dashboard.js", "player-end.js"):
        source = (ROOT / "www" / "js" / name).read_text(encoding="utf-8")
        assert "switch (award.value_label)" not in source, name
        assert "utils.awardValueText(award)" in source, name
