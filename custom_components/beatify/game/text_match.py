"""Pure text-matching helpers for Title & Artist guessing mode (Issue #1180).

This module is intentionally pure and dependency-free: it imports only the
standard library and the project's tuning constants. It backs per-field
classification (title and artist are matched independently) used by the game
challenge, scoring, and serializer layers in later phases.
"""

from __future__ import annotations

import re
import unicodedata

from custom_components.beatify.const import (
    FUZZY_EXTRA_EDIT_LENGTHS,
    FUZZY_MAX_EDITS,
    FUZZY_MIN_LEN,
    NEAR_MISS_MAX_RATIO,
)

# Per-field classification statuses. These exact strings cross the WebSocket
# boundary (serializers + frontend), so do not rename them.
STATUS_EXACT = "exact"
STATUS_FUZZY = "fuzzy"
STATUS_NEAR_MISS = "near_miss"
STATUS_WRONG = "wrong"
STATUS_SKIPPED = "skipped"

# A guess shares a "significant" word with the truth if a token at least this
# long appears in both — catches partial titles ("Bohemian" for "Bohemian
# Rhapsody") that edit-distance ratio alone would call wrong.
_MIN_SHARED_TOKEN_LEN = 4

# Leading article ("the", "a", "an") followed by whitespace.
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")
# A trailing parenthetical qualifier, e.g. "(Remastered)" / "(Album Version)".
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*$")
# A trailing dash-suffix, e.g. " - 2009 Remaster".
_DASH_SUFFIX_RE = re.compile(r"\s+-\s+.*$")
# A featured-artist segment, e.g. "feat. X" / "ft. X" (matches to end).
_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?)\s+.*$", re.IGNORECASE)
# Anything that is not a word character or whitespace (punctuation).
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
# Runs of whitespace.
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_diacritics(text: str) -> str:
    """Return ``text`` with combining diacritical marks removed (é -> e)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize(text: str) -> str:
    """Normalize a title or artist string for matching.

    Pipeline (order matters):
    1. lowercase
    2. Unicode NFD + strip diacritics (é -> e)
    3. strip featured-artist segments (feat. / ft.)
    4. strip trailing qualifiers: dash-suffixes and parentheticals
    5. strip punctuation
    6. collapse whitespace
    7. strip a single leading article ("the" / "a" / "an")
    """
    if not text:
        return ""

    result = text.lower()
    result = _strip_diacritics(result)
    # Strip featured-artist + trailing qualifiers before punctuation removal so
    # the dash / parenthesis anchors still exist.
    result = _FEAT_RE.sub("", result)
    result = _DASH_SUFFIX_RE.sub("", result)
    result = _PARENTHETICAL_RE.sub("", result)
    result = _PUNCT_RE.sub("", result)
    result = _WHITESPACE_RE.sub(" ", result).strip()
    result = _LEADING_ARTICLE_RE.sub("", result)
    return result


def levenshtein(a: str, b: str) -> int:
    """Return the Levenshtein edit distance between ``a`` and ``b``.

    Pure two-row dynamic-programming implementation; no dependencies.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            substitute_cost = previous[j - 1] + (0 if ca == cb else 1)
            current.append(min(insert_cost, delete_cost, substitute_cost))
        previous = current
    return previous[-1]


def fuzzy_budget(truth_len: int) -> int:
    """Allowed fuzzy edit distance for a normalized truth of this length.

    Returns 0 below ``FUZZY_MIN_LEN`` (too short to fuzz — a 2-edit slack on a
    4-char word is half the string). Otherwise the base ``FUZZY_MAX_EDITS`` plus
    one for each ``FUZZY_EXTRA_EDIT_LENGTHS`` threshold the length reaches, so a
    long title tolerates an extra typo a short one would not.
    """
    if truth_len < FUZZY_MIN_LEN:
        return 0
    return FUZZY_MAX_EDITS + sum(1 for t in FUZZY_EXTRA_EDIT_LENGTHS if truth_len >= t)


def _shares_significant_token(a: str, b: str) -> bool:
    """True if normalized strings ``a`` and ``b`` share a word >= the min length."""
    a_tokens = {t for t in a.split() if len(t) >= _MIN_SHARED_TOKEN_LEN}
    b_tokens = {t for t in b.split() if len(t) >= _MIN_SHARED_TOKEN_LEN}
    return bool(a_tokens & b_tokens)


def classify_field(guess: str, truth: str) -> str:
    """Classify a single field guess against the truth.

    Returns one of ``STATUS_SKIPPED``, ``STATUS_EXACT``, ``STATUS_FUZZY``,
    ``STATUS_NEAR_MISS``, ``STATUS_WRONG``.

    The fuzzy auto-accept budget scales with the truth's length (see
    ``fuzzy_budget``). The near-miss band is what goes to the community vote: a
    guess past fuzzy is only a near-miss if it is still plausibly close — within
    ``NEAR_MISS_MAX_RATIO`` edits of the truth, or sharing a significant word
    with it. A guess that is neither (e.g. "Beatles" for "Queen") is just
    ``STATUS_WRONG``: no vote, no points.
    """
    if not guess or not guess.strip():
        return STATUS_SKIPPED

    guess_norm = normalize(guess)
    truth_norm = normalize(truth)

    if guess_norm == truth_norm:
        return STATUS_EXACT

    dist = levenshtein(guess_norm, truth_norm)
    if dist <= fuzzy_budget(len(truth_norm)):
        return STATUS_FUZZY

    longest = max(len(guess_norm), len(truth_norm), 1)
    if dist / longest <= NEAR_MISS_MAX_RATIO or _shares_significant_token(
        guess_norm, truth_norm
    ):
        return STATUS_NEAR_MISS

    return STATUS_WRONG
