"""Tests for the provider-URI-backfill skill (#1289).

Covers the pure logic: Odesli-response → stored URI mapping per provider,
gap detection, resume-cursor / daily-budget accounting, and coverage-report
aggregation. All network calls are mocked — no live HTTP here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# The skill script lives outside the importable package tree, so load it by path.
# Register in sys.modules before exec so dataclass type-resolution works on 3.9.
_SKILL = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "provider-uri-backfill"
    / "scripts"
    / "backfill_provider_uris.py"
)
_spec = importlib.util.spec_from_file_location("backfill_provider_uris", _SKILL)
bf = importlib.util.module_from_spec(_spec)
sys.modules["backfill_provider_uris"] = bf
_spec.loader.exec_module(bf)


# --- spotify_track_id ------------------------------------------------------
def test_spotify_track_id_valid():
    assert (
        bf.spotify_track_id("spotify:track:7aUCLXZ4D4UD5sCgIgxqjl")
        == "7aUCLXZ4D4UD5sCgIgxqjl"
    )


@pytest.mark.parametrize(
    "bad", [None, "", "spotify:album:x", "tidal://track/1", "spotify:track:short"]
)
def test_spotify_track_id_invalid(bad):
    assert bf.spotify_track_id(bad) is None


# --- odesli_to_uris: byte-identical stored formats -------------------------
def test_odesli_maps_tidal_and_deezer_from_entity_ids():
    # Shape mirrors the live response observed 2026-06 (entityUniqueId numeric).
    payload = {
        "linksByPlatform": {
            "tidal": {
                "url": "https://listen.tidal.com/track/33833948",
                "entityUniqueId": "TIDAL_SONG::33833948",
            },
            "deezer": {
                "url": "https://www.deezer.com/track/13111375",
                "entityUniqueId": "DEEZER_SONG::13111375",
            },
        },
        "entitiesByUniqueId": {
            "TIDAL_SONG::33833948": {"id": "33833948"},
            "DEEZER_SONG::13111375": {"id": 13111375},  # int id tolerated
        },
    }
    out = bf.odesli_to_uris(payload)
    assert out["tidal"] == "tidal://track/33833948"
    assert out["deezer"] == "deezer://track/13111375"
    assert "apple_music" not in out  # not in response → not guessed


def test_odesli_falls_back_to_url_when_entity_missing():
    payload = {
        "linksByPlatform": {
            "tidal": {"url": "https://listen.tidal.com/track/150210255"},
            "deezer": {"url": "https://www.deezer.com/track/1035796702"},
        },
        "entitiesByUniqueId": {},
    }
    out = bf.odesli_to_uris(payload)
    assert out["tidal"] == "tidal://track/150210255"
    assert out["deezer"] == "deezer://track/1035796702"


def test_odesli_maps_apple_when_present():
    payload = {
        "linksByPlatform": {
            "appleMusic": {
                "url": "https://music.apple.com/us/album/x/123?i=987654321",
                "entityUniqueId": "ITUNES_SONG::987654321",
            },
        },
        "entitiesByUniqueId": {"ITUNES_SONG::987654321": {"id": "987654321"}},
    }
    out = bf.odesli_to_uris(payload)
    assert out["apple_music"] == "applemusic://track/987654321"


def test_odesli_apple_url_fallback_prefers_song_id():
    # No entity → parse the ?i=<song-id> param, not the album id.
    payload = {
        "linksByPlatform": {
            "appleMusic": {"url": "https://music.apple.com/us/album/foo/111?i=222333"},
        },
        "entitiesByUniqueId": {},
    }
    out = bf.odesli_to_uris(payload)
    assert out["apple_music"] == "applemusic://track/222333"


def test_odesli_empty_and_malformed_safe():
    assert bf.odesli_to_uris({}) == {}
    assert (
        bf.odesli_to_uris({"linksByPlatform": None, "entitiesByUniqueId": None}) == {}
    )


def test_odesli_skips_non_numeric_id():
    payload = {
        "linksByPlatform": {"tidal": {"entityUniqueId": "TIDAL_SONG::abc"}},
        "entitiesByUniqueId": {"TIDAL_SONG::abc": {"id": "not-a-number"}},
    }
    assert "tidal" not in bf.odesli_to_uris(payload)


# --- gap detection ---------------------------------------------------------
def test_song_gaps_detects_missing_and_empty():
    song = {
        "uri_apple_music": "applemusic://track/1",
        "uri_tidal": None,
        "uri_deezer": "",
        # uri_youtube_music absent
    }
    assert set(bf.song_gaps(song)) == {"tidal", "deezer", "youtube_music"}


def test_song_gaps_none_when_complete():
    song = {f: "x" for f in bf.PROVIDER_FIELDS.values()}
    assert bf.song_gaps(song) == []


# --- coverage aggregation --------------------------------------------------
def test_coverage_counts_have_and_fillable():
    songs = [
        {
            "uri": "spotify:track:" + "a" * 22,
            "uri_tidal": "tidal://track/1",
        },  # gaps → fillable
        {
            "uri": "spotify:track:" + "b" * 22,  # all gaps → fillable
        },
        {"uri": None, "uri_tidal": None},  # no spotify uri → not fillable
        {f: "x" for f in bf.PROVIDER_FIELDS.values()}
        | {"uri": "spotify:track:" + "c" * 22},  # complete
    ]
    cov = bf.coverage_for_playlist("p.json", "/p.json", songs)
    assert cov.total == 4
    assert cov.have["tidal"] == 2  # song 0 + complete song
    assert cov.have["apple_music"] == 1  # only the complete song
    assert cov.fillable == 2  # songs 0 and 1


# --- YouTube budget / resume-cursor accounting -----------------------------
def test_budget_spend_and_remaining():
    b = bf.YouTubeBudget(budget=3)
    assert b.can_spend() and b.remaining() == 3
    b.spend()
    b.spend()
    assert b.remaining() == 1 and b.can_spend()
    b.spend()
    assert b.remaining() == 0 and not b.can_spend()


def test_state_roundtrip_resets_daily_keeps_cursor(tmp_path):
    p = tmp_path / "state.json"
    yt = bf.YouTubeBudget(budget=90, spent_today=40, cursor=512, date="2026-06-10")
    bf.save_state(p, yt)
    # Same day → spent_today preserved, cursor preserved.
    same = bf.load_state(p, "2026-06-10", 90)
    assert same.spent_today == 40 and same.cursor == 512
    # New day → counter resets to 0, cursor carries over (resume across days).
    nextday = bf.load_state(p, "2026-06-11", 90)
    assert nextday.spent_today == 0 and nextday.cursor == 512


def test_load_state_missing_file(tmp_path):
    yt = bf.load_state(tmp_path / "nope.json", "2026-06-10", 90)
    assert yt.spent_today == 0 and yt.cursor == 0 and yt.budget == 90


# --- HTTP wrappers with mocked getters -------------------------------------
def test_fetch_odesli_retries_on_429(monkeypatch):
    import urllib.error

    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(url, 429, "rate", {}, None)
        return {"ok": True}

    slept = []
    out = bf.fetch_odesli(
        "x" * 22, sleep=0.01, getter=getter, sleeper=lambda s: slept.append(s)
    )
    assert out == {"ok": True}
    assert calls["n"] == 3
    assert len(slept) == 2 and slept[1] > slept[0]  # exponential backoff


def test_fetch_odesli_404_returns_none():
    import urllib.error

    def getter(url):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    assert bf.fetch_odesli("x" * 22, sleep=0, getter=getter) is None


def test_fetch_odesli_429_exhausted_returns_none_not_raises():
    # #1687: a 429 that outlasts every backoff retry must SKIP (return None),
    # never re-raise — a raise aborts the whole run + discards partial progress.
    import urllib.error

    calls = {"n": 0}

    def getter(url):
        calls["n"] += 1
        raise urllib.error.HTTPError(url, 429, "rate", {}, None)

    slept = []
    out = bf.fetch_odesli(
        "x" * 22,
        sleep=0.01,
        max_retries=2,
        getter=getter,
        sleeper=lambda s: slept.append(s),
    )
    assert out is None  # skipped, not raised
    assert calls["n"] == 3  # initial try + 2 retries
    assert len(slept) == 2  # backed off on each retryable 429


def test_fetch_odesli_other_http_error_returns_none():
    import urllib.error

    def getter(url):
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    assert bf.fetch_odesli("x" * 22, sleep=0, getter=getter) is None


def test_fetch_odesli_network_error_returns_none():
    import urllib.error

    def getter(url):
        raise urllib.error.URLError("no route")

    assert bf.fetch_odesli("x" * 22, sleep=0, getter=getter) is None


# --- version bump (matches backfill_tidal.py) ------------------------------
@pytest.mark.parametrize(
    "old,new",
    [
        ("1.0", "1.1"),
        ("0.1", "0.2"),
        ("1.9", "1.10"),
        ("1.15", "1.16"),
        ("2", "2.1"),
        ("", "1.1"),
        (None, "1.1"),
    ],
)
def test_bump_version(old, new):
    assert bf.bump_version(old) == new


def test_fetch_deezer_isrc_maps_id():
    out = bf.fetch_deezer_isrc("USRE19901615", getter=lambda u: {"id": 2268878307})
    assert out == "2268878307"


def test_fetch_deezer_isrc_no_data():
    out = bf.fetch_deezer_isrc("BAD", getter=lambda u: {"error": {"code": 800}})
    assert out is None


def test_youtube_search_extracts_video_id():
    resp = {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]}
    assert (
        bf.youtube_search_id("KEY", "Rick Astley", "Never Gonna", getter=lambda u: resp)
        == "dQw4w9WgXcQ"
    )


def test_youtube_search_no_items():
    assert bf.youtube_search_id("KEY", "a", "b", getter=lambda u: {"items": []}) is None


def test_youtube_search_ex_reports_hit():
    resp = {"items": [{"id": {"videoId": "dQw4w9WgXcQ"}}]}
    assert bf.youtube_search_ex("KEY", "a", "b", getter=lambda u: resp) == (
        "dQw4w9WgXcQ",
        "hit",
    )


def test_youtube_search_ex_reports_empty_for_no_items():
    """Gesucht, nichts gefunden — die einzige Lage, die einen Miss rechtfertigt."""
    assert bf.youtube_search_ex("KEY", "a", "b", getter=lambda u: {"items": []}) == (
        None,
        "empty",
    )


def test_youtube_search_ex_reports_error_on_exception():
    """Eine gescheiterte Anfrage ist KEIN Beleg gegen den Song."""
    import urllib.error

    def boom(url):
        raise urllib.error.URLError("no route")

    vid, status = bf.youtube_search_ex("KEY", "a", "b", getter=boom)
    assert (vid, status) == (None, "error")


def test_youtube_search_ex_reports_error_on_unusable_id():
    """Antwort da, id unbrauchbar — auch das darf keine Absage werden."""
    resp = {"items": [{"id": {"videoId": "zu-kurz"}}]}
    assert bf.youtube_search_ex("KEY", "a", "b", getter=lambda u: resp) == (
        None,
        "error",
    )


# --- report aggregation ----------------------------------------------------
def test_build_report_has_summary_and_rows():
    cov = bf.PlaylistCoverage(name="p.json", path="/p.json", total=10)
    cov.have = {"apple_music": 8, "tidal": 5, "deezer": 9, "youtube_music": 10}
    cov.filled_this_run = {
        "apple_music": 0,
        "tidal": 3,
        "deezer": 0,
        "youtube_music": 0,
    }
    md = bf.build_report([cov], "2026-06-10", applied=True, yt_phase_note="skipped")
    assert "# Beatify Provider-URI Coverage" in md
    assert "## Summary" in md
    assert "p.json" in md
    assert "DRY-RUN" not in md  # applied=True
    assert "| Tidal |" in md


# --- end-to-end dry-run over a temp repo (no network) ----------------------
def test_run_dry_run_no_mutation(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    playlist = {
        "name": "Test",
        "version": "1.0",
        "tags": [],
        "songs": [
            {
                "artist": "A",
                "title": "T",
                "year": 2000,
                "uri": "spotify:track:" + "a" * 22,
                "isrc": "USRE19901615",
                "fun_fact": "",
                "fun_fact_de": "",
                "fun_fact_es": "",
                "fun_fact_fr": "",
                "fun_fact_nl": "",
            }
        ],
    }
    f = pl_dir / "test.json"
    f.write_text(json.dumps(playlist))

    # No network should be hit in dry-run: gaps are detected and resolvers are
    # called, so mock them to assert no mutation reaches disk anyway.
    monkeypatch.setattr(
        bf,
        "fetch_odesli",
        lambda *a, **k: {
            "linksByPlatform": {"tidal": {"entityUniqueId": "TIDAL_SONG::1"}},
            "entitiesByUniqueId": {"TIDAL_SONG::1": {"id": "1"}},
        },
    )
    monkeypatch.setattr(bf, "fetch_deezer_isrc", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    # Keyless Apple iTunes fallback is network → stub it off in these tests.
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    out = tmp_path / "coverage.md"
    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--output",
            str(out),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    # Dry-run: report written, JSON untouched.
    assert out.exists()
    assert json.loads(f.read_text())["songs"][0].get("uri_tidal") is None
    assert "DRY-RUN" in out.read_text()


def test_run_apply_writes_uri(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    playlist = {
        "name": "Test",
        "version": "1.0",
        "tags": [],
        "songs": [
            {
                "artist": "A",
                "title": "T",
                "year": 2000,
                "uri": "spotify:track:" + "a" * 22,
                "fun_fact": "",
                "fun_fact_de": "",
                "fun_fact_es": "",
                "fun_fact_fr": "",
                "fun_fact_nl": "",
            }
        ],
    }
    f = pl_dir / "test.json"
    f.write_text(json.dumps(playlist))

    monkeypatch.setattr(
        bf,
        "fetch_odesli",
        lambda *a, **k: {
            "linksByPlatform": {
                "tidal": {"entityUniqueId": "TIDAL_SONG::42"},
                "deezer": {"entityUniqueId": "DEEZER_SONG::99"},
            },
            "entitiesByUniqueId": {
                "TIDAL_SONG::42": {"id": "42"},
                "DEEZER_SONG::99": {"id": "99"},
            },
        },
    )
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    # Keyless Apple iTunes fallback is network → stub it off in these tests.
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "coverage.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    doc = json.loads(f.read_text())
    song = doc["songs"][0]
    assert song["uri_tidal"] == "tidal://track/42"
    assert song["uri_deezer"] == "deezer://track/99"
    # #1687 bug 2: --apply bumps the modified playlist's version (minor +1).
    assert doc["version"] == "1.1"


def _write_playlist(pl_dir: Path, name: str, songs: list[dict], version="1.0") -> Path:
    doc = {"name": name, "version": version, "tags": [], "songs": songs}
    f = pl_dir / f"{name}.json"
    f.write_text(json.dumps(doc))
    return f


def test_run_apply_odesli_429_does_not_block_youtube(tmp_path, monkeypatch):
    # #1687 bug 1: a persistent Odesli 429 (fetch_odesli -> None) must NOT stop
    # the independent YouTube phase, which fills uri_youtube_music regardless.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "yt",
        [
            {
                "artist": "Rick Astley",
                "title": "Never Gonna",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    # Odesli hard-rate-limited: skips every song (returns None), never raises.
    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: None)
    monkeypatch.setattr(bf, "youtube_search_ex", lambda *a, **k: ("dQw4w9WgXcQ", "hit"))
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    # Keyless Apple iTunes fallback is network → stub it off in these tests.
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "coverage.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    doc = json.loads(f.read_text())
    song = doc["songs"][0]
    # YouTube filled despite Odesli being down; Odesli providers stay empty.
    assert song["uri_youtube_music"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert song.get("uri_tidal") is None
    assert song.get("uri_deezer") is None
    assert doc["version"] == "1.1"  # file modified → version bumped


def test_run_apply_flushes_partial_progress_on_crash(tmp_path, monkeypatch):
    # #1687 bug 1: progress is flushed per song, so an abort mid-run keeps every
    # song resolved BEFORE the crash instead of discarding the whole wave.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "two",
        [
            {"artist": "A", "title": "1", "uri": "spotify:track:" + "a" * 22},
            {"artist": "B", "title": "2", "uri": "spotify:track:" + "b" * 22},
        ],
    )

    calls = {"n": 0}

    def flaky_odesli(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "linksByPlatform": {"tidal": {"entityUniqueId": "TIDAL_SONG::42"}},
                "entitiesByUniqueId": {"TIDAL_SONG::42": {"id": "42"}},
            }
        raise RuntimeError("simulated mid-run abort")

    monkeypatch.setattr(bf, "fetch_odesli", flaky_odesli)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    # Keyless Apple iTunes fallback is network → stub it off in these tests.
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    with pytest.raises(RuntimeError):
        bf.main(
            [
                "--repo-root",
                str(tmp_path),
                "--apply",
                "--output",
                str(tmp_path / "coverage.md"),
                "--state",
                str(tmp_path / "state.json"),
                "--odesli-sleep",
                "0",
            ]
        )

    doc = json.loads(f.read_text())
    # Song 1 was flushed before the crash on song 2; nothing lost.
    assert doc["songs"][0]["uri_tidal"] == "tidal://track/42"
    assert doc["songs"][1].get("uri_tidal") is None
    assert doc["version"] == "1.1"  # bumped once on the first flush


# ===========================================================================
# #1687-followup: hit-rate levers (userCountry, iTunes+gate, odesli-YT-first)
# ===========================================================================


# --- Lever 1: userCountry=DE reaches Odesli --------------------------------
def test_fetch_odesli_sends_user_country_de():
    import urllib.parse

    seen = {}

    def getter(url):
        seen["url"] = url
        return {"ok": True}

    bf.fetch_odesli("x" * 22, sleep=0, getter=getter)
    assert "userCountry=DE" in seen["url"]
    # Spotify track URL is still the query subject.
    assert "open.spotify.com/track/" in urllib.parse.unquote(seen["url"])


# --- fuzzy title/artist matching (verify-gate primitive) -------------------
def test_titles_match_equal_and_diacritics():
    assert bf.titles_match("Świętokrzyskie", "Swietokrzyskie")
    assert bf.titles_match("Beyoncé", "Beyonce")
    assert bf.titles_match("Zażółć", "Zazolc")  # ż/ó/ł folded


def test_titles_match_strips_qualifiers():
    assert bf.titles_match("Song (Remastered 2011)", "Song")
    assert bf.titles_match("Song - Radio Edit", "Song")
    assert bf.titles_match("Song feat. Other", "Song")


def test_titles_match_rejects_different():
    assert not bf.titles_match("Bohemian Rhapsody", "Stairway to Heaven")
    assert not bf.titles_match("", "Song")


def test_strip_diacritics_polish():
    # Uppercase folds map to lowercase ASCII (matching lowercases anyway).
    assert (
        bf.strip_diacritics("Łódź żółć ćma ń ą ę ś ź ó") == "lodz zolc cma n a e s z o"
    )


# --- Lever 2: Apple iTunes fallback + verify-gate ---------------------------
def test_itunes_fallback_resolves_apple_id_with_gate():
    def getter(url):
        return {
            "results": [
                {
                    "trackId": 555001,
                    "trackName": "Jolka, Jolka Pamiętasz (Remastered)",
                    "artistName": "Budka Suflera",
                }
            ]
        }

    # Gate is fuzzy: a stray "(Remastered)" qualifier is stripped before compare,
    # so title+artist still pass and the numeric trackId is returned.
    aid = bf.resolve_apple_via_itunes(
        {"artist": "Budka Suflera", "title": "Jolka, Jolka Pamiętasz"}, getter=getter
    )
    assert aid == "555001"
    assert bf.apple_uri(aid) == "applemusic://track/555001"


def test_itunes_gate_rejects_wrong_title():
    # iTunes returns a *different* song by a same-ish name → gate must reject,
    # so no Apple URI is set on a niche-catalogue mismatch.
    def getter(url):
        return {
            "results": [
                {
                    "trackId": 999,
                    "trackName": "Completely Different Song",
                    "artistName": "Some Other Band",
                }
            ]
        }

    aid = bf.resolve_apple_via_itunes(
        {"artist": "Budka Suflera", "title": "Jolka Jolka"}, getter=getter
    )
    assert aid is None


def test_itunes_diacritic_variant_matches():
    # Catalogue row carries accents; the storefront index stores ASCII. The
    # folded query variant is what actually returns the result.
    calls = []

    def getter(url):
        calls.append(url)
        # Only the diacritic-folded query ("Zeromski ...") returns a hit.
        if "Zeromski" in url or "zeromski" in url.lower():
            return {
                "results": [
                    {
                        "trackId": 42042,
                        "trackName": "Ballada",
                        "artistName": "Zeromski",
                    }
                ]
            }
        return {"results": []}

    aid = bf.resolve_apple_via_itunes(
        {"artist": "Żeromski", "title": "Ballada"}, getter=getter
    )
    assert aid == "42042"


def test_itunes_alt_artists_fallback():
    # Primary artist does not match the storefront credit, but an alt_artist
    # does → gate passes on the alt.
    def getter(url):
        return {
            "results": [
                {
                    "trackId": 77,
                    "trackName": "Eve Of Destruction",
                    "artistName": "P.F. Sloan",
                }
            ]
        }

    aid = bf.resolve_apple_via_itunes(
        {
            "artist": "Barry McGuire",
            "title": "Eve Of Destruction",
            "alt_artists": ["P.F. Sloan", "The Turtles"],
        },
        getter=getter,
    )
    assert aid == "77"


def test_itunes_returns_none_on_no_results():
    assert (
        bf.resolve_apple_via_itunes(
            {"artist": "A", "title": "T"}, getter=lambda u: {"results": []}
        )
        is None
    )


def test_itunes_search_never_raises_on_http_error():
    import urllib.error

    def getter(url):
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    assert bf.itunes_search("q", getter=getter) == []
    assert (
        bf.resolve_apple_via_itunes({"artist": "A", "title": "T"}, getter=getter)
        is None
    )


# --- Feature-Artists im iTunes-Gate (#2211) ---------------------------------
def _itunes_getter(track_name: str, artist_name: str, track_id: int = 700100):
    """Every query returns the same single row — the gate is what's under test."""

    def getter(url):
        return {
            "results": [
                {
                    "trackId": track_id,
                    "trackName": track_name,
                    "artistName": artist_name,
                }
            ]
        }

    return getter


def test_split_credited_artists_handles_comma_and_semicolon():
    assert bf.split_credited_artists("Justin Bieber, Nicki Minaj") == [
        "Justin Bieber",
        "Nicki Minaj",
    ]
    # Spotify is not consistent about the separator.
    assert bf.split_credited_artists("Tanel Padar;Dave Benton") == [
        "Tanel Padar",
        "Dave Benton",
    ]
    assert bf.split_credited_artists("") == []
    assert bf.split_credited_artists("Prince") == ["Prince"]


def test_itunes_gate_accepts_guest_named_in_track_title():
    # The catalogue joins every credit into one string, iTunes names only the
    # lead and moves the guest into the title. Real case from the 2026-08-17
    # sample (spotify:track:0KTsmr6JOuhxZuiXUha1xC).
    aid = bf.resolve_apple_via_itunes(
        {"artist": "Justin Bieber, Nicki Minaj", "title": "Beauty And A Beat"},
        getter=_itunes_getter("Beauty and a Beat (feat. Nicki Minaj)", "Justin Bieber"),
    )
    assert aid == "700100"


def test_itunes_gate_accepts_guest_named_in_artist_string():
    # Same rule, other side: iTunes carries the guest in ``artistName`` instead
    # of the title (spotify:track:5bGG1abhVIUm6EAa36ipRX).
    aid = bf.resolve_apple_via_itunes(
        {
            "artist": "Asaf Avidan,The Mojos,Wankelmut",
            "title": "One Day / Reckoning Song (Wankelmut Remix) [Radio Edit]",
        },
        getter=_itunes_getter(
            "One Day / Reckoning Song (Wankelmut Remix) [Radio Edit]",
            "Asaf Avidan & The Mojos",
        ),
    )
    assert aid == "700100"


def test_itunes_gate_accepts_two_guests_named_with_ampersand():
    # Three credited names; iTunes keeps the lead and joins the two guests with
    # "&" instead of a comma (spotify:track:5bTRw958W3Gf95RwXgJ2ql).
    aid = bf.resolve_apple_via_itunes(
        {
            "artist": "Jamal, Jambojet, USPM",
            "title": "Policeman (feat. Jambojet, USPM)",
        },
        getter=_itunes_getter("Policeman (feat. Jambojet & USPM)", "Jamal"),
    )
    assert aid == "700100"


def test_itunes_gate_still_rejects_solo_version_of_a_featured_track():
    # The half that keeps the rule from being a loosening: the guest is credited
    # NOWHERE on the iTunes side, so this is the solo cut, not the feature.
    aid = bf.resolve_apple_via_itunes(
        {"artist": "Justin Bieber, Nicki Minaj", "title": "Beauty And A Beat"},
        getter=_itunes_getter("Beauty and a Beat", "Justin Bieber"),
    )
    assert aid is None


def test_itunes_gate_still_rejects_when_catalogue_credits_one_artist():
    # Kayah's Śpij Kochanie Śpij against ``kk8 — … (feat. Kayah)``: the roles are
    # swapped, so it is a different recording. One catalogue name → rule is off.
    aid = bf.resolve_apple_via_itunes(
        {"artist": "Kayah", "title": "Śpij Kochanie Śpij"},
        getter=_itunes_getter("Śpij Kochanie Śpij (feat. Kayah)", "kk8"),
    )
    assert aid is None


def test_itunes_gate_band_name_with_its_own_comma_does_not_leak():
    # "Earth, Wind & Fire" splits into a bogus "guest" that no iTunes row can
    # carry — the rule must therefore not fire and the hit must stay rejected.
    aid = bf.resolve_apple_via_itunes(
        {"artist": "Earth, Wind & Fire", "title": "September"},
        getter=_itunes_getter("September", "Earth"),
    )
    assert aid is None


# --- Lever 3: YouTube Odesli-first + oembed verify --------------------------
def test_odesli_youtube_video_id_extracts():
    payload = {
        "linksByPlatform": {
            "youtube": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&foo=1"}
        }
    }
    assert bf.odesli_youtube_video_id(payload) == "dQw4w9WgXcQ"
    # youtu.be short form + youtubeMusic key.
    assert (
        bf.odesli_youtube_video_id(
            {
                "linksByPlatform": {
                    "youtubeMusic": {"url": "https://youtu.be/abcDEF12345"}
                }
            }
        )
        == "abcDEF12345"
    )
    assert bf.odesli_youtube_video_id({}) is None


def test_youtube_oembed_verify_pass_and_fail():
    def ok(url):
        return {
            "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
            "author_name": "Rick Astley",
        }

    assert bf.youtube_oembed_verify(
        "dQw4w9WgXcQ", "Rick Astley", "Never Gonna Give You Up", getter=ok
    )

    def cover(url):
        return {
            "title": "Never Gonna Give You Up (Live Cover)",
            "author_name": "Some Cover Band",
        }

    # Wrong artist → gate fails (filters covers/live re-uploads).
    assert not bf.youtube_oembed_verify(
        "dQw4w9WgXcQ", "Rick Astley", "Never Gonna Give You Up", getter=cover
    )


def test_youtube_oembed_verify_network_error_false():
    import urllib.error

    def getter(url):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    assert not bf.youtube_oembed_verify("x" * 11, "A", "T", getter=getter)


def test_run_youtube_odesli_first_pass_skips_search_list(tmp_path, monkeypatch):
    # Odesli returns a YouTube link that oembed confirms → uri_youtube_music is
    # filled at 0 quota; the paid search.list must NOT be called.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "ytfirst",
        [
            {
                "artist": "Rick Astley",
                "title": "Never Gonna Give You Up",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    monkeypatch.setattr(
        bf,
        "fetch_odesli",
        lambda *a, **k: {
            "linksByPlatform": {
                "youtube": {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
            }
        },
    )
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf, "youtube_oembed_verify", lambda *a, **k: True)

    search_calls = {"n": 0}

    def boom_search(*a, **k):
        search_calls["n"] += 1
        return "SHOULDNOTBE1", "hit"

    monkeypatch.setattr(bf, "youtube_search_ex", boom_search)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    song = json.loads(f.read_text())["songs"][0]
    assert song["uri_youtube_music"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert search_calls["n"] == 0  # quota saved — no search.list call


def test_run_youtube_oembed_fail_falls_back_to_search_list(tmp_path, monkeypatch):
    # Odesli has a YouTube link but oembed rejects it (cover) → fall back to the
    # paid search.list path, which fills the URI.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "ytfallback",
        [
            {
                "artist": "Rick Astley",
                "title": "Never Gonna Give You Up",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    monkeypatch.setattr(
        bf,
        "fetch_odesli",
        lambda *a, **k: {
            "linksByPlatform": {
                "youtube": {"url": "https://www.youtube.com/watch?v=coverVID1234"}
            }
        },
    )
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf, "youtube_oembed_verify", lambda *a, **k: False)

    search_calls = {"n": 0}

    def real_search(*a, **k):
        search_calls["n"] += 1
        return "dQw4w9WgXcQ", "hit"

    monkeypatch.setattr(bf, "youtube_search_ex", real_search)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    song = json.loads(f.read_text())["songs"][0]
    assert song["uri_youtube_music"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert search_calls["n"] == 1  # oembed failed → paid path used


def _yt_only_playlist(tmp_path):
    """Ein Song, dem nur die YouTube-URI fehlt."""
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    return _write_playlist(
        pl_dir,
        "ytmiss",
        [
            {
                "artist": "Rick Astley",
                "title": "Never Gonna Give You Up",
                "uri": "spotify:track:" + "a" * 22,
                "uri_apple_music": "applemusic://track/1",
                "uri_tidal": "tidal://track/1",
                "uri_deezer": "deezer://track/1",
            }
        ],
    )


def _run_yt(tmp_path, extra=()):
    return bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
            *extra,
        ]
    )


def test_run_records_youtube_miss_when_search_finds_nothing(tmp_path, monkeypatch):
    """Gesucht und nichts gefunden -> Absage im Cache, damit der naechste Lauf
    dieselbe Luecke nicht erneut Quote kostet."""
    _yt_only_playlist(tmp_path)
    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: {"linksByPlatform": {}})
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf, "youtube_search_ex", lambda *a, **k: (None, "empty"))
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    assert _run_yt(tmp_path) == 0
    misses = json.loads((tmp_path / "state.json").read_text())["provider_misses"]
    entry = misses["spotify:track:" + "a" * 22]
    assert "youtube_music" in entry


def test_run_records_no_youtube_miss_on_search_error(tmp_path, monkeypatch):
    """Eine gescheiterte Anfrage darf keine 90-Tage-Sperre erzeugen."""
    _yt_only_playlist(tmp_path)
    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: {"linksByPlatform": {}})
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf, "youtube_search_ex", lambda *a, **k: (None, "error"))
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    assert _run_yt(tmp_path) == 0
    misses = json.loads((tmp_path / "state.json").read_text()).get(
        "provider_misses", {}
    )
    entry = misses.get("spotify:track:" + "a" * 22, {})
    assert "youtube_music" not in entry


def test_run_records_no_youtube_miss_when_budget_exhausted(tmp_path, monkeypatch):
    """Der Fall, der die Ausnahme urspruenglich begruendet hat: ohne Aufruf
    keine Absage."""
    _yt_only_playlist(tmp_path)
    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: {"linksByPlatform": {}})
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)

    def must_not_run(*a, **k):
        raise AssertionError("search.list darf bei aufgebrauchtem Budget nicht laufen")

    monkeypatch.setattr(bf, "youtube_search_ex", must_not_run)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.setenv("YOUTUBE_API_KEY", "KEY")

    assert _run_yt(tmp_path, ["--youtube-budget", "0"]) == 0
    misses = json.loads((tmp_path / "state.json").read_text()).get(
        "provider_misses", {}
    )
    entry = misses.get("spotify:track:" + "a" * 22, {})
    assert "youtube_music" not in entry


def test_run_apply_itunes_fills_apple_when_odesli_lacks_it(tmp_path, monkeypatch):
    # Odesli returns Tidal only (no Apple) → the iTunes fallback fills Apple.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "apple",
        [
            {
                "artist": "Budka Suflera",
                "title": "Jolka Jolka",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    monkeypatch.setattr(
        bf,
        "fetch_odesli",
        lambda *a, **k: {
            "linksByPlatform": {"tidal": {"entityUniqueId": "TIDAL_SONG::7"}},
            "entitiesByUniqueId": {"TIDAL_SONG::7": {"id": "7"}},
        },
    )
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: "808080")
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    song = json.loads(f.read_text())["songs"][0]
    assert song["uri_tidal"] == "tidal://track/7"
    assert song["uri_apple_music"] == "applemusic://track/808080"


# --------------------------------------------------------------------------
# Run caps: --max / --max-minutes (parity with scripts/backfill_tidal.py)
#
# Motivation: without a cap a single run is unbounded. Odesli's 429 backoff makes
# duration far less predictable than query count, so one 100-track playlist can
# outlast the scheduling window a caller reserved for it — which is exactly how
# the youtube-backfill agent collided with the hourly Tidal wave on 2026-08-10.
# --------------------------------------------------------------------------


def _capped_songs(n: int) -> list[dict]:
    return [
        {
            "artist": f"Artist {i}",
            "title": f"Title {i}",
            "uri": "spotify:track:" + f"{i:022d}",
        }
        for i in range(n)
    ]


def test_max_caps_odesli_queries(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    _write_playlist(pl_dir, "many", _capped_songs(10))

    calls = []
    monkeypatch.setattr(bf, "fetch_odesli", lambda sid, **k: calls.append(sid) or None)
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
            "--max",
            "3",
        ]
    )
    assert rc == 0
    # Exactly three attempts, not ten — and counted per attempt, so a run that
    # only ever gets 429s (fetch_odesli -> None) still terminates.
    assert len(calls) == 3


def test_max_minutes_stops_run(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    _write_playlist(pl_dir, "many", _capped_songs(10))

    calls = []
    # Clock jumps past the deadline after the second song's check.
    ticks = iter([0, 0, 0, 10_000, 10_000, 10_000, 10_000, 10_000, 10_000, 10_000])
    monkeypatch.setattr(bf.time, "monotonic", lambda: next(ticks, 10_000))
    monkeypatch.setattr(bf, "fetch_odesli", lambda sid, **k: calls.append(sid) or None)
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
            "--max-minutes",
            "1",
        ]
    )
    assert rc == 0
    assert len(calls) < 10  # stopped early, did not walk the whole playlist


def test_no_cap_by_default_walks_everything(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    _write_playlist(pl_dir, "many", _capped_songs(6))

    calls = []
    monkeypatch.setattr(bf, "fetch_odesli", lambda sid, **k: calls.append(sid) or None)
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    assert len(calls) == 6  # defaults stay uncapped — no behaviour change


def test_capped_run_marks_report_as_partial(tmp_path, monkeypatch):
    # A truncated run must not read like a complete one. Same failure mode that
    # made the youtube-backfill agent report "nochange" on a broken run.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    _write_playlist(pl_dir, "many", _capped_songs(5))

    monkeypatch.setattr(bf, "fetch_odesli", lambda sid, **k: None)
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    cov = tmp_path / "cov.md"
    bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(cov),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
            "--max",
            "2",
        ]
    )
    text = cov.read_text()
    assert "stopped early" in text
    assert "reached --max 2" in text

    # And the uncapped run says nothing of the sort.
    cov2 = tmp_path / "cov2.md"
    bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(cov2),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert "stopped early" not in cov2.read_text()


# --------------------------------------------------------------------------
# Deezer search fallback (parity with the Apple iTunes fallback)
#
# Motivation: the ISRC endpoint is exact but only as good as the stored ISRC.
# Measured 2026-08-10 on greatest-metal-songs — "Iron Man", "Paranoid",
# "The Trooper" and "The Number of the Beast" all carry reissue ISRCs Deezer
# does not index, while Deezer holds earlier remasters of the same recordings.
# Apple had a search fallback, Deezer did not; whole playlists sat at 0 Deezer.
# --------------------------------------------------------------------------


def _dz(track_id, title, artist):
    return {
        "id": track_id,
        "title": title,
        "title_short": title,
        "artist": {"name": artist},
    }


def test_deezer_search_gate_accepts_matching_artist_and_title():
    hit = bf._pick_deezer_match(
        [_dz(3788156072, "Iron Man (Remastered 2009)", "Black Sabbath")],
        "Iron Man",
        "Black Sabbath",
        [],
    )
    assert hit == "3788156072"


def test_deezer_search_gate_rejects_wrong_artist():
    # A cover band with the exact right title must NOT pass — this is the whole
    # point of the gate. Title-only matching would happily return it.
    assert (
        bf._pick_deezer_match(
            [_dz(999, "Iron Man", "Karaoke Allstars")], "Iron Man", "Black Sabbath", []
        )
        is None
    )


def test_deezer_search_gate_accepts_alt_artist():
    hit = bf._pick_deezer_match(
        [_dz(555, "Paranoid", "Ozzy Osbourne")],
        "Paranoid",
        "Black Sabbath",
        ["Ozzy Osbourne"],
    )
    assert hit == "555"


def test_deezer_search_gate_skips_results_without_id():
    assert (
        bf._pick_deezer_match(
            [{"title": "Iron Man", "artist": {"name": "Black Sabbath"}}],
            "Iron Man",
            "Black Sabbath",
            [],
        )
        is None
    )


def test_resolve_deezer_via_search_stops_at_first_gate_pass():
    calls = []

    def getter(url):
        calls.append(url)
        if "Iron%20Man" in url or "Iron+Man" in url:
            return {"data": [_dz(42, "Iron Man (Remastered 2009)", "Black Sabbath")]}
        return {"data": []}

    got = bf.resolve_deezer_via_search(
        {"artist": "Black Sabbath", "title": "Iron Man"}, getter=getter
    )
    assert got == "42"
    assert len(calls) == 1  # first, most-specific term already passed


def test_resolve_deezer_via_search_returns_none_when_nothing_matches():
    got = bf.resolve_deezer_via_search(
        {"artist": "Black Sabbath", "title": "Iron Man"},
        getter=lambda url: {"data": [_dz(7, "Totally Different Song", "Someone Else")]},
    )
    assert got is None


def test_deezer_search_never_raises_on_http_error():
    def boom(url):
        raise RuntimeError("network down")

    assert bf.deezer_search("anything", getter=boom) == []


def test_deezer_search_treats_api_error_payload_as_empty():
    assert (
        bf.deezer_search("x", getter=lambda url: {"error": {"type": "Exception"}}) == []
    )


def test_run_apply_uses_deezer_search_when_isrc_and_odesli_miss(tmp_path, monkeypatch):
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "metal",
        [
            {
                "artist": "Black Sabbath",
                "title": "Iron Man",
                "isrc": "USWB11304371",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: None)  # Odesli down
    monkeypatch.setattr(bf, "fetch_deezer_isrc", lambda *a, **k: None)  # ISRC misses
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: "3788156072")
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    assert (
        json.loads(f.read_text())["songs"][0]["uri_deezer"]
        == "deezer://track/3788156072"
    )


def test_deezer_isrc_runs_even_when_odesli_is_down(tmp_path, monkeypatch):
    # Regression 2026-08-10: the ISRC lookup sat INSIDE the `payload is not None`
    # block, so a 429 from Odesli skipped it entirely — Deezer got nothing while
    # Apple kept filling via its own fallback. That asymmetry is what left whole
    # playlists at full Apple / zero Deezer coverage.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "dz",
        [
            {
                "artist": "Efecto Pasillo",
                "title": "No importa que llueva",
                "isrc": "ES24C1207102",
                "uri": "spotify:track:" + "a" * 22,
            }
        ],
    )

    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: None)  # 429 / down
    monkeypatch.setattr(bf, "fetch_deezer_isrc", lambda isrc, **k: "438648342")
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(bf, "resolve_deezer_via_search", lambda *a, **k: None)
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    rc = bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert rc == 0
    assert (
        json.loads(f.read_text())["songs"][0]["uri_deezer"]
        == "deezer://track/438648342"
    )


def test_deezer_isrc_wins_over_search(tmp_path, monkeypatch):
    # The exact ISRC hit is preferred; the search fallback must not be consulted
    # when it already resolved — otherwise every song costs an extra HTTP call.
    pl_dir = tmp_path / "custom_components" / "beatify" / "playlists"
    pl_dir.mkdir(parents=True)
    f = _write_playlist(
        pl_dir,
        "dz2",
        [
            {
                "artist": "Maan",
                "title": "Stiekem",
                "isrc": "NLZ292200147",
                "uri": "spotify:track:" + "b" * 22,
            }
        ],
    )
    searched = []
    monkeypatch.setattr(bf, "fetch_odesli", lambda *a, **k: None)
    monkeypatch.setattr(bf, "fetch_deezer_isrc", lambda isrc, **k: "3606658082")
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
    monkeypatch.setattr(
        bf, "resolve_deezer_via_search", lambda *a, **k: searched.append(1) or "999"
    )
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)

    bf.main(
        [
            "--repo-root",
            str(tmp_path),
            "--apply",
            "--output",
            str(tmp_path / "cov.md"),
            "--state",
            str(tmp_path / "state.json"),
            "--odesli-sleep",
            "0",
        ]
    )
    assert (
        json.loads(f.read_text())["songs"][0]["uri_deezer"]
        == "deezer://track/3606658082"
    )
    assert searched == []  # search never consulted


# ---------------------------------------------------------------------------
# Per-Provider-Miss-Cache (13.08.2026)
#
# Kernzusage: was einmal nachweislich fehlt, wird nicht erneut abgefragt — aber
# eine Sperre darf NIE als Absage durchgehen, und ein Miss verfaellt.
# ---------------------------------------------------------------------------
_NOW = datetime(2026, 8, 13, 10, 0)


def _stamp(days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%MZ")


def test_filter_cached_misses_drops_fresh_miss():
    misses = {"spotify:track:A": {"deezer": _stamp(1)}}
    got = bf.filter_cached_misses(
        ["deezer", "apple_music"], "spotify:track:A", misses, _NOW
    )
    assert got == ["apple_music"]


def test_filter_cached_misses_keeps_other_providers_of_same_track():
    """Ein Miss bei Deezer darf Apple desselben Songs nicht mit abwuergen."""
    misses = {"spotify:track:A": {"deezer": _stamp(1)}}
    got = bf.filter_cached_misses(
        ["apple_music", "tidal", "deezer"], "spotify:track:A", misses, _NOW
    )
    assert got == ["apple_music", "tidal"]


def test_filter_cached_misses_expires_after_ttl():
    misses = {"spotify:track:A": {"deezer": _stamp(120)}}
    got = bf.filter_cached_misses(
        ["deezer"], "spotify:track:A", misses, _NOW, ttl_days=90
    )
    assert got == ["deezer"]


def test_filter_cached_misses_ttl_zero_never_expires():
    misses = {"spotify:track:A": {"deezer": _stamp(9999)}}
    got = bf.filter_cached_misses(
        ["deezer"], "spotify:track:A", misses, _NOW, ttl_days=0
    )
    assert got == []


def test_filter_cached_misses_retry_flag_ignores_cache():
    misses = {"spotify:track:A": {"deezer": _stamp(1)}}
    got = bf.filter_cached_misses(
        ["deezer"], "spotify:track:A", misses, _NOW, retry_misses=True
    )
    assert got == ["deezer"]


def test_filter_cached_misses_unparsable_stamp_is_retried():
    misses = {"spotify:track:A": {"deezer": "kaputt"}}
    got = bf.filter_cached_misses(["deezer"], "spotify:track:A", misses, _NOW)
    assert got == ["deezer"]


def test_record_provider_misses_only_for_unfilled():
    song = {"uri_deezer": "deezer://track/1"}
    misses = {}
    n = bf.record_provider_misses(
        misses, "spotify:track:A", ["deezer", "apple_music"], song, _NOW
    )
    assert n == 1
    assert list(misses["spotify:track:A"]) == ["apple_music"]


def test_record_provider_misses_records_nothing_when_all_filled():
    song = {"uri_deezer": "deezer://track/1", "uri_apple_music": "applemusic://track/2"}
    misses = {}
    n = bf.record_provider_misses(
        misses, "spotify:track:A", ["deezer", "apple_music"], song, _NOW
    )
    assert n == 0
    assert misses == {}


def test_record_provider_misses_ignores_empty_string_field():
    song = {"uri_deezer": "   "}
    misses = {}
    bf.record_provider_misses(misses, "spotify:track:A", ["deezer"], song, _NOW)
    assert "deezer" in misses["spotify:track:A"]


def test_miss_cache_roundtrip_preserves_other_state_keys(tmp_path):
    """save_provider_misses darf den YouTube-Budgetblock nicht zerstoeren."""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"youtube": {"budget": 90, "cursor": 7}}))
    bf.save_provider_misses(p, {"spotify:track:A": {"deezer": _stamp(0)}})
    data = json.loads(p.read_text())
    assert data["youtube"] == {"budget": 90, "cursor": 7}
    assert bf.load_provider_misses(p) == {"spotify:track:A": {"deezer": _stamp(0)}}


def test_load_provider_misses_tolerates_missing_and_broken_file(tmp_path):
    assert bf.load_provider_misses(tmp_path / "fehlt.json") == {}
    bad = tmp_path / "kaputt.json"
    bad.write_text("{nicht json")
    assert bf.load_provider_misses(bad) == {}


def test_attempted_providers_with_odesli_covers_all_gaps():
    assert bf.attempted_providers(["apple_music", "tidal", "deezer"], True) == [
        "apple_music",
        "tidal",
        "deezer",
    ]


def test_attempted_providers_without_odesli_excludes_tidal():
    """Die Kernregel: eine Odesli-Sperre darf NIE zu einem Tidal-Miss werden."""
    assert bf.attempted_providers(["apple_music", "tidal", "deezer"], False) == [
        "apple_music",
        "deezer",
    ]


def test_attempted_providers_without_odesli_and_only_tidal_is_empty():
    assert bf.attempted_providers(["tidal"], False) == []
