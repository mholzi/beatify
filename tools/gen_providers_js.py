#!/usr/bin/env python3
"""Generate the JavaScript mirror of the Python provider registry (#2713).

The admin frontend needs the same provider list the integration has — the
wizard chips, the capability badge, the per-playlist coverage counts and the
playlist hub's coverage rows all key off it. Before #2713 that list was typed
out again in half a dozen JS modules, so a provider added in Python reached the
browser only if somebody remembered every one of them.

This script writes ``custom_components/beatify/www/js/providers.generated.js``
from :data:`custom_components.beatify.providers.PROVIDERS`.
``tests/unit/test_provider_registry_2713.py`` regenerates it in memory and
fails when the committed file has drifted — the same guard ``npm run
build:check`` gives the minified bundles.

Usage:
    python3 tools/gen_providers_js.py           # write the file
    python3 tools/gen_providers_js.py --check   # exit 1 if it has drifted
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def registry_providers():
    """The provider registry, without importing the integration package.

    ``custom_components/beatify/__init__.py`` pulls in Home Assistant, which is
    not installed for the frontend build. ``providers.py`` deliberately depends
    on nothing but ``const.py``, so it can be loaded under a synthetic package
    name and its relative import still resolves. Under pytest the real module
    is already importable, and that copy is used so a test can monkeypatch it.
    """
    import importlib
    import types

    try:
        return importlib.import_module("custom_components.beatify.providers").PROVIDERS
    except ImportError:
        pass

    pkg = types.ModuleType("_beatify_registry")
    pkg.__path__ = [str(REPO_ROOT / "custom_components" / "beatify")]
    pkg.__package__ = "_beatify_registry"
    sys.modules.setdefault("_beatify_registry", pkg)
    return importlib.import_module("_beatify_registry.providers").PROVIDERS


OUTPUT = REPO_ROOT / "custom_components/beatify/www/js/providers.generated.js"

_HEADER = """/**
 * GENERATED FILE — do not edit by hand (#2713).
 *
 * Mirror of `custom_components/beatify/providers.py`. Regenerate with:
 *
 *     python3 tools/gen_providers_js.py
 *
 * `tests/unit/test_provider_registry_2713.py` fails if this file has drifted
 * from the Python registry, so a provider added on one side cannot reach a
 * release without the other.
 *
 * Field meanings live on the `Provider` dataclass in providers.py; the short
 * version:
 *   platforms      speaker platforms that can serve this provider
 *   supportsKey    key in a /beatify/api/media-players entry
 *   countKey       key in a playlist entry, or null when it is not counted
 *   countFallback  a missing count means "every song" (legacy playlists)
 *   catalogueCoverage  the count measures stored URIs, not "every song"
 */

"""


def _entry(provider) -> dict:
    """One provider as the frontend sees it."""
    return {
        "id": provider.id,
        "label": provider.label,
        "shortLabel": provider.short_label or provider.label,
        "platforms": sorted(provider.platforms),
        "supportsKey": provider.supports_key,
        "countKey": provider.count_key if provider.counted else None,
        "countFallback": provider.count_falls_back_to_song_count,
        # True when the count measures how many songs carry this provider's
        # URI. False for Amazon Music, whose count is "every song" because
        # Alexa searches by name — its row is shown, but it cannot be the
        # reason a playlist is described as having streaming coverage.
        "catalogueCoverage": bool(provider.counted and provider.catalogue_uris),
        "sub": provider.sub,
        "subKey": provider.sub_key,
        "pauseRecoveryKey": provider.pause_recovery_key,
    }


def render(providers=None) -> str:
    """The full contents of providers.generated.js for ``providers``.

    Takes the list rather than reading it, so the drift test can render a
    registry that is not the committed one and see the difference.
    """
    entries = [
        _entry(p)
        for p in (providers if providers is not None else registry_providers())
    ]
    body = json.dumps(entries, indent=4, ensure_ascii=False)
    # JSON is valid JS, but keep the file to the repo's 4-space, single-quote
    # free style by leaving the array as-is and wrapping it in the exports the
    # modules import.
    return (
        _HEADER
        + "export const PROVIDERS = "
        + body
        + ";\n\n"
        + "export const PROVIDER_IDS = PROVIDERS.map((p) => p.id);\n\n"
        + "export const PROVIDERS_BY_ID = Object.fromEntries("
        + "PROVIDERS.map((p) => [p.id, p]));\n\n"
        + "/** Providers a speaker on this platform can serve. */\n"
        + "export function providersForPlatform(platform) {\n"
        + '    const canonical = platform === "alexa" ? "alexa_media" : platform;\n'
        + "    return PROVIDERS.filter((p) => p.platforms.includes(canonical));\n"
        + "}\n"
    )


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(
                f"{OUTPUT} is out of date — run: python3 tools/gen_providers_js.py",
                file=sys.stderr,
            )
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
