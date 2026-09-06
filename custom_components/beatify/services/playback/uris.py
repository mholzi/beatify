"""URI shapes Music Assistant understands, and how to recognise them back.

Split out of :mod:`custom_components.beatify.services.media_player` for #2636.
Module-level functions rather than methods: neither depends on a speaker, a
provider or any service state, and both are needed on two sides — the Music
Assistant strategy when it plays, and the service shell when it waits for
metadata to catch up (#1380).
"""

from __future__ import annotations


def convert_uri_for_ma(uri: str) -> str:
    """
    Convert Beatify-internal URIs to formats Music Assistant understands.

    Beatify playlists store URIs in internal formats:
    - applemusic://track/<id>  → apple_music://track/<id>  (MA native, #772)
    - deezer://track/<id>      → unchanged (MA native, #797)
    - tidal://track/<id>       → https://tidal.com/browse/track/<id>
    - spotify:track:<id>       → unchanged (MA native format)
    - https://music.youtube.com/... → unchanged (already a URL)

    Args:
        uri: Beatify-internal URI string

    Returns:
        URI converted to a format Music Assistant can resolve

    """
    if not uri:
        return uri

    if uri.startswith("deezer://track/"):
        # MA's Deezer provider has domain "deezer". The previous
        # https://www.deezer.com/track/<id> form was being routed to the
        # "builtin" provider via MA's generic http(s):// branch — and
        # builtin doesn't know Deezer, so playback failed with
        # "No playable items found". Pass through the native form. (#797)
        return uri

    if uri.startswith("applemusic://track/"):
        # MA's Apple Music provider has domain "apple_music". Use MA's native
        # provider-URI form; the short "music.apple.com/song/<id>" URL fails
        # MA's parser (needs storefront+slug, 6+ path parts). (#772)
        track_id = uri.removeprefix("applemusic://track/")
        return f"apple_music://track/{track_id}"

    if uri.startswith("tidal://track/"):
        track_id = uri.removeprefix("tidal://track/")
        return f"https://tidal.com/browse/track/{track_id}"

    if uri.startswith("https://music.youtube.com/watch?v="):
        track_id = uri.removeprefix("https://music.youtube.com/watch?v=")
        return f"ytmusic://track/{track_id}"

    # spotify:track:<id> and https:// URLs are passed through unchanged
    return uri


def uri_match_tokens(uri: str) -> list[str]:
    """Tokens to look for in MA's media_content_id to confirm playback.

    Issue #1380: the raw Beatify-internal URI is not what MA reports in
    media_content_id — MA echoes the convert_uri_for_ma form. To reliably
    detect that the requested track started, match against BOTH the
    MA-converted URI and the bare track ID (last path/ID segment), which is
    identical across the internal and the MA-converted form for every
    provider (Spotify, Apple Music, Tidal, YT Music, Deezer).

    Args:
        uri: The Beatify-internal URI that was requested.

    Returns:
        Ordered, deduped, non-empty substring tokens.

    """
    tokens: list[str] = []

    def _add(token: str | None) -> None:
        if token and token not in tokens:
            tokens.append(token)

    # The form MA actually reports.
    _add(convert_uri_for_ma(uri))
    # The raw form too, in case a provider echoes the internal URI verbatim.
    _add(uri)

    # Bare track ID — stable across both forms.
    if uri.startswith("spotify:"):
        _add(uri.split(":")[-1])
    elif "watch?v=" in uri:
        # https://music.youtube.com/watch?v=<id>[&extra]
        _add(uri.split("watch?v=", 1)[-1].split("&", 1)[0])
    elif "://" in uri:
        # applemusic://track/<id>, tidal://track/<id>, deezer://track/<id>,
        # and plain https URLs — the bare ID is the last "/"-segment.
        tail = uri.rstrip("/").rsplit("/", 1)[-1]
        _add(tail.split("?", 1)[0])

    return tokens
