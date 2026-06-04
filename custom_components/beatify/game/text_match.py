"""Pure text-matching helpers for Title & Artist guessing mode (Issue #1180).

This module is intentionally pure and dependency-free: it imports only the
standard library and the project's tuning constants. It backs per-field
classification (title and artist are matched independently) used by the game
challenge, scoring, and serializer layers in later phases.
"""

from __future__ import annotations

import re
import unicodedata

from custom_components.beatify.const import FUZZY_MAX_EDITS, FUZZY_MIN_LEN

# Per-field classification statuses. These exact strings cross the WebSocket
# boundary (serializers + frontend), so do not rename them.
STATUS_EXACT = "exact"
STATUS_FUZZY = "fuzzy"
STATUS_NEAR_MISS = "near_miss"
STATUS_SKIPPED = "skipped"

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


def classify_field(guess: str, truth: str) -> str:
    """Classify a single field guess against the truth.

    Returns one of ``STATUS_SKIPPED``, ``STATUS_EXACT``, ``STATUS_FUZZY``,
    ``STATUS_NEAR_MISS``.
    """
    if not guess or not guess.strip():
        return STATUS_SKIPPED

    guess_norm = normalize(guess)
    truth_norm = normalize(truth)

    if guess_norm == truth_norm:
        return STATUS_EXACT

    if (
        len(truth_norm) >= FUZZY_MIN_LEN
        and levenshtein(guess_norm, truth_norm) <= FUZZY_MAX_EDITS
    ):
        return STATUS_FUZZY

    return STATUS_NEAR_MISS
