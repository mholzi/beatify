"""#2625 — the difficulty hints must stay templates, in every locale.

The scoring table in ``const.py`` was written out again as prose in
``wizard.js`` (under a "keep in sync" comment, the only safeguard there was) and
in ``admin.difficultyHint`` in six locale files. The admin copy had already
drifted: it promised "Hard: only close guesses score" where
``calculate_accuracy_score`` pays 3 points within ±2 years.

The frontend now composes the sentence from ``DIFFICULTY_SCORING`` and the
locale files carry only the wording around ``{placeholder}`` slots. That holds
only as long as no translator (or no future edit) puts a number back in — which
is what this file checks, in every language, including the ones nobody on the
team reads.

The companion checks live in ``www/js/__tests__/difficulty-hint-2625.test.js``,
which changes the table and requires the finished sentence to change with it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from custom_components.beatify.const import DIFFICULTY_SCORING, POINTS_WRONG

I18N = Path(__file__).parents[2] / "custom_components" / "beatify" / "www" / "i18n"
LOCALES = ["en", "de", "es", "fr", "nl", "it"]

# The band clause and the per-level shell that wraps it. Both are looked up by
# www/js/game-constants.js::difficultyHint.
BAND_KEYS = ("wizard.step4.difficultyBands", "wizard.step4.difficultyBandsNoNear")
SHELL_KEYS = (
    "wizard.step4.difficultyHintEasy",
    "wizard.step4.difficultyHintNormal",
    "wizard.step4.difficultyHintHard",
)
# Every number the sentence may name comes from one of these slots.
BAND_PLACEHOLDERS = ("{exact}", "{close}", "{closeRange}")
NEAR_PLACEHOLDERS = ("{near}", "{nearRange}")

_DIGIT = re.compile(r"\d")


def _load(locale: str) -> dict:
    return json.loads((I18N / f"{locale}.json").read_text(encoding="utf-8"))


def _get(data: dict, dotted: str):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@pytest.mark.parametrize("locale", LOCALES)
def test_every_locale_carries_the_templates(locale: str) -> None:
    data = _load(locale)
    for key in BAND_KEYS + SHELL_KEYS:
        assert isinstance(_get(data, key), str), f"{locale}.json is missing {key}"


def _without_slots(text: str) -> str:
    """The template's own words, with every `{placeholder}` removed."""
    return re.sub(r"\{[A-Za-z]+\}", "", text)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_band_clause_names_no_number_of_its_own(locale: str) -> None:
    """A digit outside a placeholder is a promise the code cannot keep."""
    text = _get(_load(locale), "wizard.step4.difficultyBands")
    assert not _DIGIT.search(_without_slots(text)), (
        f"{locale}.json difficultyBands states a number instead of a "
        f"placeholder: {text!r}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_no_near_clause_only_ever_spells_out_the_zero(locale: str) -> None:
    """ "…otherwise 0" is POINTS_WRONG, which is 0 by definition, not a band."""
    assert POINTS_WRONG == 0
    text = _get(_load(locale), "wizard.step4.difficultyBandsNoNear")
    stray = set(_DIGIT.findall(_without_slots(text))) - {"0"}
    assert not stray, (
        f"{locale}.json difficultyBandsNoNear states a number instead of a "
        f"placeholder: {text!r}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_band_clause_uses_every_slot_it_should(locale: str) -> None:
    data = _load(locale)
    with_near = _get(data, "wizard.step4.difficultyBands")
    without_near = _get(data, "wizard.step4.difficultyBandsNoNear")
    for slot in BAND_PLACEHOLDERS:
        assert slot in with_near, f"{locale}.json difficultyBands is missing {slot}"
        assert slot in without_near, (
            f"{locale}.json difficultyBandsNoNear is missing {slot}"
        )
    for slot in NEAR_PLACEHOLDERS:
        assert slot in with_near, f"{locale}.json difficultyBands is missing {slot}"
        # The no-near variant deliberately does not mention the near band.
        assert slot not in without_near, (
            f"{locale}.json difficultyBandsNoNear talks about the near band "
            f"it exists to omit: {without_near!r}"
        )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_shells_only_wrap_the_clause(locale: str) -> None:
    """The per-level string carries the flavour word and nothing numeric."""
    data = _load(locale)
    for key in SHELL_KEYS:
        text = _get(data, key)
        assert "{bands}" in text, f"{locale}.json {key} never renders the bands"
        assert not _DIGIT.search(text), (
            f"{locale}.json {key} states a number of its own: {text!r}"
        )


@pytest.mark.parametrize("locale", LOCALES)
def test_the_drifted_admin_string_is_gone(locale: str) -> None:
    """`admin.difficultyHint` was the copy that had already gone wrong.

    The admin panel renders the same derived per-level hint as the wizard now,
    so there is no separate string left to disagree with the code.
    """
    assert _get(_load(locale), "admin.difficultyHint") is None


def test_the_hard_level_is_the_one_without_a_near_band() -> None:
    """Pins the assumption the two band templates exist for.

    ``difficultyHint`` picks the no-near wording from the table, not from the
    level name — but if some day no level has an empty near band, the second
    template is dead weight and this is the reminder.
    """
    without_near = [
        level
        for level, scoring in DIFFICULTY_SCORING.items()
        if scoring["near_range"] <= 0 or scoring["near_points"] <= 0
    ]
    assert without_near == ["hard"], without_near
