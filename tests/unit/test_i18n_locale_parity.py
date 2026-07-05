"""Key-parity guard for the in-app UI locale files (#1730).

``custom_components/beatify/www/i18n/en.json`` is the canonical source of UI
strings. Every other locale (``de``, ``es``, ``fr``, ``nl``) must expose the
*exact same* set of (dotted) keys — no missing keys (which surface as English
fallbacks for that locale) and no extra keys (dead strings).

Regression context: #1730 — es/fr/nl each drifted 133 keys behind en.json
(the entire Smart Playlist Mixer UI, ``companionLocalNetworkRequired`` and
other 4.x strings), so ES/FR/NL hosts silently saw English fallbacks while the
README promised full support. This test fails loudly the next time a key is
added to en.json without being mirrored into every locale.
"""

from __future__ import annotations

import json
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
LOCALES = ["de", "es", "fr", "nl"]


def _flatten(obj: dict, prefix: str = "") -> set[str]:
    """Return the set of dotted leaf-key paths in a nested translation dict."""
    keys: set[str] = set()
    for key, value in obj.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten(value, dotted)
        else:
            keys.add(dotted)
    return keys


def _load(locale: str) -> dict:
    return json.loads((I18N_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def test_canonical_locale_exists() -> None:
    assert (I18N_DIR / f"{CANONICAL}.json").is_file()


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_is_valid_json(locale: str) -> None:
    # Raises if the file is not valid JSON.
    _load(locale)


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_key_parity_with_english(locale: str) -> None:
    en_keys = _flatten(_load(CANONICAL))
    loc_keys = _flatten(_load(locale))

    missing = sorted(en_keys - loc_keys)
    extra = sorted(loc_keys - en_keys)

    assert not missing, (
        f"{locale}.json is missing {len(missing)} key(s) present in "
        f"{CANONICAL}.json (English fallbacks): {missing}"
    )
    assert not extra, (
        f"{locale}.json has {len(extra)} key(s) not present in "
        f"{CANONICAL}.json (dead strings): {extra}"
    )
