#!/usr/bin/env python3
"""Fail the build when a translation key is referenced nowhere.

Six locale files carry 1502 keys each. Every key one screen stops using is a
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


def is_referenced(key, corpus):
    """True when the key, or an ancestor path of >=2 segments, is in the corpus."""
    parts = key.split(".")
    for cut in range(len(parts), MIN_ANCESTOR_SEGMENTS - 1, -1):
        if cut < MIN_ANCESTOR_SEGMENTS:
            break
        if ".".join(parts[:cut]) in corpus:
            return True
    return False


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
    unreferenced = [k for k in keys if not is_referenced(k, corpus)]

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
        f"{len(unreferenced)} unreferenced, {len(allowed)} allowlisted."
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
