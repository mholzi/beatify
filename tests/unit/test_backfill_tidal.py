"""Outcome classification in scripts/backfill_tidal.py (#2200).

The wave has to tell three things apart, and got two of them wrong until
2026-08-16: a hit, a refusal that will never change, and a hiccup worth
retrying. Everything that was not a 429 fell into the last bucket and was never
written to the state file, so all six daily waves re-asked the same permanently
failing tracks forever.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "backfill_tidal.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_tidal", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bt():
    return _load_module()


class _FakeResponse:
    """Minimal stand-in for the context manager urlopen returns."""

    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.song.link", code, "boom", {}, None)


def _patch_urlopen(monkeypatch, bt, behaviour):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        result = behaviour(calls["n"])
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    monkeypatch.setattr(bt.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)
    return calls


def test_tidal_link_is_a_hit(monkeypatch, bt):
    payload = {
        "linksByPlatform": {"tidal": {"url": "https://tidal.com/browse/track/12345"}}
    }
    _patch_urlopen(monkeypatch, bt, lambda _n: payload)

    uri, outcome, status = bt.query_odesli("abc")

    assert outcome == "hit"
    assert uri == "tidal://track/12345"
    assert status is None


def test_200_without_tidal_link_is_a_miss_without_status(monkeypatch, bt):
    _patch_urlopen(monkeypatch, bt, lambda _n: {"linksByPlatform": {"spotify": {}}})

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome) == (None, "miss")
    # No code: this is an empty answer, not a refused request. The distinction
    # is what lets a later reader tell the two apart without re-querying.
    assert status is None


@pytest.mark.parametrize("code", [400, 403, 404, 422])
def test_non_429_client_errors_are_recorded_as_misses(monkeypatch, bt, code):
    """The bug in #2200: these were 'skip' and therefore never written down."""
    calls = _patch_urlopen(monkeypatch, bt, lambda _n: _http_error(code))

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == (None, "miss", code)
    # One shot only — retrying a 4xx verbatim cannot change the answer.
    assert calls["n"] == 1


@pytest.mark.parametrize("code", [500, 502, 503])
def test_server_errors_stay_retryable(monkeypatch, bt, code):
    _patch_urlopen(monkeypatch, bt, lambda _n: _http_error(code))

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == (None, "retry", code)


def test_rate_limit_backs_off_then_gives_up_as_retryable(monkeypatch, bt):
    calls = _patch_urlopen(monkeypatch, bt, lambda _n: _http_error(429))

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == (None, "retry", 429)
    assert calls["n"] == bt.MAX_429_ATTEMPTS


def test_rate_limit_that_clears_still_resolves(monkeypatch, bt):
    payload = {
        "linksByPlatform": {"tidal": {"url": "https://tidal.com/browse/track/777"}}
    }
    _patch_urlopen(monkeypatch, bt, lambda n: _http_error(429) if n == 1 else payload)

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == ("tidal://track/777", "hit", None)


def test_network_error_is_retryable_without_a_status(monkeypatch, bt):
    _patch_urlopen(monkeypatch, bt, lambda _n: urllib.error.URLError("no route"))

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == (None, "retry", None)


def test_unparseable_body_is_retryable(monkeypatch, bt):
    class _Garbage(_FakeResponse):
        def __init__(self):
            self._payload = b"<html>nope</html>"

    def fake_urlopen(req, timeout=None):
        return _Garbage()

    monkeypatch.setattr(bt.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(bt.time, "sleep", lambda _s: None)

    uri, outcome, status = bt.query_odesli("abc")

    assert (uri, outcome, status) == (None, "retry", None)
