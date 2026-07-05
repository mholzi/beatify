# Beatify Architecture

A self-hosted multiplayer music trivia game that runs as a Home Assistant integration. This document is the top-down map of the system. For the why-was-this-decision-made nuance, follow the inline issue references (#NNN) into the GitHub history — every non-trivial path was driven by a specific user-reported bug or feature request.

> Last refreshed: 2026-07-05 against `main` at `b90f947` (the v4.2.0-rc9 line).

---

## 1. System overview

```
   Guests' phones                    Host's tablet/phone
   (player.html)                     (admin.html)
        │                                  │
        │  WebSocket  /beatify/api/ws      │
        └───────────────┬──────────────────┘
                        │
                ┌───────▼────────┐
                │ Beatify back-  │   game/state.py (~916 LOC orchestrator) +
                │ end (HA inte-  │   game/state_*.py (14 mixins)
                │ gration)       │   server/ws_handlers/ (package, ~40 message types)
                └───────┬────────┘   services/{media_player,tts,lights,stats}
                        │
                ┌───────▼────────┐
                │ Music Assistant│   external HA add-on
                │  (MA)          │   talks to Spotify / Apple Music / YT Music /
                └───────┬────────┘   Tidal / Deezer
                        │
                ┌───────▼────────┐
                │ Smart speakers │   Sonos / HomePod / Alexa / generic MA target
                └────────────────┘

   Alexa path (no MA): Amazon Music + Spotify + Apple Music play through the
   Alexa Media Player integration by text search (artist + title), bypassing
   Music Assistant entirely — see §4.

   Out-of-band:                            ┌────────────────────────┐
   "Request playlist" form ──────► CF Worker (beatify-api.mholzi    │
                                   .workers.dev) ──► GitHub Issue   │
                                   ───► manual enrichment ─────────►│
                                   ──► `playlists/community/*.json`│
                                   ──► next HACS release ──────────►│
                                                                    └─
```

## 2. Repo layout

```
custom_components/beatify/
├── __init__.py             # Home Assistant integration entry
├── manifest.json           # version + dependencies + HA constraints (HA 2025.1+)
├── config_flow.py          # First-run wizard config
├── const.py                # Constants (6 provider IDs incl. amazon_music, defaults, timeouts)
├── analytics.py            # Local error/event tracking (HA storage)
├── sensor.py               # HA sensor entities (live game state)
├── binary_sensor.py        # HA binary sensor entities
├── device.py               # HA device registration
├── game/
│   ├── state.py            # Core game-state orchestrator (~916 LOC)
│   ├── state_*.py          # 14 mixins the orchestrator composes (#1560 decomposition):
│   │                       #   state_lifecycle / state_round_delegation / state_media /
│   │                       #   state_scoring / state_reveal_transition / state_auto_advance /
│   │                       #   state_challenge / state_vote_window (Crowd Court) /
│   │                       #   state_player / state_leaderboard / state_pause /
│   │                       #   state_setup / state_tts / state_serialization
│   ├── round_manager.py    # Per-round lifecycle (intro → playing → reveal → next)
│   ├── scoring.py          # Per-player scoring per round
│   ├── text_match.py       # Title & Artist fuzzy/near-miss matching (#1180)
│   ├── challenges.py       # Artist Challenge / Movie Quiz
│   ├── powerups.py         # Steal power-up
│   ├── playlist.py         # Playlist loading + filtering + provider URI resolution
│   ├── player.py           # PlayerSession (score/streak/elimination state)
│   ├── player_registry.py  # Player roster + reconnect reclaim
│   ├── highlights.py       # End-of-game highlights reel (#75)
│   ├── share.py            # End-game share card
│   ├── tts_phrases.py      # Localised TTS phrase templates
│   └── serializers.py, types.py, protocols.py, config.py, service.py
├── server/
│   ├── __init__.py         # async_register_static_paths → /beatify/static/
│   ├── views.py            # HTTP views registry
│   ├── websocket.py        # WS endpoint plumbing
│   ├── ws_handlers/        # WS message handlers, split into a package (#1588):
│   │   ├── __init__.py     #   registration + dispatch (~40 message types)
│   │   ├── _helpers.py     #   shared helpers
│   │   ├── admin.py        #   admin/host actions
│   │   ├── guessing.py     #   submit_guess / vote / challenge answers
│   │   └── lifecycle.py    #   join / start / pause / resume / end
│   ├── game_views.py       # start-game + game HTTP endpoints
│   ├── playlist_views.py   # playlist + playlist-request endpoints, SavePlaylistView
│   ├── mix_views.py        # Smart Playlist Mixer endpoint (#1538) — see §6
│   ├── companion_auth.py   # HA Companion app login handoff (#1527 era)
│   ├── stats_views.py      # analytics dashboard data
│   ├── setup_state.py      # persisted wizard/setup state
│   ├── serializers.py, base.py
├── services/               # backend side-effect services (see §4, §10)
│   ├── media_player.py     # provider URI dispatch + playback (#768/#805/#808)
│   ├── tts.py              # TTS announcements (tts.speak; #793)
│   ├── lights.py           # party-lights phase orchestration
│   └── stats.py            # analytics/stats side-effects
├── playlists/              # 49 bundled playlists, 5,381 songs
│   ├── *.json              # 17 default packs (era / greatest-hits / movie)
│   ├── community/          # 32 community packs (genre / region), separate browse tab
│   ├── user/               # host-saved mixes land here as <slug>.json (Community tab)
│   └── mix/                # transient Mixer output (internal, auto-cleaned)
├── translations/           # HA-internal (config flow, services)
└── www/                    # Frontend assets
    ├── admin.html          # Host UI (the "control panel")
    ├── player.html         # Guest UI (lobby + gameplay + reveal)
    ├── dashboard.html      # TV / big-screen spectator view
    ├── sw.js               # PWA service worker (CACHE_VERSION pattern)
    ├── i18n/               # 5 locales: en/de/es/fr/nl
    ├── js/
    │   ├── admin/          # admin UI modules (constants.js holds TAG_CATEGORIES)
    │   ├── admin.js        # admin entry + WS hub
    │   ├── player-*.js     # player core / lobby / game / reveal / end / tour
    │   ├── dashboard.js    # TV renderers (Spotlight/Podium/Broadcast lower-third)
    │   ├── playlist-hub.js # 3-tab playlist browser
    │   ├── playlist-generator.js  # Mix tab UI
    │   ├── title-artist-bonuses.js, party-lights.js, tts-settings.js, i18n.js, ...
    └── css/
        └── styles.min.css

tests/                      # ~55 pytest files (unit + integration)
custom_components/beatify/www/js/__tests__/
└── *.test.js               # ~45+ Vitest JS unit suites

scripts/
├── playlist_schema.json    # authoritative playlist JSON schema (CI-validated)
├── validate_playlists.py   # schema gate
└── fix_broken_tracks.py    # periodic URI-health automation
```

## 3. Game state machine

`game/state.py` is a thin orchestrator (~916 LOC, down from the 2075-LOC monolith) that composes **14 `state_*.py` mixins** (#1560). Each mixin owns one concern; the orchestrator wires them together and holds the shared game object.

**Core subsystems (now mixin-owned):**
1. **Lifecycle / phase** (`state_lifecycle`) — IDLE / LOBBY / PLAYING / REVEAL / PAUSED, gated transitions.
2. **Round flow** (`state_round_delegation`, `state_reveal_transition`, `state_auto_advance`) — initialize → confirm intro → play → end (timer or all-submitted) → reveal → next.
3. **Media** (`state_media`) — playback orchestration against `MediaPlayerService`.
4. **Scoring** (`state_scoring`, `state_leaderboard`) — per-player per-round, isolated try/except so one player's exception can't freeze the round (#816); closest-wins support.
5. **Challenges & Crowd Court** (`state_challenge`, `state_vote_window`) — Artist Challenge, Movie Quiz, and the Title & Artist close-call vote window (#1180/#1243).
6. **Roster** (`state_player`) — admin (host) + 0..N guests, reclaim-by-name on reconnect (#790).
7. **Pause/resume** (`state_pause`), **setup** (`state_setup`), **TTS** (`state_tts`), **serialization** (`state_serialization`).
8. **Sudden Death** (`state.py` `_apply_sudden_death_elimination`, #827/#1472) — an opt-in elimination mode: after each round's scoring (from **round 2** onward), the surviving player with the **lowest round score** is eliminated for the rest of the game; a tie for last is broken by submission speed (slowest — or a non-submitter — is out). Never eliminates the last survivor (the game ends with a `last_one_standing` 💀 highlight instead). Requires a **3-player minimum**: the wizard disables the toggle below 3, and the LOBBY→PLAYING transition (`server/game_views.py`) auto-disables it as a server-side backstop. Can be armed at game start or toggled live from the reveal screen (`set_sudden_death`).

**Round-flow defensive coding:** every `asyncio.create_task` in the round flow carries an `add_done_callback` that surfaces unretrieved exceptions with a stack trace (fixed the #816 class of silent freezes).

## 4. Provider URI dispatch (the #768 / #805 / #808 story, plus Amazon Music)

`services/media_player.py` holds the provider dispatch that took three issues to settle:

```python
_PROVIDER_URI_FIELDS: dict[str, tuple[str, ...]] = {
    "spotify":       ("uri_spotify", "uri"),
    "apple_music":   ("uri_apple_music",),
    "youtube_music": ("uri_youtube_music",),
    "tidal":         ("uri_tidal",),
    "deezer":        ("uri_deezer",),
    "amazon_music":  (),   # no URI — plays via Alexa text search
}
```

`_get_ma_uri_candidates(song)` walks ONLY the user-selected provider's fields. The original design (#768) walked all six providers in order and fell through on failure — wrong on Apple-Music-only setups, where each round paid 4×15s of timeouts before reaching the working URI, then force-paused after 3 failures. #805 narrowed the cascade (@Levtos's stress-testing surfaced it).

**#808 storefront dimension:** Apple Music URIs are per-country. A US-storefront ID isn't in the DE catalog, so MA accepts the URI but can't resolve a stream. Fix: a per-region URI map (`uri_apple_music_by_region`), a runtime resolver keyed on `hass.config.country`, and region-locked songs filtered at playlist load.

**#777 strict-detection invariant:** if `media_title` doesn't change after `play_media`, the track never started — fail and try the next URI.

**Amazon Music (v4.1.0):** the sixth provider is **Alexa-only and URI-less** — it maps to `()` above. Playback goes through `_play_via_alexa(song)` with `content_type="AMAZON_MUSIC"`, asking Alexa to search by `artist` + `title` (`_get_alexa_search_text`). Speaker capability tables mark `amazon_music: True` only for the `alexa_media` platform (`method: "text_search"`); Music Assistant and Sonos map it to `False`. Trade-off: no exact-recording guarantee — Alexa may pick a live/remaster/cover when titles collide.

## 5. WebSocket protocol

`server/ws_handlers/` (a **package** since #1588 — previously a single 1300-LOC file) registers ~40 message types across `admin.py`, `guessing.py`, `lifecycle.py`, with `__init__.py` handling registration/dispatch and `_helpers.py` shared logic. Categories:

- **Auth** — `admin_join`, `player_join`, `reconnect` (name-based admin reclaim)
- **Game lifecycle** — `start_game`, `end_game`, `pause_game`, `resume_game`
- **Round** — `next_round`, `submit_guess`, `confirm_intro`
- **Challenges / vote** — artist/movie answers, Crowd Court 👍/👎 votes
- **State sync** — `state_update` (full serialised state broadcast), `phase_change`
- **Player management** — `kick_player`, `rename_player`
- **Playlist requests** — `submit_request`, `poll_requests`

Failure modes: WS dropped during reveal → `reconnect` with same name restores admin role regardless of phase (#790). HA restart → the client retries with a 20s budget (#814) and shows an inline "Connecting…" state.

## 6. Smart Playlist Mixer (#1538)

`server/mix_views.py` powers the **Mix** tab. The host picks tags across four categories — `decade` / `style` / `region` / `special` (the same `TAG_CATEGORIES` that drive the filter bar, `www/js/admin/constants.js`) — and a target size (**30 / 50 / 100**). The view unions all songs from tag-matching playlists, de-duplicates, caps to the target, and returns a path.

- **Transient by default:** the assembled set is written to `playlists/mix/__mix__-<uuid>.json` (unique stem per run, #1547) and treated as `bundled` by discovery, so it never pollutes the Community tab. Stale transient files are best-effort cleaned on each write.
- **No new game-start path:** the mix path feeds the *existing* `/beatify/api/start-game` flow, reusing all validated provider/platform/dedup logic.
- **Save as community:** ticking "save as community playlist" persists the set to `playlists/user/<slug>.json` (same place as `SavePlaylistView`), so `async_discover_playlists` surfaces it in the Community tab on refresh.

## 7. Playlist format & validation

Playlists are JSON in `custom_components/beatify/playlists/` (and user `config/beatify/playlists/`), validated in CI by `scripts/validate_playlists.py` against `scripts/playlist_schema.json`.

- **Playlist-level required:** `name`, `version`, `tags`, `songs`.
- **Per-song required:** `artist`, `title` (both mandatory — #697; songs missing either are **silently skipped at load**), `year`, `uri` (a `spotify:track:` URI or `null`), and the fun-fact set (`fun_fact` + `fun_fact_de/es/fr/nl`).
- **Optional:** additional provider URIs (`uri_apple_music`, `uri_youtube_music`, `uri_tidal`, `uri_deezer`, `uri_apple_music_by_region`), `alt_artists`, `isrc`, `chart_info`, `certifications`, `awards` (+ localized), and movie-quiz fields (`movie`, `movie_choices`, playlist-level `movie_quiz_enabled`).

## 8. Playlist request flow

End-to-end from the host's "+ Add custom playlist" tap: `playlist-requests.js` POSTs the Spotify URL to a Cloudflare Worker (`beatify-api.mholzi.workers.dev`, Dashboard-deployed, not in this repo), which decrypts the URL, calls the Spotify Web API, and opens a labelled GitHub issue. A maintainer enriches the tracks (years, alt-artists, fun facts, multi-provider URIs) into `playlists/community/<slug>.json`, and the pack ships in the next HACS release. The Worker's structured `error.code` is surfaced in the UI (#835) so failures are legible instead of opaque.

## 9. Frontend asset serving + cache-busting (#824)

`server/__init__.py` registers `/beatify/static/` → `<integration>/www/`. Every HTML page declares `<meta name="beatify-version">`; `i18n.js` reads it and appends `?v=X.Y.Z` to JSON fetches. Each release bumps that meta tag in admin/player/dashboard alongside `manifest.json` and `sw.js` `CACHE_VERSION`. Without it, a service-worker-cached `en.json` from an older rc would mismatch the new bundle and leak raw i18n keys on screen. `make build` runs esbuild to regenerate the `.min.js` bundles.

## 10. TTS announcements

`services/tts.py` calls `tts.speak` with both `entity_id` AND `media_player_entity_id` (pre-#793 only the former was passed, which silently failed on modern engines). Per-game-event toggles live in `tts-settings.js` with Minimal / Standard / Full verbosity presets; each event maps to a localised phrase (`game/tts_phrases.py`) in the active language.

## 11. Test strategy

- **`tests/`** — ~55 pytest files (unit + integration): state mixins, scoring, playlist filtering, provider URI dispatch, WS handlers end-to-end via mocked HA.
- **`www/js/__tests__/`** — ~45+ Vitest JS unit suites (player tour, wizard, game logic).
- **Burn-in CI** — flaky-test detection reruns the suite weekly.
- **HACS validation** — `validate.yml` runs `hacs/action` + `hassfest` on every push; the playlist schema gate runs `validate_playlists.py`.

## 12. Build + ship

```bash
# Local dev
PATH=/opt/homebrew/bin:$PATH make build       # regenerates *.min.js bundles
npm test                                       # Vitest JS suite
python3 -m pytest -q                           # pytest suite

# Release
# 1. Bump manifest.json version + sw.js CACHE_VERSION + <meta beatify-version> ×3
# 2. CHANGELOG.md entry under [<version>]
# 3. make build (regenerate .min.js)
# 4. git commit + push + tag
# 5. gh release create --prerelease (rc) or stable
```

HACS subscribers see new versions automatically (pre-release subscribers see rcs separately from stable).

## 13. Operational footprint

- **Telemetry:** zero external. `analytics.py` records error events to local HA storage; the dashboard surfaces them. No HTTP calls leave the instance unless the host submits a playlist request.
- **Persistence:** game history → `GameRecord` entries in HA storage; survives restarts; fuels the "most-played" / "recently played" shelves.
- **State machine:** in-memory only. A HA restart mid-game ends the game (admin can rejoin; recovery banner offers Resume from PAUSED).

## 14. Known dragons

The wiki at `~/Development/Claude/beatifybot/wiki/` (private to the maintainer, BeatifyBot's knowledge base) holds the long-form synthesis on recurring URI-bug patterns, playback state-sync fragility (FE↔MA↔Speaker), and external feedback that pre-empted GitHub issues (Reddit + Discussions surfaced the provider-mismatch bugs months before #768/#808). If you hit a confusing failure mode, search closed issues by symptom — almost every weird playback case has a documented post-mortem.
