"""#2939 — a Music Assistant playlist as the song source for Crate Digger.

Three things are pinned here:

* **Matching.** Playlist tracks from a provider playlist carry the provider's
  URI (``apple_music://track/1440867473``, observed on a live MA 2.8 box), not
  the ``library://track/N`` the pool stores. A pure URI intersection would
  match nothing, so the classifier matches by library URI first and by
  normalized artist + title second.
* **The explanation.** Every dropped track lands in exactly one reason bucket,
  so the panel can say "37 of 45 usable" and why.
* **The draw.** ``only_uris`` restricts the generator to the playlist and
  switches off popularity, genres and the recently-played exclusion — the host
  already made the selection.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.library import generator as gen
from custom_components.beatify.library.config import (
    YEAR_GATES,
    parse_library_source,
    sanitize_ma_playlist,
)
from custom_components.beatify.library.ma_client import (
    async_fetch_playlist_tracks,
    normalize_playlist_track,
)
from custom_components.beatify.library.playlist_source import (
    classify_playlist_tracks,
)
from custom_components.beatify.library.year_resolver import YearConfidence
from custom_components.beatify.server.library_views import (
    playlist_check_payload,
    sanitize_library_settings,
)

STRICT = YEAR_GATES["strict"]


def pool_song(i, *, title=None, artist=None, year=1985, conf=None, pctl=0.9):
    return {
        "title": title or f"T{i}",
        "artist": artist or f"A{i}",
        "uri_ma_library": f"library://track/{i}",
        "genres": ["Rock"],
        "year": year,
        "year_confidence": int(
            conf if conf is not None else YearConfidence.EXTERNAL_PRIMARY
        ),
        "popularity_percentile": pctl,
        "global_score": pctl * 100,
    }


def pl_track(title, artist, uri, *, library_uri=None, in_library=None, artists=None):
    return {
        "title": title,
        "artist": artist,
        "artists": artists or [artist],
        "uri": uri,
        "library_uri": library_uri,
        "in_library": in_library,
    }


class TestMatching:
    def test_library_uri_on_the_track_matches_directly(self):
        pool = [pool_song(131, title="Nie mehr Fastelovend", artist="Querbeat")]
        tracks = [
            pl_track(
                "Nie mehr Fastelovend",
                "Querbeat",
                "library://track/131",
                library_uri="library://track/131",
                in_library=True,
            )
        ]
        out = classify_playlist_tracks(tracks, pool, min_confidence=STRICT)
        assert out["usable_uris"] == ["library://track/131"]

    def test_provider_uri_matches_through_its_library_twin(self):
        """The observed shape: apple_music:// on the track, library twin resolved."""
        pool = [pool_song(131, title="Something Else", artist="Nobody")]
        tracks = [
            pl_track(
                "Nie mehr Fastelovend",
                "Querbeat",
                "apple_music://track/1440867473",
                library_uri="library://track/131",
                in_library=True,
            )
        ]
        out = classify_playlist_tracks(tracks, pool, min_confidence=STRICT)
        assert out["usable"] == 1

    def test_provider_uri_alone_would_match_nothing(self):
        """Why the name fallback exists: URIs of two worlds never intersect."""
        pool = [pool_song(131, title="Nie mehr Fastelovend", artist="Querbeat")]
        pool_uris = {s["uri_ma_library"] for s in pool}
        assert "apple_music://track/1440867473" not in pool_uris
        tracks = [
            pl_track(
                "Nie mehr Fastelovend - 2016 Remaster",
                "Querbeat",
                "apple_music://track/1440867473",
            )
        ]
        out = classify_playlist_tracks(tracks, pool, min_confidence=STRICT)
        assert out["usable_uris"] == ["library://track/131"]

    def test_various_artists_credit_falls_through_to_the_real_artist(self):
        pool = [pool_song(160, title="Tschingderassabum", artist="Querbeat")]
        tracks = [
            pl_track(
                "Tschingderassabum",
                "Various Artists",
                "apple_music://track/1442596610",
                artists=["Various Artists", "Querbeat"],
            )
        ]
        out = classify_playlist_tracks(tracks, pool, min_confidence=STRICT)
        assert out["usable"] == 1


class TestReasons:
    def _classify(self, min_confidence=STRICT):
        pool = [
            pool_song(1),
            pool_song(2),
            pool_song(3, conf=YearConfidence.EXTERNAL_SECONDARY),  # Deezer year
            pool_song(4, conf=YearConfidence.TAG_STUDIO),  # tag year only
            pool_song(5, title="T1", artist="A1"),  # second version of T1
        ]
        tracks = [
            pl_track("T1", "A1", "library://track/1", library_uri="library://track/1"),
            pl_track("T2", "A2", "library://track/2", library_uri="library://track/2"),
            pl_track("T3", "A3", "library://track/3", library_uri="library://track/3"),
            pl_track("T4", "A4", "library://track/4", library_uri="library://track/4"),
            pl_track("T1", "A1", "library://track/5", library_uri="library://track/5"),
            # In the library, the scan has not reached it.
            pl_track(
                "Fresh",
                "New",
                "library://track/99",
                library_uri="library://track/99",
                in_library=True,
            ),
            # MA says: not in the library at all (a streaming item).
            pl_track("Radio", "Stream", "spotify://track/x", in_library=False),
            # MA could not say (older server) — counted as not scanned.
            pl_track("Unknown", "Who", "plex://track/7", in_library=None),
        ]
        return classify_playlist_tracks(tracks, pool, min_confidence=min_confidence)

    def test_every_track_lands_in_exactly_one_bucket(self):
        out = self._classify()
        dropped = sum(len(v) for v in out["dropped"].values())
        assert out["total"] == 8
        assert out["usable"] + dropped == out["total"]

    def test_reasons(self):
        out = self._classify()
        assert out["usable"] == 2
        assert [r["title"] for r in out["dropped"]["no_year"]] == ["T3", "T4"]
        assert [r["title"] for r in out["dropped"]["duplicate"]] == ["T1"]
        assert [r["title"] for r in out["dropped"]["not_scanned"]] == [
            "Fresh",
            "Unknown",
        ]
        assert [r["title"] for r in out["dropped"]["not_in_library"]] == ["Radio"]

    def test_no_year_rows_carry_the_year_the_pool_has(self):
        out = self._classify()
        assert out["dropped"]["no_year"][0]["year"] == 1985

    def test_usable_by_gate_offers_an_honest_way_out(self):
        out = self._classify()
        assert out["usable_by_gate"] == {"strict": 2, "balanced": 3, "tags_ok": 4}

    def test_the_gate_moves_songs_between_buckets(self):
        out = self._classify(min_confidence=YEAR_GATES["tags_ok"])
        assert out["usable"] == 4
        assert out["dropped"]["no_year"] == []

    def test_empty_playlist(self):
        out = classify_playlist_tracks([], [pool_song(1)])
        assert out["total"] == 0 and out["usable"] == 0

    def test_check_payload_caps_rows_but_not_counts(self):
        rows = [{"title": f"S{i}", "artist": "X"} for i in range(450)]
        payload = playlist_check_payload(
            {
                "total": 460,
                "usable": 10,
                "usable_uris": ["library://track/1"],
                "dropped": {"not_scanned": rows, "no_year": []},
                "usable_by_gate": {"strict": 10},
            }
        )
        assert "usable_uris" not in payload
        assert payload["dropped"]["not_scanned"]["count"] == 450
        assert len(payload["dropped"]["not_scanned"]["songs"]) == 200
        assert payload["dropped"]["no_year"] == {"count": 0, "songs": []}


class TestGeneratorOnlyUris:
    def test_draws_only_from_the_playlist(self):
        pool = [pool_song(i) for i in range(100)]
        picked = {f"library://track/{i}" for i in (3, 7, 11)}
        out = gen.generate_playlist(
            pool, size=30, only_uris=picked, rng=random.Random(1)
        )
        assert {s["uri_ma_library"] for s in out["songs"]} == picked
        assert out["_eligible_count"] == 3

    def test_popularity_genres_and_recent_do_not_shrink_the_selection(self):
        pool = [pool_song(i, pctl=0.01) for i in range(10)]
        for s in pool:
            s["genres"] = ["Jazz"]
        picked = {s["uri_ma_library"] for s in pool}
        out = gen.generate_playlist(
            pool,
            size=30,
            popularity_min_percentile=0.95,  # "Top 5%" — nothing would qualify
            genres={"Rock"},
            exclude_uris=set(list(picked)[:5]),
            only_uris=picked,
            rng=random.Random(1),
        )
        assert len(out["songs"]) == 10

    def test_trust_gate_still_applies(self):
        pool = [pool_song(1), pool_song(2, conf=YearConfidence.TAG_STUDIO)]
        out = gen.generate_playlist(
            pool,
            size=30,
            only_uris={"library://track/1", "library://track/2"},
            rng=random.Random(1),
        )
        assert [s["uri_ma_library"] for s in out["songs"]] == ["library://track/1"]

    def test_size_caps_a_large_playlist(self):
        pool = [pool_song(i, year=1960 + i) for i in range(60)]
        out = gen.generate_playlist(
            pool,
            size=20,
            only_uris={s["uri_ma_library"] for s in pool},
            rng=random.Random(1),
        )
        assert len(out["songs"]) == 20


class TestSettings:
    def test_sanitize_ma_playlist(self):
        assert sanitize_ma_playlist({"item_id": 9, "provider": "library"}) == {
            "item_id": "9",
            "provider": "library",
            "name": "",
        }
        assert sanitize_ma_playlist({"item_id": "9"}) is None
        assert sanitize_ma_playlist("nope") is None

    def test_parse_source_falls_back_to_the_library_without_a_playlist(self):
        assert parse_library_source({"source": "playlist"}) == ("library", None)
        assert parse_library_source({}) == ("library", None)
        src, pl = parse_library_source(
            {
                "source": "playlist",
                "ma_playlist": {"item_id": "9", "provider": "library", "name": "X"},
            }
        )
        assert src == "playlist" and pl["item_id"] == "9"

    def test_settings_store_accepts_source_and_playlist(self):
        out = sanitize_library_settings(
            {
                "source": "playlist",
                "ma_playlist": {"item_id": "9", "provider": "library", "name": "X"},
            }
        )
        assert out["source"] == "playlist"
        assert out["ma_playlist"]["name"] == "X"

    def test_settings_store_rejects_junk_and_allows_clearing(self):
        assert "source" not in sanitize_library_settings({"source": "spotify"})
        assert "ma_playlist" not in sanitize_library_settings({"ma_playlist": {"x": 1}})
        assert sanitize_library_settings({"ma_playlist": None}) == {"ma_playlist": None}


def _track(name, artists, uri, item_id, provider):
    return SimpleNamespace(
        name=name,
        uri=uri,
        item_id=item_id,
        provider=provider,
        artists=[SimpleNamespace(name=a) for a in artists],
    )


class TestMaClient:
    def test_normalize_keeps_every_artist(self):
        t = normalize_playlist_track(
            _track(
                "Song", ["Various Artists", "Real"], "apple_music://track/1", "1", "am"
            )
        )
        assert t["artists"] == ["Various Artists", "Real"]
        assert t["artist"] == "Various Artists"

    async def test_fetch_resolves_library_twins(self):
        lib_twin = SimpleNamespace(uri="library://track/131")
        mass = MagicMock()
        mass.music.get_playlist_tracks = AsyncMock(
            return_value=[
                _track("A", ["X"], "library://track/5", "5", "library"),
                _track("B", ["Y"], "apple_music://track/1", "1", "apple_music--abc"),
                _track("C", ["Z"], "apple_music://track/2", "2", "apple_music--abc"),
                _track("D", ["W"], "apple_music://track/3", "3", "apple_music--abc"),
            ]
        )

        async def lookup(media_type, item_id, provider):
            assert media_type == "track"
            if item_id == "1":
                return lib_twin
            if item_id == "2":
                return None
            raise RuntimeError("unknown command")

        mass.music.get_library_item_by_prov_id = AsyncMock(side_effect=lookup)
        with patch(
            "custom_components.beatify.library.ma_client._get_client",
            return_value=mass,
        ):
            tracks = await async_fetch_playlist_tracks(
                MagicMock(), "entry", "9", "library"
            )

        by_title = {t["title"]: t for t in tracks}
        assert by_title["A"]["library_uri"] == "library://track/5"
        assert by_title["A"]["in_library"] is True
        assert by_title["B"]["library_uri"] == "library://track/131"
        assert by_title["C"]["in_library"] is False
        assert by_title["D"]["in_library"] is None  # lookup failed: unknown
        # Library tracks are not looked up a second time.
        assert mass.music.get_library_item_by_prov_id.await_count == 3


class TestGameStartUsesThePlaylist:
    async def _run(self, stored, check_result=None, check_exc=None):
        from custom_components.beatify.server import game_views

        hass = MagicMock()
        hass.data = {}
        generate = AsyncMock(
            return_value={"songs": [{"uri_ma_library": "library://track/1"}]}
        )
        check = AsyncMock(return_value=check_result, side_effect=check_exc)
        with (
            patch.object(
                game_views,
                "async_load_library_settings",
                AsyncMock(return_value=stored),
            ),
            patch(
                "custom_components.beatify.library.async_generate_library_playlist",
                generate,
            ),
            patch(
                "custom_components.beatify.library.playlist_source.async_check_ma_playlist",
                check,
            ),
            patch.object(
                game_views, "_recent_played_uris", return_value={"library://track/1"}
            ),
        ):
            songs, err = await game_views._generate_library_songs(hass, {})
        return songs, err, generate, check

    async def test_playlist_mode_passes_only_uris_and_no_exclusion(self):
        stored = {
            "source": "playlist",
            "ma_playlist": {"item_id": "9", "provider": "library", "name": "Grill"},
        }
        result = {"total": 3, "usable": 2, "usable_uris": ["library://track/1", "x"]}
        songs, err, generate, check = await self._run(stored, check_result=result)
        assert err is None and songs
        kwargs = generate.await_args.kwargs
        assert kwargs["only_uris"] == {"library://track/1", "x"}
        assert kwargs["exclude_uris"] is None
        assert check.await_args.kwargs["item_id"] == "9"

    async def test_library_mode_keeps_the_recent_exclusion(self):
        songs, err, generate, check = await self._run({})
        kwargs = generate.await_args.kwargs
        assert kwargs["only_uris"] is None
        assert kwargs["exclude_uris"] == {"library://track/1"}
        check.assert_not_awaited()

    async def test_unreadable_playlist_is_a_visible_error(self):
        stored = {
            "source": "playlist",
            "ma_playlist": {"item_id": "9", "provider": "library", "name": "Grill"},
        }
        songs, err, generate, _ = await self._run(
            stored, check_exc=RuntimeError("gone")
        )
        assert songs == []
        body = json.loads(err.body)
        assert body["code"] == "LIBRARY_PLAYLIST_UNAVAILABLE"
        assert body["playlist"] == "Grill"
        generate.assert_not_awaited()

    async def test_playlist_without_usable_songs_is_a_visible_error(self):
        stored = {
            "source": "playlist",
            "ma_playlist": {"item_id": "9", "provider": "library", "name": "Grill"},
        }
        result = {"total": 12, "usable": 0, "usable_uris": []}
        _, err, generate, _ = await self._run(stored, check_result=result)
        body = json.loads(err.body)
        assert body["code"] == "LIBRARY_PLAYLIST_EMPTY"
        assert body["total"] == 12
        generate.assert_not_awaited()
