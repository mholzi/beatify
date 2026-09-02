"""#2500 — the onboarding counter must not carry its total in a string.

player.html grew a fifth tour card with Title & Artist mode; the six
``onboarding.stepOf`` translations still read "of 4", so every first-time guest
saw "Step 5 of 4" on the last card. The count now comes from the DOM at render
time — these checks make sure nobody puts a number back into the strings, and
that the markup's own defaults agree with the cards that are actually there.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

WWW = Path(__file__).parents[2] / "custom_components" / "beatify" / "www"
PLAYER_HTML = (WWW / "player.html").read_text(encoding="utf-8")
LOCALES = sorted((WWW / "i18n").glob("*.json"))


def _tour_card_count() -> int:
    """Cards carry extra classes once hidden, so match the class, not the attribute."""
    return len(re.findall(r'class="tour-card(?:\s[^"]*)?"', PLAYER_HTML))


def _progress_segment_count() -> int:
    """``tour-wiz-seg-inner`` is the fill inside a segment, not a segment."""
    return len(re.findall(r'class="tour-wiz-seg(?:\s[^"]*)?"', PLAYER_HTML))


class TestTheStringsCarryNoCount:
    def test_every_locale_has_stepof(self):
        assert LOCALES, "no locale files found"
        for path in LOCALES:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "stepOf" in data["onboarding"], path.name

    def test_no_locale_bakes_a_number_into_stepof(self):
        """A digit here is the #2500 bug coming back."""
        for path in LOCALES:
            value = json.loads(path.read_text(encoding="utf-8"))["onboarding"]["stepOf"]
            assert not re.search(r"\d", value), f"{path.name}: {value!r}"


class TestTheMarkupAgreesWithItself:
    def test_there_are_as_many_progress_segments_as_cards(self):
        cards = _tour_card_count()
        assert cards >= 4, cards
        assert _progress_segment_count() == cards

    def test_the_progress_bars_upper_bound_matches_the_cards(self):
        """The rendered value is set from totalCards(); this is the pre-render
        default a screen reader can see first."""
        match = re.search(r'role="progressbar"[^>]*aria-valuemax="(\d+)"', PLAYER_HTML)
        assert match, "tour progress bar has no aria-valuemax"
        assert int(match.group(1)) == _tour_card_count()

    def test_the_total_has_its_own_element_to_be_written_into(self):
        assert 'id="tour-step-total"' in PLAYER_HTML
