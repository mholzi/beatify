"""#2911 — the i18n gate must honour keys that are built at runtime.

The gate clears a key when the key itself or an ancestor path appears in the
corpus. Six lookups in the frontend assemble the key from a value the backend
sends, so neither ever appears:

    utils.t('errors.' + code)
    utils.t('superlatives.' + award.title)

Those keys are live. A cleanup charge that follows the gate's allowlist would
delete them, and nothing would fail until the backend sends that value in front
of a party. These tests pin the rule that keeps them off the list — and the
boundary that keeps the rule from clearing everything.
"""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "check_i18n_keys.py"


def _gate():
    spec = importlib.util.spec_from_file_location("check_i18n_keys", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_concatenated_literal_is_a_prefix():
    gate = _gate()
    corpus = "var msg = utils.t('errors.' + code);"
    assert gate.dynamic_prefixes(corpus) == {"errors."}
    assert gate.is_referenced("errors.NAME_TAKEN", corpus, {"errors."})


def test_prefix_without_trailing_dot_still_matches():
    """dashboard.js:871 builds admin.difficultyEasy from 'admin.difficulty'."""
    gate = _gate()
    corpus = "t('admin.difficulty' + difficulty.charAt(0).toUpperCase())"
    prefixes = gate.dynamic_prefixes(corpus)
    assert prefixes == {"admin.difficulty"}
    assert gate.is_referenced("admin.difficultyEasy", "", prefixes)


def test_template_literal_counts():
    gate = _gate()
    assert gate.dynamic_prefixes("t(`errors.${code}`)") == {"errors."}


def test_plain_call_is_not_a_prefix():
    """The `+` is the whole point.

    Without it every ordinary lookup turns its own complete key into a prefix
    that clears the namespace below it, and the gate stops checking anything.
    """
    gate = _gate()
    assert gate.dynamic_prefixes("t('admin.title')") == set()
    assert not gate.is_referenced("admin.titleSuffix", "", set())


def test_assembled_sentence_is_not_a_prefix():
    """A literal needs a dot to be a key path — 'Join ' is prose."""
    gate = _gate()
    assert gate.dynamic_prefixes("t('Join ' + name)") == set()


def test_real_corpus_keeps_the_runtime_namespaces_off_the_list():
    gate = _gate()
    corpus = gate.load_corpus()
    prefixes = gate.dynamic_prefixes(corpus)
    for prefix in ("errors.", "superlatives.", "highlights.", "difficulty."):
        assert prefix in prefixes, f"{prefix} lookup no longer recognised"

    # Sampled from the backend: const.py emits the code, scoring.py the award,
    # highlights.py the description.
    for key in (
        "errors.NAME_TAKEN",
        "errors.NO_PLAYABLE_SONGS",
        "superlatives.best_ghost",
        "highlights.highlight_streak",
        "difficulty.extreme",
        "admin.difficultyEasy",
    ):
        assert gate.is_referenced(key, corpus, prefixes), f"{key} reported as orphan"
