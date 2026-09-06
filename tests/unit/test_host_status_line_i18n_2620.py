"""#2620 — the strings the host status line is assembled from must exist.

`admin.js` built the most important line of the setup card out of English
literals — `'no playlist'`, `` `${pls.length} playlists` ``, `'Off'`,
`${s.difficulty || 'normal'}` — plus `'🔊 no speaker'` in `setup-sync.js` and
`'Network error. Please try again.'` behind the two start buttons. A German host
read "🔊 Wohnzimmer · 3 playlists · normal · 45s · DE · ⏭️ Off" every time they
set up a game, and an English sentence whenever a start failed.

Those fragments now go through i18n. The generic guard (#2507,
``test_i18n_keys_exist_2507.py``) cannot see them: it scans literal ``t('a.b')``
calls in ``www/js/*.js``, and these are looked up through the ``tr`` wrapper and
from ``www/js/admin/``. So they are listed here by hand — a short, explicit list
is the honest form of that trade-off, and ``test_i18n_locale_parity.py`` then
carries each one into the other five locales.

The wording is checked where it belongs, in
``www/js/__tests__/home-status-line-i18n-2620.test.js``, which renders the line
with a marking translator and fails on any fragment that did not pass through
one of these keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

WWW = Path(__file__).parents[2] / "custom_components" / "beatify" / "www"
EN = json.loads((WWW / "i18n" / "en.json").read_text(encoding="utf-8"))

# key -> the `{placeholder}` slots the caller fills in.
STATUS_LINE_KEYS: dict[str, tuple[str, ...]] = {
    # www/js/admin/util.js :: buildHomeMeta
    "admin.home.noPlaylist": (),
    "admin.home.playlistCount": ("{count}",),
    "admin.home.libraryPlaylistLabel": (),
    "admin.revealAdvanceOff": (),
    "admin.easy": (),
    "admin.normal": (),
    "admin.hard": (),
    # www/js/admin/setup-sync.js :: speakerLabelFor
    "admin.home.noSpeaker": (),
    # www/js/admin.js :: the three failed-start paths
    "errors.networkRetry": (),
}


def _lookup(key: str):
    node = EN
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@pytest.mark.parametrize("key", sorted(STATUS_LINE_KEYS))
def test_the_key_resolves_to_a_string(key: str) -> None:
    value = _lookup(key)
    assert isinstance(value, str) and value, (
        f"{key} is asked for by the admin home view but missing from en.json"
    )


@pytest.mark.parametrize("key,slots", sorted(STATUS_LINE_KEYS.items()))
def test_the_placeholders_match_what_the_caller_supplies(
    key: str, slots: tuple[str, ...]
) -> None:
    """A slot the caller never fills would reach the screen as `{count}`."""
    value = _lookup(key)
    for slot in slots:
        assert slot in value, f"{key} lost its {slot} placeholder"
    for stray in ("{count}", "{max}", "{bands}"):
        if stray not in slots:
            assert stray not in value, (
                f"{key} carries {stray}, which nothing fills in — it would "
                f"render literally"
            )
