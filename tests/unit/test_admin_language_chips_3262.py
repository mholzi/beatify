"""The admin game-language chips must offer every language the game supports (#3262).

The admin setup offered EN, DE, ES, FR and NL while the server, the TTS phrases
and the guest picker already accepted Italian. An Italian host could not start a
game in Italian, and a saved setup with ``it`` lit no chip at all. Each new
language has to be added in several places, so this test ties the admin chips to
the two lists the rest of the app reads: ``SUPPORTED_LANGUAGES`` in ``i18n.js``
and the language tuples in ``game_views.py``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = ROOT / "custom_components" / "beatify"
ADMIN_HTML = COMPONENT / "www" / "admin.html"
I18N_JS = COMPONENT / "www" / "js" / "i18n.js"
GAME_VIEWS = COMPONENT / "server" / "game_views.py"


def _admin_chip_codes() -> list[str]:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    group = re.search(
        r'<div class="chip-group[^"]*" role="group" aria-label="Game language">'
        r"(.*?)</div>",
        html,
        re.S,
    )
    assert group, "game-language chip group not found in admin.html"
    return re.findall(r'data-lang="([a-z]+)"', group.group(1))


def _i18n_supported() -> list[str]:
    js = I18N_JS.read_text(encoding="utf-8")
    match = re.search(r"SUPPORTED_LANGUAGES\s*=\s*\[([^\]]*)\]", js)
    assert match, "SUPPORTED_LANGUAGES not found in i18n.js"
    return re.findall(r"'([a-z]+)'", match.group(1))


def _server_language_tuples() -> list[set[str]]:
    """Every ``language in (...)`` tuple in game_views.py."""
    tree = ast.parse(GAME_VIEWS.read_text(encoding="utf-8"))
    tuples: list[set[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "language"):
            continue
        for op, comp in zip(node.ops, node.comparators, strict=True):
            if isinstance(op, ast.In) and isinstance(comp, ast.Tuple):
                tuples.append({ast.literal_eval(elt) for elt in comp.elts})
    return tuples


def test_admin_chips_match_supported_languages() -> None:
    chips = _admin_chip_codes()
    assert len(chips) == len(set(chips)), f"duplicate language chip: {chips}"
    assert chips == _i18n_supported()


def test_admin_chips_match_server_accepted_languages() -> None:
    tuples = _server_language_tuples()
    assert tuples, "no `language in (...)` check found in game_views.py"
    chips = set(_admin_chip_codes())
    for accepted in tuples:
        assert chips == accepted


def test_italian_chip_present() -> None:
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert (
        '<button type="button" id="lang-it" class="chip" aria-pressed="false" '
        'data-lang="it">IT</button>'
    ) in html
