"""URI shapes Music Assistant understands, and how to recognise them back.

Split out of :mod:`custom_components.beatify.services.media_player` for #2636.
Module-level functions rather than methods: neither depends on a speaker, a
provider or any service state, and both are needed on two sides — the Music
Assistant strategy when it plays, and the service shell when it waits for
metadata to catch up (#1380).
"""

from __future__ import annotations

from ...providers import ma_uri_rules

#: (internal prefix, Music Assistant template) per provider, from the registry
#: (#2713). Each provider states its own rewrite next to its URI patterns, so
#: adding one cannot leave a URI that never converts — the failure this used to
#: invite, since a missing branch here returns the internal URI unchanged and MA
#: answers "No playable items found" with nothing pointing back at this file.
_MA_URI_RULES = ma_uri_rules()


def convert_uri_for_ma(uri: str) -> str:
    """
    Convert Beatify-internal URIs to formats Music Assistant understands.

    Beatify playlists store URIs in internal formats:
    - applemusic://track/<id>  → apple_music://track/<id>  (MA native, #772)
    - deezer://track/<id>      → unchanged (MA native, #797)
    - tidal://track/<id>       → https://tidal.com/browse/track/<id>
    - spotify:track:<id>       → unchanged (MA native format)
    - https://music.youtube.com/watch?v=<id> → ytmusic://track/<id>

    Args:
        uri: Beatify-internal URI string

    Returns:
        URI converted to a format Music Assistant can resolve

    """
    if not uri:
        return uri

    for prefix, template in _MA_URI_RULES:
        if uri.startswith(prefix):
            return template.format(track_id=uri.removeprefix(prefix))

    # Providers MA already understands (spotify:track:<id>, deezer://track/<id>,
    # library://track/<id>) and any other https:// URL pass through unchanged.
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
