"""#2695 — a locale key can exist and still be English.

``test_i18n_locale_parity`` compares the *key sets* of the six UI locale files
and passes as long as every key is present everywhere. That is exactly how the
whole Crate Digger library shipped English to Spanish, French and Dutch hosts
for three weeks: all 1324 keys were there, 58 of them carrying the English
sentence verbatim. Nothing compared the values.

This guard does. For every non-``en`` locale it flags any multi-word value that
is byte-identical to the English one — the fingerprint of a copy-paste that was
never translated. Single-word values are exempt on purpose: "Balanced",
"Lobby", "Countdown", "Genres" and friends really are the same word in several
of these languages, and flagging them would drown the signal.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

I18N_DIR = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "i18n"
)
CANONICAL = "en"
LOCALES = ["de", "es", "fr", "nl", "it"]

# Values that are legitimately identical in every language: product and brand
# names, and the two game modes Beatify deliberately keeps in English. Match is
# case-insensitive, so "Sudden Death" covers the shouted "SUDDEN DEATH" too.
# Keep this list short — every entry is a value no locale will ever translate.
ALLOWED_IDENTICAL = {
    "apple music",
    "beatify - dashboard",
    "beatify admin",
    "beatify analytics",
    "beatify team",
    "billboard hot 100",
    "crate digger",  # the library feature's product name
    "smart playlist mixer",  # the mix feature's product name
    "spotify playlist url",
    "sudden death",  # kept in English in every locale, like "Highlights"
    "uk charts",
    "youtube music",
}

# `{name}` / `{count}` placeholders are locale-independent, so they must not
# make a one-word string look like a sentence: "Top {p}%" and "{count} playlists"
# are single-word values.
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
# A token counts as a word only if it holds a run of two or more letters. That
# keeps "R&B", "×2", "%", "#" and bare emoji out of the count, so "Soul / R&B"
# and "🎬 Highlights" stay one-word values.
_HAS_WORD = re.compile(r"[^\W\d_]{2,}")


def _flatten(obj: dict, prefix: str = "") -> dict[str, str]:
    """Return {dotted key: value} for every leaf string in a translation dict."""
    flat: dict[str, str] = {}
    for key, value in obj.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, dotted))
        elif isinstance(value, str):
            flat[dotted] = value
    return flat


def _load(locale: str) -> dict[str, str]:
    return _flatten(
        json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))
    )


def _is_multi_word(value: str) -> bool:
    tokens = _PLACEHOLDER.sub(" ", value).split()
    return sum(1 for token in tokens if _HAS_WORD.search(token)) > 1


def _untranslated(locale: str) -> list[str]:
    english = _load(CANONICAL)
    return sorted(
        key
        for key, value in _load(locale).items()
        if value == english.get(key)
        and _is_multi_word(value)
        and value.strip().lower() not in ALLOWED_IDENTICAL
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_no_english_value_survives_into_a_locale(locale: str) -> None:
    leftovers = _untranslated(locale)
    assert not leftovers, (
        f"{locale}.json carries {len(leftovers)} multi-word value(s) still "
        f"identical to {CANONICAL}.json — translate them, or add the value to "
        f"ALLOWED_IDENTICAL if it is a proper noun: "
        + json.dumps(
            {key: _load(locale)[key] for key in leftovers},
            indent=2,
            ensure_ascii=False,
        )
    )


class TestTheWordCountRule:
    """Guard the guard: a too-eager or too-lax rule makes the test useless."""

    @pytest.mark.parametrize(
        "value",
        [
            "Balanced",  # one word — same in several locales, must not flag
            "Top {p}%",  # placeholder + one word
            "{count} playlists",
            "Soul / R&B",
            "🎬 Highlights",
            "Hip-Hop",
            "https://open.spotify.com/playlist/...",
        ],
    )
    def test_single_word_values_are_exempt(self, value: str) -> None:
        assert not _is_multi_word(value)

    @pytest.mark.parametrize(
        "value",
        [
            "Song familiarity",
            "Crowd-pleasers are the point",
            "Library ready: {usable} of {total} songs game-ready.",
            "Entire library (can take days)",
        ],
    )
    def test_real_sentences_are_checked(self, value: str) -> None:
        assert _is_multi_word(value)

    def test_the_allow_list_only_holds_values_that_exist(self) -> None:
        """A stale entry would quietly widen the exemption. Every allowed value
        must still be a real English string somewhere in en.json."""
        english = {v.strip().lower() for v in _load(CANONICAL).values()}
        stale = sorted(ALLOWED_IDENTICAL - english)
        assert not stale, f"ALLOWED_IDENTICAL entries no longer in en.json: {stale}"


class TestTheCrateDiggerRegression:
    """The 58 values from the report, spot-checked where a host would see them."""

    KEYS = (
        "admin.library.statusReady",
        "admin.library.difficulty",
        "admin.library.diffEasy",
        "admin.library.scanAll",
        "wizard.step3lib.sub",
    )

    @pytest.mark.parametrize("locale", LOCALES)
    def test_the_library_is_translated_everywhere(self, locale: str) -> None:
        english = _load(CANONICAL)
        translations = _load(locale)
        for key in self.KEYS:
            assert translations[key] != english[key], f"{locale}.json: {key}"
