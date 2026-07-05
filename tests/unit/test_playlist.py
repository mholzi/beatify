"""Tests for storefront-aware Apple Music URI resolution (#808 follow-up).

Beatify's playlists carry per-region Apple Music track IDs in
``uri_apple_music_by_region``. The resolver in ``playlist.py:get_song_uri``
picks the right one based on the user's storefront, and PlaylistManager
filters out songs explicitly unavailable in the user's region so the
runtime never even tries to play them.
"""

from __future__ import annotations

from custom_components.beatify.const import (
    PROVIDER_AMAZON_MUSIC,
    PROVIDER_APPLE_MUSIC,
    PROVIDER_SPOTIFY,
)
from custom_components.beatify.game.playlist import (
    PlaylistManager,
    filter_songs_for_provider,
    get_song_uri,
)


# ---------------------------------------------------------------------------
# get_song_uri — storefront resolution
# ---------------------------------------------------------------------------


class TestGetSongUriStorefrontAware:
    def test_no_storefront_falls_back_to_legacy_uri(self):
        """Default behavior (storefront=None): use the legacy single URI field."""
        song = {
            "uri_apple_music": "applemusic://track/302229811",
            "uri_apple_music_by_region": {
                "de": None,
                "us": "applemusic://track/302229811",
            },
        }
        assert (
            get_song_uri(song, PROVIDER_APPLE_MUSIC) == "applemusic://track/302229811"
        )

    def test_storefront_picks_regional_uri(self):
        """When storefront is set, the per-region URI wins over legacy."""
        song = {
            "uri_apple_music": "applemusic://track/100",  # legacy/US
            "uri_apple_music_by_region": {
                "us": "applemusic://track/100",
                "gb": "applemusic://track/200",  # different ID for UK
            },
        }
        assert (
            get_song_uri(song, PROVIDER_APPLE_MUSIC, storefront="gb")
            == "applemusic://track/200"
        )

    def test_storefront_unavailable_returns_none_explicitly(self):
        """If region is explicitly None in the per-region map, return None.
        This is the storefront-mismatch case (#808): track is confirmed
        unavailable in the user's region. Returning None lets PlaylistManager
        skip the song without ever trying MA.
        """
        song = {
            "uri_apple_music": "applemusic://track/302229811",  # US-only
            "uri_apple_music_by_region": {
                "us": "applemusic://track/302229811",
                "de": None,  # confirmed unavailable in DE
            },
        }
        assert get_song_uri(song, PROVIDER_APPLE_MUSIC, storefront="de") is None

    def test_storefront_not_in_map_falls_back_to_legacy(self):
        """If the user's storefront isn't in the per-region map at all,
        fall back to the legacy field. Important for backwards-compat with
        playlists that haven't been regenerated yet.
        """
        song = {
            "uri_apple_music": "applemusic://track/302229811",
            "uri_apple_music_by_region": {
                "us": "applemusic://track/302229811",
                "de": None,
            },
        }
        # User in JP — not yet covered by the regen script
        assert (
            get_song_uri(song, PROVIDER_APPLE_MUSIC, storefront="jp")
            == "applemusic://track/302229811"
        )

    def test_storefront_ignored_for_non_apple_providers(self):
        """The storefront param only affects Apple Music; Spotify ignores it."""
        song = {
            "uri_spotify": "spotify:track:abc123",
            "uri_apple_music_by_region": {"de": None},
        }
        assert (
            get_song_uri(song, PROVIDER_SPOTIFY, storefront="de")
            == "spotify:track:abc123"
        )

    def test_no_per_region_data_uses_legacy(self):
        """Songs that haven't been regenerated yet (no by_region map) still
        resolve via the legacy single URI."""
        song = {"uri_apple_music": "applemusic://track/12345"}
        assert (
            get_song_uri(song, PROVIDER_APPLE_MUSIC, storefront="de")
            == "applemusic://track/12345"
        )


# ---------------------------------------------------------------------------
# PlaylistManager — storefront-aware filtering
# ---------------------------------------------------------------------------


def _song(*, title: str, by_region: dict[str, str | None] | None = None) -> dict:
    """Build a minimal song dict for tests."""
    s = {
        "title": title,
        "artist": "Test Artist",
        "year": 1990,
        "uri_apple_music": "applemusic://track/legacy",
    }
    if by_region is not None:
        s["uri_apple_music_by_region"] = by_region
    return s


class TestPlaylistManagerStorefrontFiltering:
    def test_songs_unavailable_in_storefront_are_filtered_out(self):
        """#808: PlaylistManager removes songs explicitly unavailable in the
        user's storefront from the playable pool entirely. They never
        appear in get_next_song output → MA is never asked to play them.
        """
        songs = [
            _song(
                title="Available everywhere",
                by_region={"us": "applemusic://track/1", "de": "applemusic://track/1"},
            ),
            _song(
                title="US-only (DE unavailable)",
                by_region={"us": "applemusic://track/2", "de": None},
            ),
            _song(
                title="DE-only (US unavailable)",
                by_region={"us": None, "de": "applemusic://track/3"},
            ),
        ]
        # DE user: only songs 1 and 3 should be playable
        pm = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC, storefront="de")
        assert pm.has_playable_songs()

        playable_titles: set[str] = set()
        for _ in range(20):  # sample a bunch of times to be sure
            picked = pm.get_next_song()
            if picked is None:
                break
            playable_titles.add(picked["title"])
            pm.mark_played(picked["_resolved_uri"])

        assert "Available everywhere" in playable_titles
        assert "DE-only (US unavailable)" in playable_titles
        assert "US-only (DE unavailable)" not in playable_titles

    def test_resolved_uri_uses_storefront(self):
        """get_next_song's _resolved_uri must be the per-region URI."""
        songs = [
            _song(
                title="Different IDs per region",
                by_region={
                    "us": "applemusic://track/usid",
                    "gb": "applemusic://track/gbid",
                },
            ),
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC, storefront="gb")
        picked = pm.get_next_song()
        assert picked is not None
        assert picked["_resolved_uri"] == "applemusic://track/gbid"

    def test_no_storefront_uses_legacy_uri(self):
        """Backwards-compat: PlaylistManager without storefront uses the
        legacy single URI, ignoring per-region data."""
        songs = [
            _song(
                title="Available US, unavailable DE",
                by_region={"us": "applemusic://track/legacy", "de": None},
            ),
        ]
        # No storefront → legacy URI used → song IS playable.
        pm = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC)
        picked = pm.get_next_song()
        assert picked is not None
        assert picked["_resolved_uri"] == "applemusic://track/legacy"

    def test_song_with_no_per_region_data_still_playable(self):
        """Songs without ``uri_apple_music_by_region`` (not yet regenerated)
        fall back to legacy URI even when a storefront is set."""
        songs = [
            _song(title="Not regenerated yet"),  # no by_region key
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC, storefront="de")
        picked = pm.get_next_song()
        assert picked is not None
        assert picked["_resolved_uri"] == "applemusic://track/legacy"

    def test_storefront_only_song_without_legacy_uri_survives_prefilter(self):
        """#1402 B3: a song that has NO legacy ``uri_apple_music`` field but is
        available via ``uri_apple_music_by_region`` for the user's storefront
        must NOT be dropped by the pre-filter. The storefront-blind pre-filter
        used to call get_song_uri without the storefront, get None (no legacy
        field), and silently drop the song before the storefront-aware bucket
        loop ever saw it.
        """
        song = {
            "title": "DE storefront-exclusive",
            "artist": "Test Artist",
            "year": 1990,
            # No legacy uri_apple_music field at all — only per-region data.
            "uri_apple_music_by_region": {"de": "applemusic://track/de-only"},
        }
        pm = PlaylistManager([song], provider=PROVIDER_APPLE_MUSIC, storefront="de")
        assert pm.has_playable_songs()
        picked = pm.get_next_song()
        assert picked is not None
        assert picked["_resolved_uri"] == "applemusic://track/de-only"


class TestFilterSongsForProviderStorefront:
    """#1402 B3: filter_songs_for_provider must thread the storefront through to
    get_song_uri so it isn't storefront-blind."""

    def test_storefront_only_song_kept(self):
        songs = [
            {
                "title": "DE-only",
                "artist": "A",
                "year": 1990,
                "uri_apple_music_by_region": {"de": "applemusic://track/de"},
            },
        ]
        filtered, skipped = filter_songs_for_provider(
            songs, PROVIDER_APPLE_MUSIC, storefront="de"
        )
        assert len(filtered) == 1
        assert skipped == 0

    def test_song_unavailable_in_storefront_is_skipped(self):
        songs = [
            {
                "title": "Not in DE",
                "artist": "A",
                "year": 1990,
                "uri_apple_music_by_region": {"de": None},
            },
        ]
        filtered, skipped = filter_songs_for_provider(
            songs, PROVIDER_APPLE_MUSIC, storefront="de"
        )
        assert filtered == []
        assert skipped == 1

    def test_default_no_storefront_still_works(self):
        songs = [
            {
                "title": "Legacy",
                "artist": "A",
                "year": 1990,
                "uri_apple_music": "applemusic://track/legacy",
            },
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_APPLE_MUSIC)
        assert len(filtered) == 1
        assert skipped == 0


# ---------------------------------------------------------------------------
# Amazon Music — per-song identity (regression for #1361)
# ---------------------------------------------------------------------------
#
# Amazon Music plays via Alexa text-search, so there is no real per-track URI.
# Previously ``get_song_uri`` returned the constant ``"amazon_music"`` for every
# song. Because PlaylistManager uses that value both as the dedup key (in
# ``__init__``) AND as the played-tracking key (``mark_played``), the whole
# playlist collapsed to a single playable track and every Alexa game ended after
# round 1. These tests pin the per-song identity behavior so that never
# regresses.


def _amazon_song(artist: str, title: str, year: int = 1990) -> dict:
    """Minimal Amazon-Music-style song (no URI fields — Alexa text-search)."""
    return {"artist": artist, "title": title, "year": year}


class TestGetSongUriAmazonMusic:
    def test_distinct_songs_get_distinct_keys(self):
        a = get_song_uri(_amazon_song("ABBA", "Waterloo"), PROVIDER_AMAZON_MUSIC)
        b = get_song_uri(
            _amazon_song("Queen", "Bohemian Rhapsody"), PROVIDER_AMAZON_MUSIC
        )
        assert a != b
        assert a is not None and b is not None

    def test_key_is_stable_for_same_song(self):
        song = _amazon_song("ABBA", "Waterloo")
        assert get_song_uri(song, PROVIDER_AMAZON_MUSIC) == get_song_uri(
            song, PROVIDER_AMAZON_MUSIC
        )

    def test_key_is_case_insensitive(self):
        assert get_song_uri(
            _amazon_song("ABBA", "Waterloo"), PROVIDER_AMAZON_MUSIC
        ) == get_song_uri(_amazon_song("abba", "waterloo"), PROVIDER_AMAZON_MUSIC)

    def test_falls_back_to_id_when_no_metadata(self):
        key = get_song_uri({"id": 42}, PROVIDER_AMAZON_MUSIC)
        assert key == "amazon:id:42"


class TestPlaylistManagerAmazonMusic:
    def test_full_playlist_survives_dedup(self):
        """#1361: all 10 distinct songs survive — not collapsed to one."""
        songs = [_amazon_song(f"Artist {i}", f"Title {i}") for i in range(10)]
        pm = PlaylistManager(songs, provider=PROVIDER_AMAZON_MUSIC)
        assert pm.get_total_count() == 10

    def test_ten_successive_rounds_play_all_songs(self):
        """#1361: a 10-song Amazon game must run 10 rounds, not end after 1.

        Mirrors the runtime loop: get_next_song() then
        mark_played(_resolved_uri). With the old constant URI, mark_played
        poisoned the whole pool after round 1 and get_next_song returned None.
        """
        songs = [_amazon_song(f"Artist {i}", f"Title {i}") for i in range(10)]
        pm = PlaylistManager(songs, provider=PROVIDER_AMAZON_MUSIC)

        played: list[str] = []
        for _ in range(10):
            song = pm.get_next_song()
            assert song is not None, "game ended early — pool collapsed"
            played.append(song["_resolved_uri"])
            pm.mark_played(song["_resolved_uri"])

        # All 10 rounds played distinct songs, and the pool is now exhausted.
        assert len(set(played)) == 10
        assert pm.get_next_song() is None
        assert pm.get_remaining_count() == 0

    def test_true_duplicate_songs_are_deduped(self):
        """Identical artist+title genuinely collapse (intended dedup)."""
        songs = [
            _amazon_song("ABBA", "Waterloo"),
            _amazon_song("ABBA", "Waterloo"),
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_AMAZON_MUSIC)
        assert pm.get_total_count() == 1


class TestPrecomputedUriEquivalence:
    """#1710: the URI cached in __init__ equals the on-the-fly get_song_uri
    result, and the full play-through behaviour is unchanged."""

    def test_precomputed_uri_matches_on_the_fly_spotify(self):
        songs = [
            {"uri_spotify": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa", "title": "A"},
            {"uri": "spotify:track:bbbbbbbbbbbbbbbbbbbbbb", "title": "B"},
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_SPOTIFY)
        for song in pm._songs:
            assert song["_precomputed_uri"] == get_song_uri(
                song, PROVIDER_SPOTIFY, None
            )

    def test_precomputed_uri_matches_on_the_fly_apple_storefront(self):
        songs = [
            {
                "uri_apple_music": "applemusic://track/legacy",
                "uri_apple_music_by_region": {"gb": "applemusic://track/gbid"},
                "title": "A",
            },
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC, storefront="gb")
        song = pm._songs[0]
        assert (
            song["_precomputed_uri"]
            == get_song_uri(song, PROVIDER_APPLE_MUSIC, "gb")
            == "applemusic://track/gbid"
        )

    def test_resolved_uri_equals_precomputed(self):
        songs = [
            {"uri_spotify": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa", "title": "A"},
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_SPOTIFY)
        picked = pm.get_next_song()
        assert picked is not None
        assert picked["_resolved_uri"] == "spotify:track:aaaaaaaaaaaaaaaaaaaaaa"

    def test_multi_playlist_play_through_unchanged(self):
        songs = [
            {
                "uri_spotify": "spotify:track:aaaaaaaaaaaaaaaaaaaaaa",
                "title": "A",
                "_playlist_source": "p1",
            },
            {
                "uri_spotify": "spotify:track:bbbbbbbbbbbbbbbbbbbbbb",
                "title": "B",
                "_playlist_source": "p2",
            },
        ]
        pm = PlaylistManager(songs, provider=PROVIDER_SPOTIFY)
        assert pm._multi_playlist is True
        played: list[str] = []
        for _ in range(2):
            song = pm.get_next_song()
            assert song is not None
            played.append(song["_resolved_uri"])
            pm.mark_played(song["_resolved_uri"])
        assert set(played) == {
            "spotify:track:aaaaaaaaaaaaaaaaaaaaaa",
            "spotify:track:bbbbbbbbbbbbbbbbbbbbbb",
        }
        assert pm.get_next_song() is None
