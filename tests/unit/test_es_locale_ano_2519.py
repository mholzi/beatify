"""#2519 — the Spanish locale must not say "ano" when it means "año".

``es.json`` carried it in 14 strings, including ``reveal.correctYear``
("Ano correcto"), which is on screen after every round of every Spanish game.
It is not a dropped accent on the same word: ``ano`` is a different noun.

The file already wrote ``año`` correctly elsewhere and holds 700 other
non-ASCII characters, so this was never an ASCII house style — which is why a
guard is worth having: the next hand-edit or ASCII-folding pass would put it
straight back.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

I18N = Path(__file__).parents[2] / "custom_components" / "beatify" / "www" / "i18n"
ES = json.loads((I18N / "es.json").read_text(encoding="utf-8"))

# Word-bounded, so "mano", "piano" and "plano" are untouched.
BARE_ANO = re.compile(r"\b[Aa]nos?\b")


def _strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


class TestSpanishYearIsSpelledWithTheTilde:
    def test_no_string_says_ano(self):
        offenders = [
            f"{path}: {text!r}" for path, text in _strings(ES) if BARE_ANO.search(text)
        ]
        assert not offenders, 'es.json says "ano" where it means "año":\n' + "\n".join(
            offenders
        )

    def test_the_year_strings_actually_carry_the_tilde(self):
        """Guard the guard — deleting the word entirely would also pass above."""
        for key in ("reveal.correctYear", "reveal.theYearWas", "game.selectYear"):
            node = ES
            for part in key.split("."):
                node = node[part]
            assert "ño" in node, f"{key}: {node!r}"

    def test_the_scan_reaches_the_whole_file(self):
        assert sum(1 for _ in _strings(ES)) > 500
