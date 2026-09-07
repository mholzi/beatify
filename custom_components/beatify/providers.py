"""Every music provider Beatify knows, described once (#2713).

Before this module the provider list was hand-unrolled across about fifteen
places: a column per provider in ``PLATFORM_CAPABILITIES``, a ``supports_*``
key next to it, five copy-pasted validation blocks in ``server/game_views.py``,
an ``if provider ==`` chain in ``game/playlist.py``, ``_PROVIDER_URI_FIELDS``
in the Music Assistant strategy, a content-type chain in the Alexa strategy,
six ``*_count`` fields in playlist discovery, and the same list again in half a
dozen JavaScript modules.

Adding ``ytmusic_free`` (#2426) touched about twelve files, and missing one was
never an error — it was a chip that never enabled, a validation that never
fired, a URI that never converted. Three such holes were still open when this
module was written; the commit that introduced it names them.

Everything above now derives from :data:`PROVIDERS`. Adding a provider is one
entry here, ``python3 tools/gen_providers_js.py`` to refresh the JavaScript
mirror and ``npm run build`` to reminify; the
completeness test in ``tests/unit/test_provider_registry_2713.py`` fails if any
of the derived surfaces is left behind.

This module deliberately imports nothing from the rest of the integration
(only ``const`` for the URI patterns), so every layer — playback, HTTP views,
playlist discovery, the JS generator — can read it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    URI_PATTERN_APPLE_MUSIC,
    URI_PATTERN_DEEZER,
    URI_PATTERN_MA_LIBRARY,
    URI_PATTERN_SPOTIFY,
    URI_PATTERN_TIDAL,
    URI_PATTERN_YOUTUBE_MUSIC,
)

# Platform identifiers, as the entity registry spells them. ``alexa`` is an
# alias the capability lookup folds into ``alexa_media``; keep both out of the
# provider tables and let :func:`normalise_platform` do it.
PLATFORM_MUSIC_ASSISTANT = "music_assistant"
PLATFORM_SONOS = "sonos"
PLATFORM_ALEXA = "alexa_media"

#: ``alexa`` and ``alexa_media`` are the same speaker seen through two versions
#: of the integration.
_PLATFORM_ALIASES = {"alexa": PLATFORM_ALEXA}


def normalise_platform(platform: str) -> str:
    """Fold platform aliases onto their canonical identifier."""
    return _PLATFORM_ALIASES.get(platform, platform)


@dataclass(frozen=True)
class UriField:
    """One playlist field that can hold a track URI, and its shape.

    ``example`` is the human wording playlist validation puts in front of an
    author whose URI does not match ``pattern``.
    """

    name: str
    pattern: str
    example: str


@dataclass(frozen=True)
class Provider:
    """One music provider, and everything the rest of the integration asks of it."""

    #: Wire identifier. Used in the game options, the HTTP API, the ``supports_*``
    #: keys and the ``data-provider`` attribute of the admin chips.
    id: str

    #: English display name. Shown in the wizard chip and in HTTP error details.
    label: str

    #: Platform identifiers whose speakers can play this provider. This is the
    #: one answer to "can this speaker serve this service?" — the capability
    #: table, the ``supports_*`` keys, the wizard's dimmed chips and the
    #: start-game rejection all read it.
    platforms: frozenset[str]

    #: Playlist fields that can carry this provider's URI, in the order
    #: playlist validation reports problems with them. Empty when the provider
    #: has no catalogue URI at all (Alexa text search, a derived URI).
    catalogue_uris: tuple[UriField, ...] = ()

    #: The same field names in the order Music Assistant should try them.
    #: Differs from ``catalogue_uris`` only for Spotify, where the explicit
    #: ``uri_spotify`` outranks the legacy ``uri`` for playback but is
    #: validated after it. Empty when playback does not read a stored field.
    playback_uri_fields: tuple[str, ...] = ()

    #: True when playlist discovery reports a ``<id>_count`` for this provider.
    counted: bool = False

    #: True when that count is "every song in the playlist" rather than "every
    #: song carrying a matching URI" — Alexa text search plays anything.
    counts_every_song: bool = False

    #: True when the admin's per-provider playlist count falls back to the raw
    #: song count for a playlist that carries no count (legacy playlists).
    count_falls_back_to_song_count: bool = False

    #: The prefix a Beatify-internal URI of this provider starts with, and the
    #: shape Music Assistant wants instead. ``ma_uri_template`` is a format
    #: string taking ``track_id``; None means MA already understands the
    #: internal form and it is passed through untouched.
    ma_uri_prefix: str | None = None
    ma_uri_template: str | None = None

    #: ``media_content_type`` an Echo is asked for. None when this provider
    #: never reaches :class:`~.services.playback.alexa.AlexaStrategy`.
    alexa_content_type: str | None = None

    #: Music Assistant may retry by artist+title when the URI is missing or
    #: fails to resolve.
    name_fallback: bool = False

    #: What to tell a host whose speaker cannot serve this provider. Appended
    #: to "<label> is not supported on this speaker."
    unsupported_hint: str = "Use Music Assistant."

    #: Short name for the playlist hub's per-provider coverage rows.
    short_label: str = ""

    #: Second line under the wizard chip, and its i18n key. Only for providers
    #: whose name alone does not say what they play.
    sub: str | None = None
    sub_key: str | None = None

    #: i18n key for the pause-recovery banner's provider name. None where no
    #: translation exists yet — the banner then omits the name, as it always
    #: has. A new provider does not have to add one; it just will not be named
    #: in that one banner until it does.
    pause_recovery_key: str | None = None

    #: Free-form notes carried into the generated JS mirror's header.
    notes: str = ""

    @property
    def supports_key(self) -> str:
        """The ``supports_*`` key the media-player payload carries."""
        return f"supports_{self.id}"

    @property
    def count_key(self) -> str:
        """The ``<id>_count`` key playlist discovery carries."""
        return f"{self.id}_count"

    def plays_on(self, platform: str) -> bool:
        """Can a speaker on ``platform`` serve this provider?"""
        return normalise_platform(platform) in self.platforms


#: Every provider, in the order the wizard lists them. Order is the only thing
#: this tuple decides that a set could not; everything else keys off ``id``.
PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="spotify",
        label="Spotify",
        short_label="Spotify",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT, PLATFORM_SONOS, PLATFORM_ALEXA}),
        catalogue_uris=(
            # `uri` is the legacy field; both hold a Spotify track URI.
            UriField("uri", URI_PATTERN_SPOTIFY, "spotify:track:{22-char-id}"),
            UriField("uri_spotify", URI_PATTERN_SPOTIFY, "spotify:track:{22-char-id}"),
        ),
        # Playback prefers the explicit field and falls back to the legacy one.
        playback_uri_fields=("uri_spotify", "uri"),
        counted=True,
        count_falls_back_to_song_count=True,
        alexa_content_type="SPOTIFY",
        unsupported_hint="Use Music Assistant.",
        pause_recovery_key="admin.pauseRecovery.providerSpotify",
    ),
    Provider(
        id="apple_music",
        label="Apple Music",
        short_label="Apple",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT, PLATFORM_ALEXA}),
        catalogue_uris=(
            UriField(
                "uri_apple_music", URI_PATTERN_APPLE_MUSIC, "applemusic://track/id"
            ),
        ),
        playback_uri_fields=("uri_apple_music",),
        counted=True,
        # MA's Apple Music provider has domain "apple_music". Use MA's native
        # provider-URI form; the short "music.apple.com/song/<id>" URL fails
        # MA's parser (needs storefront+slug, 6+ path parts). (#772)
        ma_uri_prefix="applemusic://track/",
        ma_uri_template="apple_music://track/{track_id}",
        alexa_content_type="APPLE_MUSIC",
        unsupported_hint="Use Music Assistant.",
        pause_recovery_key="admin.pauseRecovery.providerAppleMusic",
        notes=(
            "Storefront-aware: uri_apple_music_by_region overrides the legacy "
            "single-storefront field when the host's storefront is known (#808)."
        ),
    ),
    Provider(
        id="youtube_music",
        label="YouTube Music",
        short_label="YouTube",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT}),
        catalogue_uris=(
            UriField(
                "uri_youtube_music",
                URI_PATTERN_YOUTUBE_MUSIC,
                "https://music.youtube.com/watch?v=...",
            ),
        ),
        playback_uri_fields=("uri_youtube_music",),
        counted=True,
        ma_uri_prefix="https://music.youtube.com/watch?v=",
        ma_uri_template="ytmusic://track/{track_id}",
        unsupported_hint="Use Music Assistant.",
        pause_recovery_key="admin.pauseRecovery.providerYouTubeMusic",
    ),
    Provider(
        id="tidal",
        label="Tidal",
        short_label="Tidal",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT}),
        catalogue_uris=(
            UriField("uri_tidal", URI_PATTERN_TIDAL, "tidal://track/{id}"),
        ),
        playback_uri_fields=("uri_tidal",),
        counted=True,
        ma_uri_prefix="tidal://track/",
        ma_uri_template="https://tidal.com/browse/track/{track_id}",
        name_fallback=True,
        unsupported_hint="Use Music Assistant.",
        pause_recovery_key="admin.pauseRecovery.providerTidal",
        notes=(
            "name_fallback: Tidal URIs can no longer be refreshed — Odesli's "
            "public API, their only source, was retired on 2026-07-31."
        ),
    ),
    Provider(
        id="deezer",
        label="Deezer",
        short_label="Deezer",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT}),
        catalogue_uris=(
            UriField("uri_deezer", URI_PATTERN_DEEZER, "deezer://track/{id}"),
        ),
        playback_uri_fields=("uri_deezer",),
        counted=True,
        # No ma_uri_* rule: MA's Deezer provider has domain "deezer" and takes
        # the internal form as-is. The earlier https://www.deezer.com/track/<id>
        # form was routed to MA's "builtin" provider via its generic http(s)
        # branch, and builtin does not know Deezer — playback failed with "No
        # playable items found" (#797).
        unsupported_hint="Use Music Assistant.",
        pause_recovery_key="admin.pauseRecovery.providerDeezer",
    ),
    Provider(
        id="amazon_music",
        label="Amazon Music",
        short_label="Amazon",
        platforms=frozenset({PLATFORM_ALEXA}),
        # No URI: the Echo is asked, in words, for "<title> by <artist>", so
        # every song in a playlist is playable.
        counted=True,
        counts_every_song=True,
        count_falls_back_to_song_count=True,
        alexa_content_type="AMAZON_MUSIC",
        unsupported_hint="Use an Amazon Echo (alexa_media).",
    ),
    Provider(
        id="ma_library",
        label="Crate Digger",
        short_label="Library",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT}),
        catalogue_uris=(
            # Permissive by design — the provider prefix varies per MA
            # instance (library://track/123, plex--<id>://track/<key>, …).
            UriField("uri_ma_library", URI_PATTERN_MA_LIBRARY, "library://track/{id}"),
        ),
        playback_uri_fields=("uri_ma_library",),
        # Not counted: Crate Digger playlists are assembled from the host's own
        # library at game start, so a per-playlist coverage number would be
        # about a catalogue the host does not play from.
        name_fallback=True,
        unsupported_hint="Use Music Assistant.",
        sub="Your personal Music Assistant library",
        sub_key="wizard.providerLibrarySub",
    ),
    Provider(
        id="ytmusic_free",
        label="YouTube Music (Free)",
        short_label="YT Free",
        platforms=frozenset({PLATFORM_MUSIC_ASSISTANT}),
        # #2426: the URI is DERIVED from uri_youtube_music rather than stored,
        # because the ytmusic_free track id IS the YouTube video id. An empty
        # playback_uri_fields is deliberate, not an omission.
        name_fallback=True,
        unsupported_hint="Use Music Assistant.",
        sub="Needs the ytmusic_free provider in Music Assistant",
        sub_key="wizard.providerYtmusicFreeSub",
        notes=(
            "Third-party MA provider (sproft/music-assistant-ytmusic), not part "
            "of Music Assistant itself. Selectable on any MA speaker whether or "
            "not the provider is actually installed."
        ),
    ),
)

#: Providers by wire identifier.
PROVIDERS_BY_ID: dict[str, Provider] = {p.id: p for p in PROVIDERS}

#: Wire identifiers, in wizard order.
PROVIDER_IDS: tuple[str, ...] = tuple(p.id for p in PROVIDERS)


def get_provider(provider_id: str) -> Provider | None:
    """The provider with this identifier, or None when it is unknown."""
    return PROVIDERS_BY_ID.get(provider_id)


def providers_for_platform(platform: str) -> tuple[Provider, ...]:
    """Every provider a speaker on ``platform`` can serve, in wizard order."""
    canonical = normalise_platform(platform)
    return tuple(p for p in PROVIDERS if canonical in p.platforms)


def platform_provider_flags(platform: str) -> dict[str, bool]:
    """``{provider_id: can this platform serve it}`` for EVERY provider.

    Total by construction: a provider added to :data:`PROVIDERS` gets a column
    for every platform on the same commit, so the capability table can never
    fall a provider behind again.
    """
    canonical = normalise_platform(platform)
    return {p.id: canonical in p.platforms for p in PROVIDERS}


def supports_keys(platform: str) -> dict[str, bool]:
    """``{"supports_<id>": bool}`` for the media-player payload the admin reads."""
    canonical = normalise_platform(platform)
    return {p.supports_key: canonical in p.platforms for p in PROVIDERS}


def catalogue_uri_fields() -> tuple[UriField, ...]:
    """Every catalogue URI field across all providers, in validation order.

    Deduped by field name — the legacy ``uri`` belongs to Spotify and appears
    once, where Spotify puts it.
    """
    seen: set[str] = set()
    out: list[UriField] = []
    for provider in PROVIDERS:
        for uri_field in provider.catalogue_uris:
            if uri_field.name in seen:
                continue
            seen.add(uri_field.name)
            out.append(uri_field)
    return tuple(out)


def name_fallback_providers() -> frozenset[str]:
    """Providers Music Assistant may resolve from artist+title instead of a URI."""
    return frozenset(p.id for p in PROVIDERS if p.name_fallback)


def alexa_content_types() -> dict[str, str]:
    """``{provider_id: media_content_type}`` for the providers an Echo can search."""
    return {
        p.id: p.alexa_content_type
        for p in PROVIDERS
        if p.alexa_content_type is not None
    }


def ma_uri_rules() -> tuple[tuple[str, str], ...]:
    """``(internal prefix, Music Assistant template)`` for every provider that
    needs its URI rewritten before Music Assistant will resolve it.

    Providers MA already understands (Spotify, Deezer, the MA library itself)
    declare no rule and are passed through unchanged. The prefixes are mutually
    exclusive, so the order of the rules does not matter.
    """
    return tuple(
        (p.ma_uri_prefix, p.ma_uri_template)
        for p in PROVIDERS
        if p.ma_uri_prefix and p.ma_uri_template
    )


def provider_uri_fields() -> dict[str, tuple[str, ...]]:
    """``{provider_id: URI fields to try}``, in Music Assistant's preference order."""
    return {p.id: p.playback_uri_fields for p in PROVIDERS}


__all__ = [
    "PLATFORM_ALEXA",
    "PLATFORM_MUSIC_ASSISTANT",
    "PLATFORM_SONOS",
    "PROVIDERS",
    "PROVIDERS_BY_ID",
    "PROVIDER_IDS",
    "Provider",
    "UriField",
    "alexa_content_types",
    "catalogue_uri_fields",
    "get_provider",
    "ma_uri_rules",
    "name_fallback_providers",
    "normalise_platform",
    "platform_provider_flags",
    "provider_uri_fields",
    "providers_for_platform",
    "supports_keys",
]
