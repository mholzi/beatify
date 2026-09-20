#!/usr/bin/env python3
"""Fail the build when a translation key is referenced nowhere.

Six locale files carry the same key set (1502 of them when this gate went in). Every key one screen stops using is a
string six translators keep in sync for a screen that no longer exists, and
nothing noticed: the leave-flow keys from #2583 sat there for months. The point
of this gate is not the cleanup — it is that the next orphan gets caught on the
PR that creates it.

**The .gz trap.** ``www/i18n/`` carries a ``<name>.json.gz`` next to every
``<name>.json``, and Home Assistant's ``/local`` handler serves the gzip when it
exists. Pruning a JSON without regenerating its ``.gz`` leaves the old keys live
in the browser while the diff looks finished. This script therefore checks that
every ``.json`` and its ``.gz`` carry the same key set — a stale sibling is an
error in its own right, not a detail for the cleanup PR to remember.

**Why the reference rule is generous.** Keys are not only written out in full.
Several subtrees are fetched whole and indexed at runtime (``reveal.emotions``,
``errors``, ``difficulty``, …), so a leaf inside one can be live without ever
appearing as a literal. A key therefore counts as referenced when the full
dotted key appears anywhere in the corpus **or** when any ancestor path does.
That admits some genuinely dead keys; a stricter rule was tried and reported
452 keys, of which whole namespaces were demonstrably in use. A gate that cries
wolf gets switched off.

**Keys assembled at runtime** (#2911) have neither form: ``utils.t('errors.' +
code)`` never writes ``errors.NAME_TAKEN`` down, and ``errors`` alone is one
segment. Such prefixes are collected from the corpus and everything under them
counts as referenced — see ``dynamic_prefixes``. Getting this wrong is the
expensive direction: the allowlist reads as a to-do list, and deleting a live
error message breaks nothing until the backend sends that code mid-game.

**The allowlist** (``scripts/i18n_allowlist.txt``) holds keys that are known
orphans not yet cleaned up, each with a reason. It cannot rot: an entry that
has become referenced again is an error too, so the file shrinks as the screens
come back or the keys go.

Usage:
    python3 scripts/check_i18n_keys.py            # gate, exits 1 on findings
    python3 scripts/check_i18n_keys.py --list     # print unreferenced keys
    python3 scripts/check_i18n_keys.py --write-allowlist
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "custom_components" / "beatify" / "www" / "i18n"
REFERENCE_LOCALE = "en"
ALLOWLIST = Path(__file__).resolve().parent / "i18n_allowlist.txt"

# Where a key may be referenced. The minified bundles are included on purpose:
# they are shipped, so a key only the bundle names is still live.
CORPUS_GLOBS = (
    ("custom_components/beatify/www", "**/*.html"),
    ("custom_components/beatify/www", "**/*.js"),
    ("custom_components/beatify", "**/*.py"),
)
CORPUS_SKIP = ("__tests__",)


def flatten(obj, prefix=""):
    """Dotted leaf keys of a nested dict, in file order."""
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from flatten(value, path)
        else:
            yield path


def locale_files():
    return sorted(p for p in I18N_DIR.glob("*.json"))


def load_corpus():
    chunks = []
    for base, pattern in CORPUS_GLOBS:
        for path in sorted((ROOT / base).glob(pattern)):
            if any(skip in str(path) for skip in CORPUS_SKIP):
                continue
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


# An ancestor only counts as a reference when it is itself a dotted path. The
# top-level names are ordinary English words — "admin", "game", "player",
# "errors" — and each of them occurs hundreds of times in the corpus for
# reasons that have nothing to do with translations. Accepting a bare
# top-level name as evidence clears 1500 of 1502 keys and the gate checks
# nothing at all.
MIN_ANCESTOR_SEGMENTS = 2

# Not every key is written out, and not every key has a referenced ancestor
# either: several lookups build the key at runtime from a value the backend
# sends.
#
#     utils.t('errors.' + code)                    errors.NAME_TAKEN, …
#     utils.t('superlatives.' + award.title)       superlatives.best_ghost, …
#     utils.t('highlights.' + h.description)       highlights.highlight_streak, …
#     utils.t('difficulty.' + difficulty.label)    difficulty.extreme, …
#     utils.t('game.difficulty' + capitalised)     game.difficultyEasy, …
#
# The literal in front of the `+` is a prefix and everything under it is live.
# Without this rule the gate reports those keys as orphans, and they are the
# worst possible false positive: deleting one breaks a message at runtime that
# no test renders, because the code that asks for it only runs when the backend
# sends that particular value.
#
# The prefixes are read out of the corpus instead of being listed here, so a new
# dynamic lookup does not need this file changed. Two shapes are recognised, both
# anchored on a `t(` call: a quoted literal being concatenated, and a template
# literal interrupted by a placeholder — t(`errors.${code}`).
#
# Two guards keep the rule from swallowing the gate. The `+` is mandatory in the
# concatenated shape: match a bare `t('admin.title')` too and every complete key
# becomes a prefix that clears the namespace under it — tried it, 319 "prefixes",
# and the gate went blind. And a literal must look like a key path with at least
# one dot, so `t('Join ' + name)` stays what it is, a sentence being assembled.
DYNAMIC_PREFIX_RES = (
    re.compile(r"""\bt\(\s*'([^'\n]*)'\s*\+"""),
    re.compile(r"""\bt\(\s*"([^"\n]*)"\s*\+"""),
    re.compile(r"""\bt\(\s*`([^`\n$]*)\$\{"""),
)
KEY_PATH_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*\.?$")


def dynamic_prefixes(corpus):
    """Key prefixes that the corpus assembles at runtime."""
    found = set()
    for pattern in DYNAMIC_PREFIX_RES:
        for match in pattern.finditer(corpus):
            literal = match.group(1)
            if "." not in literal or not KEY_PATH_RE.match(literal):
                continue
            found.add(literal)
    return found


def is_referenced(key, corpus, prefixes=()):
    """True when the key is named, has a named ancestor, or sits under a
    prefix the corpus builds keys from at runtime."""
    parts = key.split(".")
    for cut in range(len(parts), MIN_ANCESTOR_SEGMENTS - 1, -1):
        if cut < MIN_ANCESTOR_SEGMENTS:
            break
        if ".".join(parts[:cut]) in corpus:
            return True
    return any(key.startswith(prefix) for prefix in prefixes)


def read_allowlist():
    if not ALLOWLIST.exists():
        return {}
    entries = {}
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, reason = line.partition("#")
        entries[key.strip()] = reason.strip()
    return entries


def check_locale_parity(errors):
    """Every locale must carry the reference locale's key set, .gz included."""
    reference = None
    for path in locale_files():
        keys = set(flatten(json.loads(path.read_text(encoding="utf-8"))))
        if path.stem == REFERENCE_LOCALE:
            reference = keys
    if reference is None:
        errors.append(f"no {REFERENCE_LOCALE}.json in {I18N_DIR}")
        return

    for path in locale_files():
        keys = set(flatten(json.loads(path.read_text(encoding="utf-8"))))
        missing, extra = reference - keys, keys - reference
        if missing:
            errors.append(
                f"{path.name} is missing {len(missing)} key(s) that "
                f"{REFERENCE_LOCALE}.json has, e.g. {sorted(missing)[:3]}"
            )
        if extra:
            errors.append(
                f"{path.name} has {len(extra)} key(s) {REFERENCE_LOCALE}.json "
                f"does not, e.g. {sorted(extra)[:3]}"
            )

        gz = path.with_suffix(".json.gz")
        if not gz.exists():
            continue
        try:
            gz_keys = set(flatten(json.loads(gzip.decompress(gz.read_bytes()))))
        except (OSError, ValueError) as exc:
            errors.append(f"{gz.name} is not readable as JSON ({exc})")
            continue
        if gz_keys != keys:
            errors.append(
                f"{gz.name} is stale: its key set differs from {path.name} "
                f"({len(keys - gz_keys)} only in the json, "
                f"{len(gz_keys - keys)} only in the gzip). Home Assistant "
                f"serves the gzip, so the json alone does not ship."
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="print unreferenced keys and exit 0"
    )
    parser.add_argument(
        "--write-allowlist",
        action="store_true",
        help="rewrite the allowlist from the current findings",
    )
    args = parser.parse_args()

    reference_path = I18N_DIR / f"{REFERENCE_LOCALE}.json"
    keys = list(flatten(json.loads(reference_path.read_text(encoding="utf-8"))))
    corpus = load_corpus()
    prefixes = dynamic_prefixes(corpus)
    unreferenced = [k for k in keys if not is_referenced(k, corpus, prefixes)]

    if args.list:
        print("\n".join(unreferenced))
        return 0

    if args.write_allowlist:
        header = [
            "# Translation keys that are referenced nowhere and have not been",
            "# cleaned up yet. Regenerate with:",
            "#     python3 scripts/check_i18n_keys.py --write-allowlist",
            "#",
            "# An entry here is a debt, not a permission. Removing a key from a",
            "# locale file means removing it from all six AND regenerating the",
            "# .gz sibling — Home Assistant serves the gzip.",
            "",
        ]
        ALLOWLIST.write_text("\n".join(header + unreferenced) + "\n", encoding="utf-8")
        print(f"wrote {len(unreferenced)} key(s) to {ALLOWLIST.name}")
        return 0

    allowed = read_allowlist()
    errors = []
    check_locale_parity(errors)

    new = [k for k in unreferenced if k not in allowed]
    revived = [k for k in allowed if k not in set(unreferenced)]

    for key in new:
        errors.append(
            f"{key} is referenced nowhere. Remove it from all six locales "
            f"(and their .gz), or add it to {ALLOWLIST.name} with a reason."
        )
    for key in revived:
        errors.append(
            f"{key} is in {ALLOWLIST.name} but is referenced again — "
            f"drop the allowlist entry."
        )

    total = len(keys)
    print(
        f"i18n: {total} keys in {REFERENCE_LOCALE}.json, "
        f"{len(unreferenced)} unreferenced, {len(allowed)} allowlisted, "
        f"{len(prefixes)} runtime prefix(es) honoured."
    )
    if errors:
        print(f"\n{len(errors)} problem(s):\n", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1
    print("No new orphans, locales in parity, gzip siblings current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
