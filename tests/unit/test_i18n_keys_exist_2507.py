"""#2507 — every translation key the frontend asks for must exist in en.json.

``BeatifyI18n.t`` returns the key itself on a miss and never a falsy value, so
a missing key fails silently: ``data-i18n`` elements keep their hard-coded
English (a German TV showed "Now Playing", "Reveal", "Now revealing", "Year"),
and ``t(key) || 'fallback'`` renders the raw key, because the fallback is dead
code. Eight keys were missing at once, and nothing noticed.

This is the cross-reference the issue asked for: collect every literal key from
``data-i18n`` attributes and ``t('…')`` calls, and check it resolves in
en.json — the file every other locale falls back to.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WWW = Path(__file__).parents[2] / "custom_components" / "beatify" / "www"
EN = json.loads((WWW / "i18n" / "en.json").read_text(encoding="utf-8"))

# A key built at runtime from a variable — 'difficulty.' + level — reaches the
# scanner as its literal prefix and can never be resolved statically. Each entry
# is a prefix whose leaves are looked up dynamically; the section itself is
# still asserted to exist, so a renamed section is not silently tolerated.
DYNAMIC_PREFIXES = (
    "difficulty.",
    "highlights.",
    "superlatives.",
    "game.difficulty",
    "errors.",
    # #2584: the sabotage badge on the TV resolves
    # 'sabotage.effect.' + <rolled effect>. The effect is picked server-side
    # from SABOTAGE_EFFECTS, so the leaf is never a literal here — but the
    # section is, and the test below still asserts it exists.
    "sabotage.effect.",
)

# `data-i18n`, `data-i18n-placeholder`, `data-i18n-title`, `data-i18n-aria-label`.
# The aria variant carries two dashes, so the old single-segment suffix never
# matched it — eight player.html controls sat outside this scan until #2705.
_HTML_KEY = re.compile(r'data-i18n(?:-[a-z]+(?:-[a-z]+)?)?="([A-Za-z0-9_.]+)"')
# t('a.b') / t("a.b") on any of the wrappers: utils.t, BeatifyI18n.t, bare t —
# and the local `tr(key, fallback)` guards several modules define (#2704 added
# one to party-lights.js), which the bare-`t` pattern used to walk straight past.
_JS_KEY = re.compile(r"""(?<![A-Za-z0-9])_?(?:t|tr)\(\s*['"]([A-Za-z0-9_.]+)['"]""")


def _lookup(key: str):
    """Return the node en.json holds for a dotted key, or None if the path breaks."""
    node = EN
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _is_dynamic(key: str) -> bool:
    return any(key.startswith(p) or p.rstrip(".") == key for p in DYNAMIC_PREFIXES)


_ADMIN_SECTIONS = ("library-ai.js", "media-players.js")


def _sources() -> list[Path]:
    files = sorted(WWW.glob("*.html"))
    files += [
        p for p in sorted((WWW / "js").glob("*.js")) if not p.name.endswith(".min.js")
    ]
    # #3422: admin sections use their own `_t(key, fallback)` / `tr(...)` guards,
    # whose fallback hid nine missing libraryAi keys in every language.
    files += [WWW / "js" / "admin" / "sections" / n for n in _ADMIN_SECTIONS]
    return files


def _referenced_keys(suffix: str) -> dict[str, list[str]]:
    """key -> the files of that kind that ask for it."""
    found: dict[str, list[str]] = {}
    for path in _sources():
        if path.suffix != suffix:
            continue
        text = path.read_text(encoding="utf-8")
        # JS-rendered markup (library-ai.js builds its modal in a template
        # string) carries `data-i18n` attributes too (#3422).
        keys = _HTML_KEY.findall(text)
        if suffix == ".js":
            keys += _JS_KEY.findall(text)
        for key in keys:
            if "." not in key:
                continue  # a bare word is a variable name, not a key path
            found.setdefault(key, []).append(path.name)
    return found


def _all_referenced_keys() -> dict[str, list[str]]:
    merged = _referenced_keys(".html")
    for key, files in _referenced_keys(".js").items():
        merged.setdefault(key, []).extend(files)
    return merged


class TestEveryReferencedKeyResolves:
    def test_the_scan_actually_finds_keys(self):
        """Guard the guard: a broken regex would make this suite vacuously pass."""
        keys = _all_referenced_keys()
        assert len(keys) > 200, len(keys)
        assert "dashboard.nowPlaying" in keys
        assert "leaderboard.leader" in keys

    def test_no_frontend_key_is_missing_from_en_json(self):
        missing = {
            key: sorted(set(files))
            for key, files in _all_referenced_keys().items()
            if not _is_dynamic(key) and _lookup(key) is None
        }
        assert not missing, (
            "keys referenced by the frontend but absent from en.json: "
            + json.dumps(missing, indent=2, sort_keys=True)
        )

    def test_every_data_i18n_key_resolves_to_a_string(self):
        """initPageTranslations writes textContent, so an object here would
        render as [object Object]. JS may fetch a whole object on purpose —
        reveal.emotions does — but markup never can."""
        wrong = {
            key: sorted(set(files))
            for key, files in _referenced_keys(".html").items()
            if not _is_dynamic(key) and not isinstance(_lookup(key), str)
        }
        assert not wrong, "data-i18n keys that are not plain strings: " + json.dumps(
            wrong, indent=2, sort_keys=True
        )

    def test_the_dynamic_prefixes_still_name_something_real(self):
        """A tolerated prefix must stay a real section, or the allowance hides a
        rename instead of a dynamic lookup."""
        for prefix in DYNAMIC_PREFIXES:
            head = prefix.split(".")[0]
            assert head in EN, prefix


class TestLibraryAiAndProviderKeys:
    """#3422: the Crate Digger AI modal and the speaker hints were English everywhere."""

    def test_library_ai_keys_are_scanned(self):
        keys = _all_referenced_keys()
        for name in (
            "title",
            "intro",
            "theme",
            "count",
            "copy",
            "paste",
            "resolve",
            "name",
            "save",
        ):
            assert f"admin.libraryAi.{name}" in keys, name
        assert "admin.providerWarning.sonos" in keys

    def test_keys_present_and_translated_in_every_locale(self):
        keys = [
            k
            for k in _all_referenced_keys()
            if k.startswith(
                ("admin.libraryAi.", "admin.providerWarning.", "admin.speakerHint.")
            )
        ]
        assert len(keys) >= 20
        for path in sorted((WWW / "i18n").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in keys:
                node = data
                for part in key.split("."):
                    assert isinstance(node, dict) and part in node, (
                        f"{path.name}: {key}"
                    )
                    node = node[part]
                assert isinstance(node, str) and node.strip(), f"{path.name}: {key}"
                # "Songs" is the same word in de/nl; nothing else may match en.
                if path.name != "en.json" and key != "admin.libraryAi.count":
                    assert node != _lookup(key), f"{path.name}: {key} is still English"


class TestTheEightKeysFromTheReport:
    KEYS = (
        "dashboard.nowPlaying",
        "dashboard.reveal",
        "dashboard.nowRevealing",
        "game.yearLabel",
        "leaderboard.leader",
        "admin.alreadyJoined",
    )

    def test_present_in_every_locale(self):
        for path in sorted((WWW / "i18n").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in self.KEYS:
                node = data
                for part in key.split("."):
                    assert isinstance(node, dict) and part in node, (
                        f"{path.name}: {key}"
                    )
                    node = node[part]
                assert isinstance(node, str) and node.strip(), (
                    f"{path.name}: {key} is empty"
                )

    def test_the_name_placeholder_survives_translation(self):
        for path in sorted((WWW / "i18n").glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))["admin"][
                "alreadyJoined"
            ]
            assert "{name}" in value, f"{path.name}: {value!r}"
