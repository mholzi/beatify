#!/usr/bin/env python3
"""Copy check for the six locale files: warns, never fails the build (#3386).

``check_i18n_keys.py`` guards the *structure* (key parity, orphans, stale .gz).
This one looks at the *words*, the things the copy review in #3386 found by
hand and that drift back in one PR at a time:

* **keys**: every locale has exactly the keys of en.json;
* **placeholders**: the same ``{name}`` set as the English text;
* **length**: a short label (en up to 16 characters: buttons, chips, tabs)
  that grows past 1.4 × the English length and past 22 characters, where it
  can start to wrap or cut;
* **glossary**: one word per thing and language. German says "Gastgeber",
  never "Host" or "Admin"; French says "tu" to the host and keeps "vous" for
  a room full of people; Spanish and Dutch keep "playlist" as the loanword;
  Italian says "turno" for a round and "risposta" for a guess;
* **typography**: "…" instead of three dots; Spanish exclamations and
  questions open with "¡" and "¿".

Why a warning and not an error: the review left the English Title Case labels
and a handful of long translations in place on purpose. A gate that turns
every PR red over known leftovers gets switched off. On GitHub Actions each
finding becomes a ``::warning`` annotation on the PR; ``--strict`` exits 1 on
any finding, for the day the leftovers are gone.

Usage:
    python3 scripts/check_i18n_copy.py            # print warnings, exit 0
    python3 scripts/check_i18n_copy.py --strict   # exit 1 on any warning
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = ROOT / "custom_components" / "beatify" / "www" / "i18n"
REFERENCE = "en"
LOCALES = ("de", "es", "fr", "it", "nl")

SHORT_LABEL_MAX = 16  # en length up to which a text counts as a label
LENGTH_FACTOR = 1.4
# Below this many characters a label fits a chip or a button in every layout
# we have, however much longer than the English it is: "Plays" -> "Partidas"
# is 1.6x and harmless. Above it, 1.4x is where wrapping starts.
LENGTH_FLOOR = 22

PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_]+\}")

# Words that must not appear, per language. Each entry: (pattern, advice,
# keys exempt from it). The exemptions are the places where the other word is
# right: a page title, or "vous" speaking to everyone in the room at once.
GLOSSARY: dict[str, list[tuple[re.Pattern[str], str, frozenset[str]]]] = {
    "de": [
        (
            re.compile(r"\bHost\b|\bHosten\b"),
            'say "Gastgeber"',
            frozenset(),
        ),
        (
            re.compile(r"\bAdmin"),
            'say "Gastgeber" (only the page title may say Admin)',
            frozenset({"admin.title"}),
        ),
        (
            re.compile(r"Media-?[Pp]layer"),
            'say "Lautsprecher"',
            frozenset(),
        ),
    ],
    "fr": [
        (
            re.compile(r"\b(vous|votre|vos)\b", re.IGNORECASE),
            'say "tu" to one person; "vous" only for everyone at once',
            frozenset(
                {
                    # The whole room: the TV, the rules brief, shared state.
                    "lobby.brief.dev.suddenDeath",
                    "lobby.brief.dev.titleArtist",
                    "game.pausedGuessesSaved",
                    "reveal.coverHint",
                    "dashboard.qrUnavailable",
                    "starting.sub",
                    "wizard.step4.modeYearHint",
                    "wizard.step4.modeTitleArtistHint",
                }
            ),
        ),
        (re.compile(r"\bround\b", re.IGNORECASE), 'say "manche"', frozenset()),
    ],
    "es": [
        (
            re.compile(r"\blistas? de reproducci", re.IGNORECASE),
            'say "playlist"',
            frozenset(),
        ),
    ],
    "nl": [
        (re.compile(r"afspeellijst", re.IGNORECASE), 'say "playlist"', frozenset()),
        (re.compile(r"luidspreker", re.IGNORECASE), 'say "speaker"', frozenset()),
    ],
    "it": [
        (re.compile(r"\bround\b", re.IGNORECASE), 'say "turno"', frozenset()),
        (re.compile(r"\bipotesi\b", re.IGNORECASE), 'say "risposta"', frozenset()),
    ],
}


def flatten(obj, prefix=""):
    """Dotted leaf keys with their values, in file order."""
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from flatten(value, path)
        else:
            yield path, value


def load(locale: str) -> dict[str, str]:
    path = I18N_DIR / f"{locale}.json"
    return dict(flatten(json.loads(path.read_text(encoding="utf-8"))))


def _sentences(text: str):
    return re.split(r"(?<=[.!?…])\s+", text)


def check(texts: dict[str, dict[str, str]]) -> list[tuple[str, str, str]]:
    """All findings as (locale, key, message)."""
    found: list[tuple[str, str, str]] = []
    en = texts[REFERENCE]

    for key, value in en.items():
        if isinstance(value, str) and "..." in value:
            found.append((REFERENCE, key, 'three dots: use "…"'))

    for locale in LOCALES:
        tr = texts[locale]
        for key in sorted(set(en) - set(tr)):
            found.append((locale, key, "missing (en.json has it)"))
        for key in sorted(set(tr) - set(en)):
            found.append((locale, key, "extra (en.json does not have it)"))

        rules = GLOSSARY.get(locale, [])
        for key, value in tr.items():
            if not isinstance(value, str) or key not in en:
                continue
            source = en[key] if isinstance(en[key], str) else ""

            if set(PLACEHOLDER_RE.findall(value)) != set(
                PLACEHOLDER_RE.findall(source)
            ):
                found.append((locale, key, "placeholders differ from en"))

            if (
                0 < len(source) <= SHORT_LABEL_MAX
                and len(value) > LENGTH_FACTOR * len(source)
                and len(value) > LENGTH_FLOOR
            ):
                found.append(
                    (
                        locale,
                        key,
                        f"label is {len(value) / len(source):.1f}× the English "
                        f"length ({value!r} vs {source!r})",
                    )
                )

            words = PLACEHOLDER_RE.sub("", value)  # {round} is not the word
            for pattern, advice, exempt in rules:
                if key in exempt:
                    continue
                match = pattern.search(words)
                if match:
                    found.append((locale, key, f'"{match.group(0)}": {advice}'))

            if "..." in value:
                found.append((locale, key, 'three dots: use "…"'))

            if locale == "es":
                for sentence in _sentences(value):
                    if "!" in sentence and "¡" not in sentence:
                        found.append((locale, key, 'exclamation without "¡"'))
                        break
                for sentence in _sentences(value):
                    if "?" in sentence and "¿" not in sentence and "://" not in sentence:
                        found.append((locale, key, 'question without "¿"'))
                        break
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 when there is any finding"
    )
    args = parser.parse_args(argv)

    texts = {loc: load(loc) for loc in (REFERENCE, *LOCALES)}
    found = check(texts)
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"

    for locale, key, message in found:
        line = f"{locale}.json {key}: {message}"
        if annotate:
            rel = (I18N_DIR / f"{locale}.json").relative_to(ROOT)
            print(f"::warning file={rel},title=i18n copy::{key}: {message}")
        else:
            print(line)

    by_locale: dict[str, int] = {}
    for locale, _, _ in found:
        by_locale[locale] = by_locale.get(locale, 0) + 1
    summary = ", ".join(f"{loc} {n}" for loc, n in sorted(by_locale.items()))
    print(
        f"i18n copy: {len(found)} warning(s)" + (f" ({summary})" if summary else "")
    )
    return 1 if (args.strict and found) else 0


if __name__ == "__main__":
    sys.exit(main())
