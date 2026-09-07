/**
 * GENERATED FILE — do not edit by hand (#2713).
 *
 * Mirror of `custom_components/beatify/providers.py`. Regenerate with:
 *
 *     python3 tools/gen_providers_js.py
 *
 * `tests/unit/test_provider_registry_2713.py` fails if this file has drifted
 * from the Python registry, so a provider added on one side cannot reach a
 * release without the other.
 *
 * Field meanings live on the `Provider` dataclass in providers.py; the short
 * version:
 *   platforms      speaker platforms that can serve this provider
 *   supportsKey    key in a /beatify/api/media-players entry
 *   countKey       key in a playlist entry, or null when it is not counted
 *   countFallback  a missing count means "every song" (legacy playlists)
 *   catalogueCoverage  the count measures stored URIs, not "every song"
 */

export const PROVIDERS = [
    {
        "id": "spotify",
        "label": "Spotify",
        "shortLabel": "Spotify",
        "platforms": [
            "alexa_media",
            "music_assistant",
            "sonos"
        ],
        "supportsKey": "supports_spotify",
        "countKey": "spotify_count",
        "countFallback": true,
        "catalogueCoverage": true,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": "admin.pauseRecovery.providerSpotify"
    },
    {
        "id": "apple_music",
        "label": "Apple Music",
        "shortLabel": "Apple",
        "platforms": [
            "alexa_media",
            "music_assistant"
        ],
        "supportsKey": "supports_apple_music",
        "countKey": "apple_music_count",
        "countFallback": false,
        "catalogueCoverage": true,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": "admin.pauseRecovery.providerAppleMusic"
    },
    {
        "id": "youtube_music",
        "label": "YouTube Music",
        "shortLabel": "YouTube",
        "platforms": [
            "music_assistant"
        ],
        "supportsKey": "supports_youtube_music",
        "countKey": "youtube_music_count",
        "countFallback": false,
        "catalogueCoverage": true,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": "admin.pauseRecovery.providerYouTubeMusic"
    },
    {
        "id": "tidal",
        "label": "Tidal",
        "shortLabel": "Tidal",
        "platforms": [
            "music_assistant"
        ],
        "supportsKey": "supports_tidal",
        "countKey": "tidal_count",
        "countFallback": false,
        "catalogueCoverage": true,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": "admin.pauseRecovery.providerTidal"
    },
    {
        "id": "deezer",
        "label": "Deezer",
        "shortLabel": "Deezer",
        "platforms": [
            "music_assistant"
        ],
        "supportsKey": "supports_deezer",
        "countKey": "deezer_count",
        "countFallback": false,
        "catalogueCoverage": true,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": "admin.pauseRecovery.providerDeezer"
    },
    {
        "id": "amazon_music",
        "label": "Amazon Music",
        "shortLabel": "Amazon",
        "platforms": [
            "alexa_media"
        ],
        "supportsKey": "supports_amazon_music",
        "countKey": "amazon_music_count",
        "countFallback": true,
        "catalogueCoverage": false,
        "sub": null,
        "subKey": null,
        "pauseRecoveryKey": null
    },
    {
        "id": "ma_library",
        "label": "Crate Digger",
        "shortLabel": "Library",
        "platforms": [
            "music_assistant"
        ],
        "supportsKey": "supports_ma_library",
        "countKey": null,
        "countFallback": false,
        "catalogueCoverage": false,
        "sub": "Your personal Music Assistant library",
        "subKey": "wizard.providerLibrarySub",
        "pauseRecoveryKey": null
    },
    {
        "id": "ytmusic_free",
        "label": "YouTube Music (Free)",
        "shortLabel": "YT Free",
        "platforms": [
            "music_assistant"
        ],
        "supportsKey": "supports_ytmusic_free",
        "countKey": null,
        "countFallback": false,
        "catalogueCoverage": false,
        "sub": "Needs the ytmusic_free provider in Music Assistant",
        "subKey": "wizard.providerYtmusicFreeSub",
        "pauseRecoveryKey": null
    }
];

export const PROVIDER_IDS = PROVIDERS.map((p) => p.id);

export const PROVIDERS_BY_ID = Object.fromEntries(PROVIDERS.map((p) => [p.id, p]));

/** Providers a speaker on this platform can serve. */
export function providersForPlatform(platform) {
    const canonical = platform === "alexa" ? "alexa_media" : platform;
    return PROVIDERS.filter((p) => p.platforms.includes(canonical));
}
