"""A provider is wired everywhere, or this file goes red (Issue #2713).

The bug this exists to prevent: the provider list was hand-unrolled across
about fifteen files, and missing one was never an error. It was a chip that
never enabled (``supports_amazon_music`` was read by the admin and never sent,
so Amazon Music could not be picked even on an Echo), a validation that never
fired (``ma_library`` and ``ytmusic_free`` were absent from the five
copy-pasted start-game blocks, so Crate Digger on a Sonos started a game that
could not play a note), a URI that never converted. Adding ``ytmusic_free``
(#2426) took about twelve files.

``custom_components/beatify/providers.py`` is now the one list, and
:func:`wiring_gaps` is what keeps it one list. It asks each derived surface
what it knows about a provider — the capability table, the ``supports_*`` keys,
the Music Assistant URI-field map, the Alexa content types, playlist
validation, the start-game gate, the generated JavaScript mirror — and reports
every surface that has never heard of it.

Three kinds of test here:

* ``test_every_registered_provider_is_wired`` runs that over the real registry.
  A provider added to ``PROVIDERS`` is covered the moment it is declared; no
  test edit is needed, and none is possible to forget.
* ``TestTheCheckActuallyCatchesThings`` is the counter-proof. It re-runs the
  same check against a half-wired provider, and against the pre-#2713
  hand-written capability table replayed as it stood, and asserts both go red
  with the surface named. Without these, a check that never fails proves
  nothing.
* ``TestRegistryShape`` pins the internal consistency of the registry itself
  (a URI field claimed for playback must be one the provider declares, a
  platform named must be one some strategy serves), so a typo is a red test
  rather than a provider that quietly plays nowhere.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from custom_components.beatify import providers as registry
from custom_components.beatify.providers import (
    PROVIDERS,
    Provider,
    UriField,
    supports_keys,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_JS = REPO_ROOT / "custom_components/beatify/www/js/providers.generated.js"


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


def _a_song_with_everything(provider: Provider) -> dict[str, Any]:
    """A song carrying a plausible value in every field this provider names.

    Used to ask "can this provider ever resolve a URI at all?" without
    hard-coding what a URI looks like per provider.
    """
    song: dict[str, Any] = {
        "title": "Test Song",
        "artist": "Test Artist",
        "year": 1999,
        "id": "song-1",
        # ytmusic_free derives its URI from the YouTube Music field.
        "uri_youtube_music": "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    }
    for uri_field in provider.catalogue_uris:
        song.setdefault(uri_field.name, f"{uri_field.name}-value")
    for name in provider.playback_uri_fields:
        song.setdefault(name, f"{name}-value")
    return song


def wiring_gaps(provider: Provider) -> list[str]:
    """Every derived surface that has never heard of ``provider``.

    Empty list means the provider is reachable end to end: a host can pick it,
    the server accepts it, a playlist can be validated for it, a URI resolves,
    and the speaker is asked to play it in a form the platform understands.
    """
    # Imported here rather than at module scope so a monkeypatched module
    # attribute is picked up on each call — that is what the counter-proofs
    # below rely on.
    from custom_components.beatify.game import playlist as playlist_mod
    from custom_components.beatify.server import game_views
    from custom_components.beatify.services import media_player as mp
    from custom_components.beatify.services.playback import music_assistant as ma

    gaps: list[str] = []
    pid = provider.id

    # 1. A URI, or a documented reason there is none.
    if not provider.playback_uri_fields and pid not in playlist_mod._SPECIAL_RESOLVERS:
        gaps.append(
            f"{pid}: no playback_uri_fields and no entry in "
            "game/playlist.py::_SPECIAL_RESOLVERS — get_song_uri can only "
            "ever return None, so every song is skipped as unplayable"
        )
    elif playlist_mod.get_song_uri(_a_song_with_everything(provider), pid) is None:
        gaps.append(
            f"{pid}: get_song_uri returns None for a song that carries every "
            "field this provider declares"
        )

    # 2. The Music Assistant strategy's URI-field map. A missing key (as
    #    opposed to an empty tuple) makes it log "unknown provider" and refuse
    #    to walk anything.
    if pid not in ma._PROVIDER_URI_FIELDS:
        gaps.append(
            f"{pid}: missing from services/playback/music_assistant.py::"
            "_PROVIDER_URI_FIELDS — MA logs 'unknown provider' and plays nothing"
        )

    # 3. A column in every platform's capability row, so the wizard can grey
    #    the chip out for a speaker that cannot serve it.
    for platform, row in mp.PLATFORM_CAPABILITIES.items():
        if not row.get("supported"):
            continue
        if pid not in row:
            gaps.append(
                f"{pid}: no column in PLATFORM_CAPABILITIES[{platform!r}] — "
                "the admin cannot tell whether this speaker serves it"
            )

    # 4. A supports_* key in the /beatify/api/media-players payload. This is
    #    the one that bit amazon_music: consumed by the admin, never sent.
    for platform in mp.PLATFORM_CAPABILITIES:
        if not mp.PLATFORM_CAPABILITIES[platform].get("supported"):
            continue
        if provider.supports_key not in supports_keys(platform):
            gaps.append(
                f"{pid}: the media-player payload for {platform!r} carries no "
                f"{provider.supports_key!r} — the chip can never enable"
            )

    # 5. Alexa asks for a catalog by name. A provider an Echo can be asked for
    #    needs to say which one, or it is silently played as Apple Music.
    if (
        registry.PLATFORM_ALEXA in provider.platforms
        and not provider.alexa_content_type
    ):
        gaps.append(
            f"{pid}: playable on {registry.PLATFORM_ALEXA} but declares no "
            "alexa_content_type — AlexaStrategy falls back to APPLE_MUSIC"
        )

    # 6. The start-game view must accept the identifier rather than coerce it
    #    to the default provider.
    if game_views._validate_provider(pid) != pid:
        gaps.append(
            f"{pid}: coerced away by server/game_views.py::_validate_provider — "
            "the selection silently becomes the default"
        )

    # 7. Every catalogue field the provider claims must be validated when a
    #    playlist is read, or a malformed URI passes and fails at the speaker.
    validated = {name for name, _pattern, _example in playlist_mod._URI_FIELDS}
    for uri_field in provider.catalogue_uris:
        if uri_field.name not in validated:
            gaps.append(
                f"{pid}: catalogue field {uri_field.name!r} is not in "
                "game/playlist.py::_URI_FIELDS — playlist validation never "
                "checks its shape"
            )

    # 8. A counted provider must actually get a count out of discovery.
    if (
        provider.counted
        and provider.count_key not in playlist_mod.count_songs_per_provider([])
    ):
        gaps.append(
            f"{pid}: counted, but count_songs_per_provider emits no "
            f"{provider.count_key!r} — the admin shows no coverage for it"
        )

    # 9. The browser has to know about it too. The generated mirror is what
    #    the wizard chips, the capability badge and the playlist coverage rows
    #    read, and it is committed, so it can go stale.
    mirror = GENERATED_JS.read_text(encoding="utf-8")
    if f'"id": "{pid}"' not in mirror:
        gaps.append(
            f"{pid}: absent from www/js/providers.generated.js — run "
            "`python3 tools/gen_providers_js.py`; until then the wizard offers "
            "no chip for it"
        )

    return gaps


# ---------------------------------------------------------------------------
# The completeness test
# ---------------------------------------------------------------------------


def test_every_registered_provider_is_wired():
    """Every provider in the registry reaches every surface that consumes it."""
    gaps = [gap for provider in PROVIDERS for gap in wiring_gaps(provider)]
    assert not gaps, "Provider(s) not wired end to end:\n  " + "\n  ".join(gaps)


def test_the_generated_javascript_mirror_is_current():
    """www/js/providers.generated.js must match the Python registry.

    The same guard `npm run build:check` gives the minified bundles: the file
    is committed, so it can drift, and a stale mirror means a provider exists
    in the integration and not in the admin.
    """
    gen = importlib.import_module("tools.gen_providers_js")
    assert GENERATED_JS.read_text(encoding="utf-8") == gen.render(PROVIDERS), (
        "www/js/providers.generated.js is out of date — run "
        "`python3 tools/gen_providers_js.py` and `npm run build`."
    )


# ---------------------------------------------------------------------------
# The counter-proofs — a check that cannot fail proves nothing
# ---------------------------------------------------------------------------


#: A provider added to the registry and nowhere else: no URI fields, no special
#: resolver, no Alexa content type although it claims an Echo can play it.
HALF_WIRED = Provider(
    id="napster",
    label="Napster",
    platforms=frozenset({registry.PLATFORM_SONOS, registry.PLATFORM_ALEXA}),
    catalogue_uris=(
        UriField("uri_napster", r"^napster://track/\d+$", "napster://track/{id}"),
    ),
    counted=True,
)


class TestTheCheckActuallyCatchesThings:
    """The counter-proofs. Each breaks one surface and expects a named gap."""

    def test_a_half_wired_provider_is_caught(self, monkeypatch):
        """A provider declared in the registry and wired nowhere else."""
        extended = (*PROVIDERS, HALF_WIRED)
        monkeypatch.setattr(registry, "PROVIDERS", extended)
        monkeypatch.setattr(registry, "PROVIDERS_BY_ID", {p.id: p for p in extended})

        gaps = wiring_gaps(HALF_WIRED)
        joined = "\n".join(gaps)

        # It cannot play: no URI fields, no resolver.
        assert "no playback_uri_fields" in joined, joined
        # The Music Assistant strategy has never heard of it.
        assert "_PROVIDER_URI_FIELDS" in joined, joined
        # The capability table has no column, so no chip can be greyed out.
        assert "no column in PLATFORM_CAPABILITIES" in joined, joined
        # It says an Echo can play it but not which catalog to search.
        assert "alexa_content_type" in joined, joined
        # Playlist validation would never check its URI shape.
        assert "uri_napster" in joined, joined
        # It is counted but discovery emits no count.
        assert "napster_count" in joined, joined
        # And the browser has never heard of it.
        assert "providers.generated.js" in joined, joined

    def test_the_real_registry_stays_green_beside_it(self, monkeypatch):
        """Adding the broken provider must not make the real ones look broken."""
        extended = (*PROVIDERS, HALF_WIRED)
        monkeypatch.setattr(registry, "PROVIDERS", extended)
        monkeypatch.setattr(registry, "PROVIDERS_BY_ID", {p.id: p for p in extended})
        for provider in PROVIDERS:
            assert not wiring_gaps(provider), provider.id

    def test_the_pre_2713_capability_table_goes_red(self, monkeypatch):
        """Replay the hand-written table this PR deleted; ytmusic_free is missing.

        This is not a hypothetical: the literal below is exactly what
        `PLATFORM_CAPABILITIES` held on `origin/main` before this change, and
        `ytmusic_free` had been a selectable provider since #2426 without ever
        appearing in it.
        """
        from custom_components.beatify.services import media_player as mp

        monkeypatch.setattr(
            mp,
            "PLATFORM_CAPABILITIES",
            {
                "music_assistant": {
                    "supported": True,
                    "ma_library": True,
                    "spotify": True,
                    "apple_music": True,
                    "youtube_music": True,
                    "tidal": True,
                    "deezer": True,
                    "amazon_music": False,
                    "method": "uri",
                    "warning": "Premium account must be configured in Music Assistant",
                },
                "sonos": {
                    "supported": True,
                    "spotify": True,
                    "apple_music": False,
                    "youtube_music": False,
                    "tidal": False,
                    "amazon_music": False,
                    "method": "uri",
                    "warning": "Spotify must be linked in Sonos app",
                },
                "alexa_media": {
                    "supported": True,
                    "spotify": True,
                    "apple_music": True,
                    "youtube_music": False,
                    "tidal": False,
                    "amazon_music": True,
                    "method": "text_search",
                    "warning": "Service must be linked in Alexa app",
                    "caveat": "Uses voice search - may occasionally play different version",
                },
                "cast": {
                    "supported": False,
                    "reason": "Cast devices require Music Assistant",
                },
            },
        )

        ytmusic_free = registry.PROVIDERS_BY_ID["ytmusic_free"]
        gaps = "\n".join(wiring_gaps(ytmusic_free))
        assert "no column in PLATFORM_CAPABILITIES" in gaps, gaps

        # ...and so is Crate Digger, on the two platforms the old table simply
        # left the column out of.
        gaps = "\n".join(wiring_gaps(registry.PROVIDERS_BY_ID["ma_library"]))
        assert "'sonos'" in gaps and "'alexa_media'" in gaps, gaps

    def test_a_dropped_uri_field_map_entry_goes_red(self, monkeypatch):
        """The historic shape: a provider left out of one hand-kept dict."""
        from custom_components.beatify.services.playback import music_assistant as ma

        monkeypatch.setattr(
            ma,
            "_PROVIDER_URI_FIELDS",
            {k: v for k, v in ma._PROVIDER_URI_FIELDS.items() if k != "deezer"},
        )
        gaps = "\n".join(wiring_gaps(registry.PROVIDERS_BY_ID["deezer"]))
        assert "_PROVIDER_URI_FIELDS" in gaps, gaps

    def test_a_stale_javascript_mirror_goes_red(self, monkeypatch):
        """A provider added in Python but not regenerated for the browser."""
        gen = importlib.import_module("tools.gen_providers_js")
        assert GENERATED_JS.read_text(encoding="utf-8") != gen.render(
            (*PROVIDERS, HALF_WIRED)
        )


# ---------------------------------------------------------------------------
# The registry's own consistency
# ---------------------------------------------------------------------------


class TestRegistryShape:
    """A typo in the registry must be a red test, not a provider that plays nowhere."""

    def test_ids_are_unique(self):
        ids = [p.id for p in PROVIDERS]
        assert len(ids) == len(set(ids)), ids

    def test_const_provider_identifiers_and_the_registry_agree(self):
        """`const.PROVIDER_*` is the other place an identifier is spelled out.

        They are the names the rest of the codebase imports, so a constant
        without a registry entry is a provider half the code believes in, and a
        registry entry without a constant is one the older call sites cannot
        name.
        """
        from custom_components.beatify import const

        constants = {
            value
            for name, value in vars(const).items()
            if name.startswith("PROVIDER_")
            and name != "PROVIDER_DEFAULT"
            and isinstance(value, str)
        }
        assert constants == set(registry.PROVIDER_IDS), (
            "const.PROVIDER_* and providers.PROVIDERS disagree: "
            f"only in const: {sorted(constants - set(registry.PROVIDER_IDS))}, "
            f"only in the registry: {sorted(set(registry.PROVIDER_IDS) - constants)}"
        )
        assert const.PROVIDER_DEFAULT in registry.PROVIDERS_BY_ID

    def test_every_provider_names_at_least_one_platform(self):
        orphans = [p.id for p in PROVIDERS if not p.platforms]
        assert not orphans, f"provider(s) no speaker can play: {orphans}"

    def test_platforms_named_are_platforms_that_exist(self):
        """A provider cannot be carried by a platform no strategy implements."""
        from custom_components.beatify.services.playback import supported_platforms

        known = {registry.normalise_platform(p) for p in supported_platforms()}
        for provider in PROVIDERS:
            unknown = provider.platforms - known
            assert not unknown, (
                f"{provider.id} names platform(s) no PlaybackStrategy serves: "
                f"{sorted(unknown)}"
            )

    def test_playback_fields_are_declared_catalogue_fields(self):
        """You cannot play from a field the provider never says it has."""
        for provider in PROVIDERS:
            declared = {u.name for u in provider.catalogue_uris}
            stray = set(provider.playback_uri_fields) - declared
            assert not stray, f"{provider.id}: {sorted(stray)} not in catalogue_uris"

    def test_a_uri_field_belongs_to_exactly_one_provider(self):
        """Two providers claiming one field would make validation ambiguous."""
        owner: dict[str, str] = {}
        for provider in PROVIDERS:
            for uri_field in provider.catalogue_uris:
                assert uri_field.name not in owner, (
                    f"{uri_field.name!r} claimed by both {owner[uri_field.name]} "
                    f"and {provider.id}"
                )
                owner[uri_field.name] = provider.id

    def test_a_provider_with_no_catalogue_uris_is_not_a_catalogue_count(self):
        """Amazon Music counts every song; nothing else may claim to."""
        for provider in PROVIDERS:
            if provider.counts_every_song:
                assert not provider.catalogue_uris, provider.id

    @pytest.mark.parametrize(
        ("platform", "expected"),
        [
            ("music_assistant", True),
            ("sonos", False),
            ("alexa_media", False),
            ("alexa", False),
            ("cast", False),
        ],
    )
    def test_plays_on_folds_the_alexa_alias(self, platform, expected):
        assert registry.PROVIDERS_BY_ID["tidal"].plays_on(platform) is expected
