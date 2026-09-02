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

# The second pass: words whose unaccented spelling is not a Spanish word at all,
# so seeing one is always a defect and never a legitimate choice. Words where
# both spellings exist and mean different things — esta/está, tu/tú, como/cómo,
# mas/más, aun/aún, valida/válida, acabo/acabó, bloqueo/bloqueó — are
# deliberately absent: only a reader can tell those apart, and a guard that
# cannot would fail on correct Spanish.
MUST_CARRY_AN_ACCENT = (
    "accion",
    "ahi",
    "anfitrion",
    "asegurate",
    "boton",
    "campeon",
    "cancion",
    "clasificacion",
    "codigo",
    "conexion",
    "configuracion",
    "continuara",
    "dias",
    "dificil",
    "distribucion",
    "envie",
    "esten",
    "estadisticas",
    "estandar",
    "exito",
    "facil",
    "grafico",
    "historico",
    "increible",
    "intentalo",
    "maquina",
    "musica",
    "ningun",
    "ocurrio",
    "pagina",
    "pestana",
    "posicion",
    "precision",
    "proxima",
    "puntuacion",
    "rapido",
    "record",
    "reproduccion",
    "sacudete",
    "salon",
    "seran",
    "sesion",
    "solida",
    "titulo",
    "todavia",
    "uniendose",
)
BARE_WORD = re.compile(r"\b(" + "|".join(MUST_CARRY_AN_ACCENT) + r")\b", re.IGNORECASE)


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


class TestSpanishCarriesItsAccents:
    """The same file wrote "Puntuacion", "Estadisticas" and "Cancion mas dificil"
    beside fully accented strings — the accents were dropped by hand, not by
    policy. 118 strings were corrected; this keeps them corrected."""

    def test_no_string_drops_a_required_accent(self):
        offenders = []
        for path, text in _strings(ES):
            for match in BARE_WORD.finditer(text):
                offenders.append(f"{path}: {match.group(0)!r} in {text!r}")
        assert not offenders, "es.json is missing accents:\n" + "\n".join(offenders)

    def test_placeholders_were_not_swept_up(self):
        """{version}, {min} and friends are tokens, not Spanish — a careless
        accent pass would rename them and break the interpolation."""
        for key, expected in (
            ("admin.updateAvailable", "{version}"),
            ("analyticsDashboard.pagination", "{current}"),
            ("wizard.step4.roundsHint", "{min}"),
        ):
            node = ES
            for part in key.split("."):
                node = node[part]
            assert expected in node, f"{key}: {node!r}"
