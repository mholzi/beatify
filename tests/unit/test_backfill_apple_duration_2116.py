"""Dauer-Zweitmeinung zum Jahres-Gate (#2116).

Gemessen am 13.08.2026: von 20 auswertbaren Jahres-Ablehnungen weichen 14 um
hoechstens 2 s in der Spieldauer ab, 8 davon um exakt 0 ms. Die beiden echten
Fehltreffer weichen um 10,7 s und 38 s ab. Das Jahr trennt nicht, die Dauer tut es.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backfill_apple.py"
_spec = importlib.util.spec_from_file_location("backfill_apple", _SCRIPT)
ba = importlib.util.module_from_spec(_spec)
sys.modules["backfill_apple"] = ba
_spec.loader.exec_module(ba)


# --------------------------------------------------------------------- helper
def _track(**kw):
    base = {
        "artist": "Dinah Washington",
        "title": "Teach Me Tonight",
        "year": 1988,
        "uri": "spotify:track:0004Uy71ku11n3LMpuyf59",
    }
    base.update(kw)
    return base


def _result(**kw):
    base = {
        "artistName": "Dinah Washington",
        "trackName": "Teach Me Tonight",
        "releaseDate": "1954-01-01T12:00:00Z",
        "trackId": 12345,
        "trackTimeMillis": 180000,
    }
    base.update(kw)
    return base


# --------------------------------------------------------------- durations_match
def test_durations_match_exact():
    assert ba.durations_match(180000, 180000) is True


def test_durations_match_within_tolerance():
    assert ba.durations_match(180000, 180920) is True


def test_durations_match_outside_tolerance():
    """2303 ms ist der erste gemessene Fall jenseits der Luecke."""
    assert ba.durations_match(180000, 182303) is False


def test_durations_match_unknown_reference_is_false():
    assert ba.durations_match(None, 180000) is False


def test_durations_match_unknown_candidate_is_false():
    assert ba.durations_match(180000, None) is False


def test_durations_match_zero_is_false():
    assert ba.durations_match(0, 0) is False


def test_durations_match_custom_tolerance():
    assert ba.durations_match(180000, 184000, tolerance_ms=5000) is True


# ------------------------------------------------------------------- evaluate
def test_year_mismatch_rejected_without_duration():
    """Ohne Referenzdauer bleibt es beim bisherigen Verhalten."""
    ok, reason = ba.evaluate(
        _track(), _result(), title_threshold=0.87, year_tolerance=1
    )
    assert ok is False
    assert "off by 34" in reason


def test_year_mismatch_accepted_when_duration_matches():
    """Der Kern von #2116: 34 Jahre daneben, 0 ms Unterschied -> annehmen."""
    ok, reason = ba.evaluate(
        _track(),
        _result(),
        title_threshold=0.87,
        year_tolerance=1,
        ref_duration_ms=180000,
    )
    assert ok is True
    assert "durch Dauer bestaetigt" in reason
    assert "0 ms" in reason


def test_year_mismatch_still_rejected_when_duration_differs():
    """Die Live-Fassung mit 38 s Unterschied bleibt abgelehnt."""
    ok, reason = ba.evaluate(
        _track(),
        _result(trackTimeMillis=218000),
        title_threshold=0.87,
        year_tolerance=1,
        ref_duration_ms=180000,
    )
    assert ok is False
    assert "off by 34" in reason


def test_duration_never_rejects_what_the_year_accepts():
    """Die Dauer ueberstimmt nur in EINE Richtung."""
    ok, _ = ba.evaluate(
        _track(year=1954),
        _result(trackTimeMillis=999999),
        title_threshold=0.87,
        year_tolerance=1,
        ref_duration_ms=180000,
    )
    assert ok is True


def test_duration_does_not_rescue_artist_mismatch():
    ok, reason = ba.evaluate(
        _track(),
        _result(artistName="Ella Fitzgerald"),
        title_threshold=0.87,
        year_tolerance=1,
        ref_duration_ms=180000,
    )
    assert ok is False
    assert "artist" in reason


def test_candidate_without_duration_stays_rejected():
    ok, reason = ba.evaluate(
        _track(),
        _result(trackTimeMillis=None),
        title_threshold=0.87,
        year_tolerance=1,
        ref_duration_ms=180000,
    )
    assert ok is False
    assert "off by 34" in reason


# -------------------------------------------------------------- spotify_track_id
def test_spotify_track_id_parses():
    assert (
        ba.spotify_track_id("spotify:track:0004Uy71ku11n3LMpuyf59")
        == "0004Uy71ku11n3LMpuyf59"
    )


def test_spotify_track_id_rejects_other_forms():
    assert ba.spotify_track_id("deezer://track/123") is None
    assert ba.spotify_track_id(None) is None
    assert ba.spotify_track_id("") is None


def test_spotify_duration_ms_survives_network_error():
    def boom(*a, **kw):
        raise OSError("kein Netz")

    assert (
        ba.spotify_duration_ms("spotify:track:0004Uy71ku11n3LMpuyf59", opener=boom)
        is None
    )


def test_spotify_duration_ms_without_uri_makes_no_request():
    called = []

    def opener(*a, **kw):
        called.append(1)
        raise AssertionError("darf nicht aufgerufen werden")

    assert ba.spotify_duration_ms(None, opener=opener) is None
    assert called == []


# ---------------------------------------------------------- _year_would_reject
def test_year_would_reject_true_on_mismatch():
    assert ba._year_would_reject(_track(), _result(), 1) is True


def test_year_would_reject_false_when_within_tolerance():
    assert ba._year_would_reject(_track(year=1954), _result(), 1) is False


def test_year_would_reject_false_when_year_unknown():
    assert ba._year_would_reject(_track(year=None), _result(), 1) is False
    assert ba._year_would_reject(_track(), _result(releaseDate=""), 1) is False
