#!/usr/bin/env python3
"""Does the documentation still describe the version that ships? (#2808)

Release step 7 says "pull the README and the docs along" and names two numbers.
On 2026-09-10 both were right, the step was ticked off, and two other things
had been stale for a month: the README's "What's New" stopped at v4.2.0, four
minor versions back, and `docs/provider-coverage.md` still counted a 5,980-song
catalogue that had grown to 8,432.

A prose instruction that ends in "and anything else under docs/" is not a
check. This is: it reads the catalogue and the manifest, and says which file
disagrees with them.

Usage:
    python3 scripts/check_docs_current.py           # report, exit 1 on drift
    python3 scripts/check_docs_current.py --json    # machine-readable

The check is deliberately narrow. It only compares claims that can be derived
from the repository — song counts, playlist counts, the newest version named.
It cannot tell whether a paragraph is still *true*, and it does not pretend to.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYLISTS = ROOT / "custom_components" / "beatify" / "playlists"
MANIFEST = ROOT / "custom_components" / "beatify" / "manifest.json"
README = ROOT / "README.md"
PROVIDER_COVERAGE = ROOT / "docs" / "provider-coverage.md"


def catalogue() -> tuple[int, int]:
    """(playlist files, song entries) — the same arithmetic the README claims."""
    files = sorted(PLAYLISTS.glob("**/*.json"))
    songs = 0
    count = 0
    for f in files:
        if f.name.startswith("_"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        entries = data.get("songs")
        if not isinstance(entries, list):
            continue
        count += 1
        songs += len(entries)
    return count, songs


def shipped_version() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def _num(text: str) -> int:
    return int(text.replace(",", "").replace(".", ""))


def check() -> list[dict]:
    """Every disagreement between the docs and the repository."""
    playlists, songs = catalogue()
    version = shipped_version()
    stable = version.split("-")[0]
    findings: list[dict] = []

    readme = README.read_text(encoding="utf-8")

    # 1. "Beatify comes with N songs across M curated playlists"
    m = re.search(
        r"comes with \*{0,2}([\d,\.]+)\*{0,2} songs across \*{0,2}(\d+)\*{0,2}"
        r" curated playlists",
        readme,
    )
    if not m:
        findings.append(
            {
                "file": "README.md",
                "what": "the catalogue sentence is gone",
                "detail": (
                    "no 'comes with N songs across M curated playlists' line — "
                    "either it was reworded or it was dropped; this check cannot "
                    "follow it"
                ),
            }
        )
    elif (_num(m.group(1)), int(m.group(2))) != (songs, playlists):
        findings.append(
            {
                "file": "README.md",
                "what": "catalogue numbers are stale",
                "detail": (
                    f"says {m.group(1)} songs / {m.group(2)} playlists, "
                    f"repository has {songs:,} / {playlists}"
                ),
            }
        )

    # 2. The comparison table repeats them.
    for claim in re.finditer(r"(\d+) playlists ship with it, ([\d,\.]+) songs", readme):
        if (int(claim.group(1)), _num(claim.group(2))) != (playlists, songs):
            findings.append(
                {
                    "file": "README.md",
                    "what": "comparison table is stale",
                    "detail": (
                        f"says {claim.group(1)} playlists / {claim.group(2)} songs, "
                        f"repository has {playlists} / {songs:,}"
                    ),
                }
            )

    # 3. "What's New" has to lead with the version that ships.
    #
    # Only while a stable is in the manifest. During an rc cycle the README
    # would otherwise have to announce a version nobody can install yet, and
    # every rc-cut PR would carry a README edit for no reader's benefit. The
    # contract is: the README is current **when a stable ships**.
    prerelease = "-" in version
    section = re.search(r"##\s*What's New\s*(.+?)(?=\n##\s|\Z)", readme, re.S)
    if section and not prerelease:
        heads = re.findall(r"###\s*v(\d+\.\d+\.\d+)", section.group(1))
        if not heads:
            findings.append(
                {
                    "file": "README.md",
                    "what": "What's New lists no version at all",
                    "detail": "expected the newest release at the top",
                }
            )
        elif heads[0] != stable:
            findings.append(
                {
                    "file": "README.md",
                    "what": "What's New is behind",
                    "detail": (
                        f"newest entry is v{heads[0]}, the shipped version is v{stable}"
                    ),
                }
            )

    # 4. A generated report that names the catalogue it counted.
    if PROVIDER_COVERAGE.exists() and not prerelease:
        text = PROVIDER_COVERAGE.read_text(encoding="utf-8")
        state = re.search(r"Catalogue state:\s*v?([\d.]+(?:-rc\d+)?)", text)
        total = re.search(r"\|\s*Apple\s*\|\s*\d+\s*\|\s*(\d+)\s*\|", text)
        if state and state.group(1).split("-")[0] != stable:
            findings.append(
                {
                    "file": "docs/provider-coverage.md",
                    "what": "counted an older catalogue",
                    "detail": (
                        f"header says v{state.group(1)}, the shipped version is "
                        f"v{stable} — regenerate or date it explicitly"
                    ),
                }
            )
        if total and int(total.group(1)) != songs:
            findings.append(
                {
                    "file": "docs/provider-coverage.md",
                    "what": "coverage percentages use an old total",
                    "detail": (
                        f"totals {total.group(1)} songs, repository has {songs:,} — "
                        f"every percentage in the table is off"
                    ),
                }
            )

    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    findings = check()
    if args.json:
        print(json.dumps({"findings": findings}, indent=2, ensure_ascii=False))
        return 1 if findings else 0

    playlists, songs = catalogue()
    print(f"catalogue: {playlists} playlists, {songs:,} songs")
    print(f"shipped:   v{shipped_version()}")
    if not findings:
        print("\nthe documentation matches the repository")
        return 0
    print(f"\n{len(findings)} disagreement(s):\n")
    for f in findings:
        print(f"  {f['file']} — {f['what']}")
        print(f"    {f['detail']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
