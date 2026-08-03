"""Title-matching rules of the playlist health-check validator (#1957).

The validator compares the title a provider returns against the title in the
playlist. That comparison is a string match, which cannot decide anything when
the two sides are written in different scripts: providers return Japanese
tracks romanised ("紅蓮華" -> "Gurenge") or translated ("百花繚乱" -> "In Bloom").

Before #1957 every one of those counted as a defect. A single run on
`community/anime-openings.json` produced 308 flags with zero real defects, which
is worse than not running the check at all — a report that is 100 % noise trains
its reader to ignore it.

These tests pin the three rules that fixed it, and — just as important — pin
that a genuinely wrong track is still reported.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude/skills/playlist-health-check/scripts/validate_uris.py"
)


@pytest.fixture(scope="module")
def validator():
    spec = importlib.util.spec_from_file_location("validate_uris", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestChannelSuffix:
    """YouTube's auto-generated channels are not part of an artist's name."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Ikimonogakari - Topic", "Ikimonogakari"),
            ("Mrs. GREEN APPLE - Topic", "Mrs. GREEN APPLE"),
            ("SevenOopsVEVO", "SevenOops"),
            ("Judy & Mary", "Judy & Mary"),
        ],
    )
    def test_strips_topic_and_vevo(self, validator, raw, expected):
        assert validator.strip_channel_suffix(raw) == expected

    def test_never_empties_a_name(self, validator):
        """A band literally called "Topic" must survive the strip."""
        assert validator.strip_channel_suffix("Topic") == "Topic"


class TestScriptMismatch:
    """Different scripts -> the comparison has no verdict to give."""

    @pytest.mark.parametrize(
        "expected,actual",
        [
            ("紅蓮華", "Gurenge"),  # kanji -> romaji
            ("百花繚乱", "In Bloom"),  # kanji -> English translation
            ("インフェルノ", "Inferno"),  # katakana -> English
            ("Guren no Yumiya", "紅蓮の弓矢"),  # romaji -> kanji (reverse)
        ],
    )
    def test_reports_unverifiable_not_mismatch(self, validator, expected, actual):
        assert validator.title_verdict(expected, actual, "LiSA") == "unverifiable"

    def test_same_script_still_compared(self, validator):
        """Both sides Latin -> the script rule must not swallow the check."""
        assert (
            validator.title_verdict("Let It Be", "Se Me Enamora el Alma", "The Beatles")
            == "mismatch"
        )

    def test_both_sides_cjk_still_compared(self, validator):
        assert validator.title_verdict("紅蓮華", "残響散歌", "LiSA") == "mismatch"


class TestCompatibilityFolding:
    """Fullwidth and halfwidth latin are the same title written two ways."""

    def test_fullwidth_latin_matches_halfwidth(self, validator):
        assert validator.title_verdict("少女Ｓ", "少女S", "SCANDAL") == "match"


class TestNoRegressionOnLatinTitles:
    """The rules above must not loosen the ordinary Latin-script path."""

    @pytest.mark.parametrize(
        "expected,actual,artist",
        [
            ("Bohemian Rhapsody", "Bohemian Rhapsody - Remastered 2011", "Queen"),
            ("Blame", "Blame (feat. John Newman)", "Calvin Harris"),
            ("Dancing Queen", "Dancing Queen", "ABBA"),
        ],
    )
    def test_known_good_pairs_still_match(self, validator, expected, actual, artist):
        assert validator.title_verdict(expected, actual, artist) == "match"

    def test_a_genuinely_wrong_track_is_still_reported(self, validator):
        """The defect #1943 found — the check must keep catching this."""
        assert (
            validator.title_verdict(
                "Se Me Enamora el Alma", "Let It Be", "Isabel Pantoja"
            )
            == "mismatch"
        )


class TestVerdictShape:
    def test_unverifiable_result_is_not_a_defect(self, validator):
        r = validator.unverifiable_title("紅蓮華", "Gurenge", "LiSA - Topic")
        assert r["status"] == "unverifiable"
        assert r["http_code"] == 200
        assert r["actual_artist"] == "LiSA"  # channel suffix stripped
        assert "no verdict" in r["detail"]

    def test_wrong_track_result_keeps_both_titles(self, validator):
        r = validator.wrong_track("Africa", "Toto", "Rosanna", "Toto - Topic")
        assert r["status"] == "wrong_track"
        assert r["actual_title"] == "Rosanna"
        assert r["actual_artist"] == "Toto"
