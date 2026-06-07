"""Tests for the pure text-matching layer (game/text_match.py).

Title & Artist guessing mode — Issue #1180. These functions are pure and
dependency-free; they back per-field classification in later phases.
"""

from __future__ import annotations


from custom_components.beatify.const import FUZZY_MAX_EDITS, FUZZY_MIN_LEN
from custom_components.beatify.game.text_match import (
    STATUS_EXACT,
    STATUS_FUZZY,
    STATUS_NEAR_MISS,
    STATUS_SKIPPED,
    STATUS_WRONG,
    classify_field,
    levenshtein,
    normalize,
)


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------


class TestStatusConstants:
    def test_status_literal_values(self):
        # Frontend + serializers depend on these exact strings.
        assert STATUS_EXACT == "exact"
        assert STATUS_FUZZY == "fuzzy"
        assert STATUS_NEAR_MISS == "near_miss"
        assert STATUS_WRONG == "wrong"
        assert STATUS_SKIPPED == "skipped"


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_lowercases(self):
        assert normalize("Bohemian Rhapsody") == "bohemian rhapsody"

    def test_strips_diacritics(self):
        # é -> e, ü -> u, ñ -> n
        assert normalize("Beyoncé") == "beyonce"
        assert normalize("Motörhead") == "motorhead"
        assert normalize("El Niño") == "el nino"

    def test_strips_punctuation(self):
        assert normalize("Don't Stop Me Now!") == "dont stop me now"
        assert normalize("Hello, World.") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize("  too   many    spaces  ") == "too many spaces"

    def test_strips_leading_the(self):
        assert normalize("The Beatles") == "beatles"

    def test_strips_leading_a(self):
        assert normalize("A Horse With No Name") == "horse with no name"

    def test_strips_leading_an(self):
        assert normalize("An Innocent Man") == "innocent man"

    def test_does_not_strip_the_mid_string(self):
        # Only a *leading* article is stripped.
        assert normalize("Save The Last Dance") == "save the last dance"

    def test_strips_parenthetical_qualifier(self):
        assert normalize("Smells Like Teen Spirit (Remastered)") == (
            "smells like teen spirit"
        )
        assert normalize("Africa (Album Version)") == "africa"

    def test_strips_dash_suffix(self):
        assert normalize("Don't Stop Believin' - 2009 Remaster") == (
            "dont stop believin"
        )

    def test_strips_feat_segment(self):
        assert normalize("Calvin Harris feat. Rihanna") == "calvin harris"

    def test_strips_ft_segment(self):
        assert normalize("Eminem ft. Dido") == "eminem"

    def test_empty_string_normalizes_to_empty(self):
        assert normalize("") == ""

    def test_whitespace_only_normalizes_to_empty(self):
        assert normalize("   ") == ""

    def test_idempotent(self):
        once = normalize("The Beyoncé (Remastered)")
        assert normalize(once) == once


# ---------------------------------------------------------------------------
# levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical_is_zero(self):
        assert levenshtein("kitten", "kitten") == 0

    def test_empty_to_word_is_length(self):
        assert levenshtein("", "abc") == 3
        assert levenshtein("abc", "") == 3

    def test_both_empty_is_zero(self):
        assert levenshtein("", "") == 0

    def test_single_substitution(self):
        assert levenshtein("cat", "bat") == 1

    def test_single_insertion(self):
        assert levenshtein("cat", "cart") == 1

    def test_single_deletion(self):
        assert levenshtein("cart", "cat") == 1

    def test_classic_kitten_sitting(self):
        assert levenshtein("kitten", "sitting") == 3

    def test_symmetric(self):
        assert levenshtein("flaw", "lawn") == levenshtein("lawn", "flaw")


# ---------------------------------------------------------------------------
# classify_field
# ---------------------------------------------------------------------------


class TestClassifyFieldSkipped:
    def test_empty_guess_is_skipped(self):
        assert classify_field("", "Africa") == STATUS_SKIPPED

    def test_whitespace_only_guess_is_skipped(self):
        assert classify_field("   ", "Africa") == STATUS_SKIPPED


class TestClassifyFieldExact:
    def test_identical_is_exact(self):
        assert classify_field("Africa", "Africa") == STATUS_EXACT

    def test_exact_after_normalization(self):
        # Diacritics + case + leading article all normalize away.
        assert classify_field("the beyonce", "Beyoncé") == STATUS_EXACT

    def test_exact_ignores_parenthetical(self):
        assert classify_field("Africa", "Africa (Album Version)") == STATUS_EXACT


class TestClassifyFieldFuzzy:
    def test_one_edit_long_truth_is_fuzzy(self):
        # truth_norm "africa" len 6 >= FUZZY_MIN_LEN(5); 1 edit <= FUZZY_MAX_EDITS(2)
        assert classify_field("afica", "Africa") == STATUS_FUZZY

    def test_two_edits_long_truth_is_fuzzy(self):
        # "rhianna" vs "rihanna": 2 edits, truth len 7
        assert classify_field("Rhianna", "Rihanna") == STATUS_FUZZY

    def test_two_edit_boundary_is_inclusive(self):
        # Exactly FUZZY_MAX_EDITS edits must still be fuzzy.
        truth = "Coldplay"  # normalized len 8
        guess = "Codplaay"  # 2 edits from "coldplay"
        assert FUZZY_MIN_LEN <= len(normalize(truth))
        assert levenshtein(normalize(guess), normalize(truth)) == FUZZY_MAX_EDITS
        assert classify_field(guess, truth) == STATUS_FUZZY


class TestClassifyFieldNearMiss:
    def test_three_edits_is_near_miss(self):
        # > FUZZY_MAX_EDITS -> near miss, even on a long truth.
        truth = "Coldplay"
        guess = "Codplaayy"  # 3 edits from "coldplay"
        assert levenshtein(normalize(guess), normalize(truth)) > FUZZY_MAX_EDITS
        assert classify_field(guess, truth) == STATUS_NEAR_MISS

    def test_short_truth_guard_blocks_fuzzy(self):
        # truth_norm "abba" len 4 < FUZZY_MIN_LEN(5): 2 edits must NOT be fuzzy.
        truth = "ABBA"
        guess = "Adda"  # 2 edits from "abba" but truth too short to fuzz
        assert len(normalize(truth)) < FUZZY_MIN_LEN
        assert levenshtein(normalize(guess), normalize(truth)) <= FUZZY_MAX_EDITS
        assert classify_field(guess, truth) == STATUS_NEAR_MISS

    def test_partial_title_shares_token_is_near_miss(self):
        # A partial guess that shares a real word stays debatable -> near miss.
        assert classify_field("Bohemian", "Bohemian Rhapsody") == STATUS_NEAR_MISS

    def test_close_ratio_is_near_miss(self):
        # Within NEAR_MISS_MAX_RATIO edits of the truth -> near miss.
        assert classify_field("Bohem Rapsody", "Bohemian Rhapsody") == STATUS_NEAR_MISS


class TestClassifyFieldWrong:
    """A guess that is neither close nor token-sharing is just wrong (#1180)."""

    def test_completely_different_is_wrong(self):
        # "Toto" is not a near miss for "Queen" — it's just wrong.
        assert classify_field("Toto", "Queen") == STATUS_WRONG

    def test_different_band_is_wrong(self):
        assert classify_field("Beatles", "Queen") == STATUS_WRONG

    def test_unrelated_long_title_is_wrong(self):
        assert classify_field("Hotel California", "Bohemian Rhapsody") == STATUS_WRONG
