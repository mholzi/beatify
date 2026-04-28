"""Tests for storefront-aware Apple Music URI resolution (#808 follow-up).

Beatify's playlists carry per-region Apple Music track IDs in
``uri_apple_music_by_region``. The resolver in ``playlist.py:get_song_uri``
picks the right one based on the user's storefront, and PlaylistManager
filters out songs explicitly unavailable in the user's region so the
runtime never even tries to play them.
"""

from __future__ import annotations

from custom_components.beatify.const import (
    PROVIDER_APPLE_MUSIC,
    PROVIDER_SPOTIFY,
)
from custom_components.beatify.game.playlist import (
    PlaylistManager,
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
