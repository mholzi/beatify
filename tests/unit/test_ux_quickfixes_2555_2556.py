"""#2555 and #2556 — two small things the party sees.

Both live in static assets, so they are checked the way #2500's companion test
checks the tour strings: against the source itself.

* #2555 — the phone podium double-escaped names. ``textContent`` already
  neutralizes markup, so passing it ``escapeHtml()`` output rendered
  "Tom & Jerry" as "Tom &amp; Jerry" in the podium moment. The TV was fixed for
  this in #1402-B8; the phone kept the old line.
* #2556 — the TV lobby showed a QR code, a URL and a player count without ever
  saying that scanning is how you join.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WWW = Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"
# This repo ships six locales, not the five the docs mention.
LOCALES = ("en", "de", "es", "fr", "it", "nl")


class TestPodiumNameIsNotDoubleEscaped:
    def test_podium_assigns_the_raw_name(self):
        src = (WWW / "js" / "player-end.js").read_text(encoding="utf-8")
        podium_line = next(
            line for line in src.splitlines() if "podium-' + place + '-name" in line
        )
        assert "escapeHtml" not in podium_line, (
            "textContent escapes on its own — escapeHtml() here double-escapes"
        )

    def test_no_textcontent_is_fed_escaped_html(self):
        """The whole family, so the fix cannot come back in a sibling line."""
        offenders = []
        for path in (WWW / "js").glob("*.js"):
            if path.name.endswith(".min.js"):
                continue
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if re.search(r"textContent\s*=.*escapeHtml\(", line):
                    offenders.append(f"{path.name}:{number}")
        assert offenders == [], f"double-escaped textContent: {offenders}"


class TestTvLobbyAsksGuestsToScan:
    def test_the_hint_sits_in_the_qr_section(self):
        html = (WWW / "dashboard.html").read_text(encoding="utf-8")
        section = html.split('class="lobby-qr-section"', 1)[1].split("</div>", 1)[0]
        assert 'data-i18n="lobby.scanToJoin"' in section

    def test_the_hint_is_translated_everywhere(self):
        for locale in LOCALES:
            data = json.loads(
                (WWW / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
            )
            assert data["lobby"]["scanToJoin"], f"{locale} is missing lobby.scanToJoin"

    def test_the_hint_is_styled_at_tv_size(self):
        css = (WWW / "css" / "dashboard.css").read_text(encoding="utf-8")
        assert ".dashboard-scan-hint" in css
        # The #1717 TV breakpoint upscales the lobby text; the hint follows it.
        breakpoint_block = css.split(".dashboard-player-count {", 2)[-1]
        assert ".dashboard-scan-hint" in breakpoint_block
