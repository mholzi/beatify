"""iTunes 403 is throttling, Spotify 403 is a restricted track.

The comment above ``check_apple_music`` has always promised "iTunes throttles
hard (403/429) — never call a track dead on that", but 403 was not in
``TRANSIENT_CODES``, so an iTunes 403 came back as ``unreachable`` rather than
as a transient. Harmless on its own, and invisible until a long Apple backfill
run put iTunes into throttling for hours.

Adding 403 to the shared set would have been the obvious fix and the wrong one:
Spotify answers 403 for a track that really is restricted, so the same change
would turn a genuine defect into a retried non-finding and spend ~20 seconds of
backoff on each one. The iTunes reading therefore lives in
``check_apple_music``, where 403 can only mean throttling.

These tests pin both halves of that split.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".claude/skills/playlist-health-check/scripts/validate_uris.py"
)


@pytest.fixture()
def validator():
    """A fresh module per test — each one swaps out http_json."""
    spec = importlib.util.spec_from_file_location("validate_uris_403", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _answer(code, transient=False, calls=None):
    """Stand in for http_json and always fail with `code`."""

    def fake(url, headers=None, timeout=10, retry_404=False):
        if calls is not None:
            calls.append(url)
        return None, code, transient

    return fake


def test_itunes_403_is_transient_not_a_defect(validator):
    validator.http_json = _answer(403)
    result = validator.check_apple_music("1440834619", "American Pie", "Don McLean")

    assert result["status"] == "error"
    assert result["transient"] is True
    assert result["status"] != "dead"


def test_itunes_403_does_not_walk_all_three_storefronts(validator):
    """Throttling is about the caller, not the storefront — retrying us/de/gb
    triples the load on a service that just asked us to slow down."""
    calls = []
    validator.http_json = _answer(403, calls=calls)
    validator.check_apple_music("1440834619", "American Pie", "Don McLean")

    assert len(calls) == 1


def test_spotify_403_still_means_restricted(validator):
    """The reason 403 stays out of TRANSIENT_CODES."""
    validator.http_json = _answer(403)
    result = validator.check_spotify("5A3IdgGphzKS2etiGFB73S", "Das Boot", "U96")

    assert result["status"] == "dead"
    assert result["detail"] == "Restricted"


def test_403_stays_out_of_the_shared_transient_set(validator):
    assert 403 not in validator.TRANSIENT_CODES
    # The codes that really are provider-side stay in.
    assert {429, 500, 503}.issubset(validator.TRANSIENT_CODES)


def test_itunes_404_still_walks_the_storefronts(validator):
    """The fallback that #1957-era runs depend on must survive the change."""
    calls = []
    validator.http_json = _answer(404, calls=calls)
    result = validator.check_apple_music("1", "T", "A")

    assert len(calls) == 3
    assert result["status"] == "dead"


@pytest.mark.parametrize("code", [429, 500, 503])
def test_itunes_other_throttle_codes_unchanged(validator, code):
    validator.http_json = _answer(code, transient=True)
    result = validator.check_apple_music("1", "T", "A")

    assert result["status"] == "error"
    assert result["transient"] is True
