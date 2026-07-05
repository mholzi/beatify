"""Tests for the provider-URI-backfill skill (#1289).

Covers the pure logic: Odesli-response → stored URI mapping per provider,
gap detection, resume-cursor / daily-budget accounting, and coverage-report
aggregation. All network calls are mocked — no live HTTP here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
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
    monkeypatch.setattr(bf, "youtube_search_id", lambda *a, **k: "dQw4w9WgXcQ")
    monkeypatch.setattr(bf.time, "sleep", lambda s: None)
    # Keyless Apple iTunes fallback is network → stub it off in these tests.
    monkeypatch.setattr(bf, "resolve_apple_via_itunes", lambda *a, **k: None)
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
    monkeypatch.setattr(bf, "youtube_oembed_verify", lambda *a, **k: True)

    search_calls = {"n": 0}

    def boom_search(*a, **k):
        search_calls["n"] += 1
        return "SHOULDNOTBE1"

    monkeypatch.setattr(bf, "youtube_search_id", boom_search)
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
    monkeypatch.setattr(bf, "youtube_oembed_verify", lambda *a, **k: False)

    search_calls = {"n": 0}

    def real_search(*a, **k):
        search_calls["n"] += 1
        return "dQw4w9WgXcQ"

    monkeypatch.setattr(bf, "youtube_search_id", real_search)
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
