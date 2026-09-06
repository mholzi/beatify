"""#2641 — nothing a phone fetches from a foreign origin may hold up the page.

`player.html` and `dashboard.html` pulled `canvas-confetti` from jsdelivr with a
plain `<script src>` in the head, and all three host-facing pages linked the
Google Fonts stylesheet the same way. A synchronous cross-origin resource in the
head stops the parser until the CDN answers or the connection times out — on
party wifi with no working internet that is 5 to 30 seconds of blank screen
before the join button exists.

The service worker deliberately passes foreign origins through and caches only
Google Fonts, so confetti is fetched fresh on every cold load and the delay
repeats for every guest.

These tests assert the property rather than today's markup: *every* external
script must be `async` or `defer`, and *every* external stylesheet must be
loaded non-blocking. A new page, or a new third-party asset on an existing one,
is covered the day it lands.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WWW = Path(__file__).parents[2] / "custom_components" / "beatify" / "www"

# `<script ... src="https://...">`, capturing the whole tag so its attributes
# can be inspected. Same-origin `/beatify/static/...` sources are served by HA
# off the LAN and are not what this is about.
_EXTERNAL_SCRIPT = re.compile(
    r"<script\b(?![^>]*\bsrc=[\"']/)[^>]*\bsrc=[\"']https?://[^>]*>",
    re.IGNORECASE,
)
_EXTERNAL_STYLESHEET = re.compile(
    r"<link\b(?=[^>]*\brel=[\"']stylesheet[\"'])(?=[^>]*\bhref=[\"']https?://)[^>]*>",
    re.IGNORECASE,
)


def _pages() -> list[Path]:
    return sorted(WWW.glob("*.html"))


def _visible(html: str) -> str:
    """The markup with HTML comments stripped.

    Every fix in this area ships with a comment explaining it, and those
    comments quote the very markup they replaced. Scanning them would report the
    documentation as the defect.
    """
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def test_there_are_pages_to_scan() -> None:
    """Guard the guard: a moved www/ would make everything below vacuous."""
    pages = _pages()
    assert len(pages) >= 5, [p.name for p in pages]
    assert {"admin.html", "player.html", "dashboard.html"} <= {p.name for p in pages}


def test_the_scan_sees_the_third_party_assets_at_all() -> None:
    """The regexes must actually match the resources this issue is about."""
    joined = "\n".join(_visible(p.read_text(encoding="utf-8")) for p in _pages())
    assert any("jsdelivr" in tag for tag in _EXTERNAL_SCRIPT.findall(joined))
    assert any(
        "fonts.googleapis.com" in tag for tag in _EXTERNAL_STYLESHEET.findall(joined)
    )


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_no_external_script_blocks_the_parser(page: Path) -> None:
    """A cross-origin `<script src>` must carry `async` or `defer`.

    `async` is the right one for confetti specifically: the pages load their own
    code as `type="module"`, which is deferred, and a `defer`red confetti would
    run ahead of it in document order and hold up DOMContentLoaded — the page
    would paint and then sit there unwired. `defer` is still accepted here for
    any future script where ordering matters.
    """
    blocking = [
        tag
        for tag in _EXTERNAL_SCRIPT.findall(_visible(page.read_text(encoding="utf-8")))
        if not re.search(r"\b(async|defer)\b", tag)
    ]
    assert not blocking, (
        f"{page.name} loads a third-party script synchronously; on a party "
        f"network this blocks the page for the whole CDN timeout: {blocking}"
    )


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_no_external_stylesheet_blocks_the_render(page: Path) -> None:
    """A cross-origin `<link rel=stylesheet>` must not block first paint.

    The accepted forms are the two that do not: `media="print"` swapped to
    `all` on load, or `rel="preload"` applied on load. A plain stylesheet link
    is render-blocking by definition — the browser will not paint until it
    resolves.

    The `<noscript>` fallback each page carries is deliberately exempt: it is
    inert unless scripting is off, in which case the swap cannot run and the
    blocking link is the only way to get the font at all.
    """
    html = _visible(page.read_text(encoding="utf-8"))
    html = re.sub(
        r"<noscript>.*?</noscript>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    blocking = [
        tag
        for tag in _EXTERNAL_STYLESHEET.findall(html)
        if 'media="print"' not in tag and "onload=" not in tag
    ]
    assert not blocking, (
        f"{page.name} loads a third-party stylesheet render-blocking: {blocking}"
    )


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.name)
def test_a_swapped_stylesheet_still_applies(page: Path) -> None:
    """`media="print"` without the onload swap would never apply the font."""
    for tag in _EXTERNAL_STYLESHEET.findall(_visible(page.read_text(encoding="utf-8"))):
        if 'media="print"' in tag:
            assert "this.media='all'" in tag, (
                f"{page.name} parks a stylesheet on media=print and never "
                f"swaps it back — the font would never load: {tag}"
            )
