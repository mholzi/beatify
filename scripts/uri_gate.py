"""Shared verify-gate primitives for the URI resolvers.

Both resolvers guess: they query a search endpoint with artist + title and have
to decide whether the first plausible hit is really *our* recording. That
decision used to live twice, in two different shapes:

* ``scripts/backfill_apple.py`` — iTunes search, four rules (artist membership,
  title similarity, suffix conflict, year tolerance). Hardened over #1980,
  #2007 and #2030.
* ``.claude/skills/provider-uri-backfill/scripts/backfill_provider_uris.py`` —
  the all-rounder for Apple/Tidal/Deezer/YouTube. Its gate is a Levenshtein
  match on title and artist.

Measured on 2026-08-11, the second one **cannot tell a remix from the
original**: its ``normalize_title`` strips parentheticals before comparing, so
``The Night`` and ``The Night (Extended Mix)`` are equal to it. That is exactly
the regression #1980 fixed in the Apple script — and the Apple backfill agent
runs on the all-rounder.

This module holds the pieces both need, so a fix lands in one place. It is
deliberately dependency-free (only ``re`` and ``unicodedata``) and free of I/O,
so it can be imported by a script in any directory and unit-tested on its own.

Kept out of here on purpose: ``title_similarity`` and ``release_year``, which
are specific to the Apple script's thresholds, and ``normalize_title`` /
``levenshtein`` from the all-rounder, which serve its own fuzzy stage.
"""

from __future__ import annotations

import re
import unicodedata

_FEAT_RE = re.compile(r"\s*[\(\[]?\b(feat|ft|featuring|with)\b\.?\s.*$", re.I)
_PAREN_RE = re.compile(r"\s*[\(\[][^)\]]*[)\]]")
_PAREN_CONTENT_RE = re.compile(r"[\(\[]([^)\]]*)[)\]]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_ARTIST_SPLIT_RE = re.compile(r"\s*[,;/]\s*|\s+(?:&|feat\.?|ft\.?|x|vs\.?)\s+", re.I)
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|der|die|das|los|las|le|la|les)\s+", re.I)

# Parenthetical suffixes that name the same *recording* — packaging or mastering
# wording, not a different take. Only these may appear on one side alone.
# Deliberately a short closed list: every entry here is a licence to accept a
# title the other side does not carry, so it is reviewed in the diff.
_NEUTRAL_SUFFIX_RE = re.compile(
    r"^(?:\d{4}\s+)?(?:digital\s+)?(?:"
    r"remaster(?:ed)?(?:\s+version)?(?:\s+\d{4})?"
    r"|deluxe(?:\s+edition)?"
    r"|album\s+version"
    r"|single\s+version"
    r"|original\s+(?:version|mix)"
    r"|bonus\s+track"
    r"|explicit|clean"
    r")$",
    re.I,
)

# Apple appends an origin credit to film music instead of a take marker:
# "Zwei Seelen (aus \"Die Schoene und das Biest\" deutscher Film-Soundtrack)".
# That says WHERE the recording comes from, not WHICH recording it is — and in
# the 2026-08-09 probe run it was the largest single group among the 19 suffix
# rejections (Beauty and the Beast, Tangled, Hercules, Mulan). Deliberately
# narrow: must start with "aus"/"from" AND end in "soundtrack", so a bare
# "(Motion Picture Version)" — which can genuinely be a different take — keeps
# being rejected.
_SOUNDTRACK_ORIGIN_RE = re.compile(
    r"^(?:aus|from)\s+.+\ssoundtrack$|^original\s+motion\s+picture\s+soundtrack$",
    re.I,
)


def normalise(text: str, *, drop_parens: bool = False) -> str:
    """Fold a title/artist to a comparable form.

    Deliberately conservative: diacritics are kept (``Böhse`` must not collapse
    onto ``Bohse`` and start matching unrelated artists), only case, punctuation,
    ``&``/``and`` and whitespace are unified.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = _FEAT_RE.sub("", out)
    if drop_parens:
        out = _PAREN_RE.sub("", out)
    out = out.casefold()
    out = out.replace("&", " and ")
    out = _PUNCT_RE.sub(" ", out)
    return _WS_RE.sub(" ", out).strip()


def primary_artist(artist: str) -> str:
    """First credited artist — search results carry the lead artist only."""
    if not artist:
        return ""
    return _ARTIST_SPLIT_RE.split(artist, maxsplit=1)[0]


def artist_set(artist: str) -> set[str]:
    """All credited artists, normalised.

    Split on the raw string, not the normalised one: ``normalise`` turns ``&``
    into ``and``, which would stop it being a separator.
    """
    if not artist:
        return set()
    return {n for n in (normalise(p) for p in _ARTIST_SPLIT_RE.split(artist)) if n}


def _artist_variants(name: str) -> set[str]:
    """Comparable spellings of one credited artist.

    All four variants come from real rejections in the 2026-08-09 probe run over
    861 missing Apple URIs — 38 of 137 rejections were artist mismatches, and
    every one of them was a spelling difference, not a different act:

    * ``Jackson 5`` vs ``The Jackson 5`` — a leading article.
    * ``MadHouse`` vs ``Mad'House`` — an apostrophe. ``normalise`` turns
      punctuation into a space, so the two differ by exactly that space.
    * ``Run-DMC`` vs ``Run-D.M.C.`` — dots inside an abbreviation, again a
      space after normalisation.
    * ``Frozen - Cast`` vs ``Cast - Frozen`` — the same credit, reordered.

    The space-free variant is what folds the apostrophe and the dots; it is
    computed from the article-stripped form so ``The Jackson 5`` also yields
    ``jackson5``.
    """
    base = normalise(name)
    if not base:
        return set()
    stripped = _LEADING_ARTICLE_RE.sub("", base).strip()
    out = {base, stripped}
    out |= {v.replace(" ", "") for v in (base, stripped)}
    out.add(" ".join(sorted(stripped.split())))
    return {v for v in out if v}


def artist_matches(want: str, got: str) -> bool:
    """True when ``want`` (our primary artist) is credited in ``got``.

    Two rules, in order of strictness:

    1. Any spelling variant of ``want`` equals a variant of any artist credited
       in ``got``.
    2. ``want`` appears in the full credit as a **contiguous run of at least
       two tokens** — ``Jimi Hendrix`` inside ``The Jimi Hendrix Experience``.
       Deliberately not a substring test and deliberately one-directional: it
       must be *our* artist that is contained, and a single token is never
       enough.

    Rule 2 is what keeps the real false positives out. In the same probe run
    iTunes answered ``The Parachute Club`` for our ``Paul Kalkbrenner`` and an
    ensemble credit for our ``Phil Collins`` — neither shares a token run with
    ours, so both stay rejected. Loosening this to a plain substring or to
    single tokens would let exactly those through.
    """
    want_variants = _artist_variants(want)
    if not want_variants:
        return False
    for credited in _ARTIST_SPLIT_RE.split(got or ""):
        if want_variants & _artist_variants(credited):
            return True
    want_tokens = _LEADING_ARTICLE_RE.sub("", normalise(want)).split()
    if len(want_tokens) >= 2:
        run = " ".join(want_tokens)
        if run and run in normalise(got or ""):
            return True
    return False


def parenthetical_suffixes(text: str) -> list[str]:
    """Normalised contents of every ``(...)``/``[...]`` group.

    ``feat.``-tails are cut first — ``normalise`` already handles those, and a
    featured guest is not a different recording.
    """
    if not text:
        return []
    cleaned = _FEAT_RE.sub("", text)
    out = []
    for raw in _PAREN_CONTENT_RE.findall(cleaned):
        norm = normalise(raw)
        if norm:
            out.append(norm)
    return out


def suffix_conflict(a: str, b: str) -> str | None:
    """The first suffix that one title carries and the other does not account for.

    A fuzzy title comparison that ignores parentheticals cannot separate
    ``(2000 Remaster)`` from ``(Extended Mix)`` — both look like the same title
    with something appended. So the suffix has to be inspected directly.

    A suffix is fine when either

      * the other side mentions it anywhere in its title (``The Afterlife -
        Radio Edit`` vs ``The Afterlife (Radio Edit)`` — same words, different
        punctuation), or
      * it is recording-neutral per :data:`_NEUTRAL_SUFFIX_RE`, or
      * it is an origin credit per :data:`_SOUNDTRACK_ORIGIN_RE`.

    Anything else names a different take and is returned for rejection.
    """
    for src, other in ((a, b), (b, a)):
        other_norm = normalise(other)
        for suffix in parenthetical_suffixes(src):
            if suffix in other_norm:
                continue
            if _NEUTRAL_SUFFIX_RE.match(suffix):
                continue
            if _SOUNDTRACK_ORIGIN_RE.match(suffix):
                continue
            return suffix
    return None
