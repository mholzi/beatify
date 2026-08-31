"""The `ytmusic_free` provider derives its URIs (#2426).

@ipalomo asked whether Beatify could play through
sproft/music-assistant-ytmusic, a third-party Music Assistant provider that
streams YouTube Music without a Premium account.

It can, and without a single new catalogue field. The provider keys tracks by
the YouTube video id (`_encode_track_id` returns it unchanged unless a trim
window is set), and that id already sits inside every `uri_youtube_music` the
catalogue carries. So the URI is derived in `get_song_uri` rather than stored
a second time where the copy could drift.

Deriving it there is enough for the whole stack: `filter_songs_for_provider`
calls the same function, `PlaylistManager` caches the result as
`_precomputed_uri`, and `_get_ma_uri_candidates` always tries `_resolved_uri`
first.
"""

from __future__ import annotations

import re

from custom_components.beatify.const import (
    PROVIDER_YTMUSIC_FREE,
    URI_PATTERN_MA_LIBRARY,
    URI_PATTERN_YTMUSIC_FREE,
)
from custom_components.beatify.game.playlist import (
    filter_songs_for_provider,
    get_song_uri,
)
from custom_components.beatify.server.game_views import _validate_provider


def _song(**over):
    song = {
        "title": "Test Song",
        "artist": "Test Artist",
        "year": 1990,
        "uri": "spotify:track:0000000000000000000000",
        "uri_youtube_music": "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    }
    song.update(over)
    return song


class TestTheDerivation:
    def test_builds_the_uri_from_the_youtube_link(self):
        assert (
            get_song_uri(_song(), PROVIDER_YTMUSIC_FREE)
            == "ytmusic_free://track/dQw4w9WgXcQ"
        )

    def test_no_youtube_link_means_not_playable(self):
        assert (
            get_song_uri(_song(uri_youtube_music=None), PROVIDER_YTMUSIC_FREE) is None
        )
        assert get_song_uri(_song(uri_youtube_music=""), PROVIDER_YTMUSIC_FREE) is None

    def test_a_link_without_a_video_id_is_refused(self):
        # Better no URI than a malformed one that fails at the speaker.
        assert (
            get_song_uri(
                _song(uri_youtube_music="https://music.youtube.com/playlist?list=X"),
                PROVIDER_YTMUSIC_FREE,
            )
            is None
        )

    def test_extra_query_parameters_do_not_confuse_it(self):
        song = _song(
            uri_youtube_music="https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDX"
        )
        assert (
            get_song_uri(song, PROVIDER_YTMUSIC_FREE)
            == "ytmusic_free://track/dQw4w9WgXcQ"
        )

    def test_it_does_not_disturb_the_other_providers(self):
        song = _song()
        assert get_song_uri(song, "spotify") == song["uri"]
        assert get_song_uri(song, "youtube_music") == song["uri_youtube_music"]


class TestTheUriIsAcceptedDownstream:
    def test_it_matches_its_own_pattern(self):
        uri = get_song_uri(_song(), PROVIDER_YTMUSIC_FREE)
        assert re.match(URI_PATTERN_YTMUSIC_FREE, uri)

    def test_it_also_matches_the_generic_ma_pattern(self):
        # The Crate Digger pattern was written provider-neutral, and it carries
        # this case without a change.
        uri = get_song_uri(_song(), PROVIDER_YTMUSIC_FREE)
        assert re.match(URI_PATTERN_MA_LIBRARY, uri)

    def test_the_pattern_accepts_a_multi_instance_name(self):
        # The provider declares multi_instance, so MA may name the instance
        # `ytmusic_free--<suffix>`.
        assert re.match(
            URI_PATTERN_YTMUSIC_FREE, "ytmusic_free--abc123://track/dQw4w9WgXcQ"
        )


class TestTheProviderReachesTheGame:
    def test_the_request_is_not_coerced_to_the_default(self):
        # An unlisted provider is silently coerced to Spotify, after which the
        # "no playlists" guard answers 400 with no log line. That is the bug
        # Crate Digger hit, and the reason this test exists.
        assert _validate_provider(PROVIDER_YTMUSIC_FREE) == PROVIDER_YTMUSIC_FREE

    def test_songs_without_youtube_data_are_filtered_out(self):
        songs = [_song(), _song(uri_youtube_music=None)]
        kept, _ = filter_songs_for_provider(songs, PROVIDER_YTMUSIC_FREE)
        assert len(kept) == 1
