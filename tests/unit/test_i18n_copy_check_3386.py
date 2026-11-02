"""#3386 - the copy check warns about wording, it does not gate the build.

``scripts/check_i18n_copy.py`` runs in CI as a warning. These tests pin its
mechanics: a finding is reported, a placeholder is not mistaken for a word,
the default run exits 0 and ``--strict`` turns findings into exit 1.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "check_i18n_copy.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_i18n_copy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _texts(**overrides):
    base = {"en": {"a.b": "Waiting for host", "a.c": "Round {round}"}}
    for loc in ("de", "es", "fr", "it", "nl"):
        base[loc] = dict(base["en"])
    for loc, values in overrides.items():
        base[loc].update(values)
    return base


def test_german_host_is_flagged():
    mod = _load()
    found = mod.check(_texts(de={"a.b": "Warte auf den Host"}))
    assert any(loc == "de" and key == "a.b" for loc, key, _ in found)


def test_placeholder_named_like_a_word_is_not_flagged():
    mod = _load()
    found = mod.check(_texts(it={"a.c": "Turno {round}"}, fr={"a.c": "Manche {round}"}))
    assert not [f for f in found if f[1] == "a.c"]


def test_spanish_exclamation_needs_the_opening_mark():
    mod = _load()
    found = mod.check(_texts(es={"a.b": "Correcto!"}))
    assert any("¡" in msg for loc, _, msg in found if loc == "es")


def test_missing_key_and_placeholder_drift_are_reported():
    mod = _load()
    texts = _texts(nl={"a.c": "Ronde"})
    del texts["de"]["a.b"]
    found = mod.check(texts)
    assert ("de", "a.b", "missing (en.json has it)") in found
    assert ("nl", "a.c", "placeholders differ from en") in found


def test_default_run_never_fails_and_strict_does(monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod, "check", lambda texts: [("de", "x", "planted")])
    assert mod.main([]) == 0
    assert mod.main(["--strict"]) == 1


def test_the_real_locales_load():
    mod = _load()
    texts = {loc: mod.load(loc) for loc in ("en", *mod.LOCALES)}
    assert all(len(t) == len(texts["en"]) for t in texts.values())
    mod.check(texts)  # runs end to end on the shipped files
