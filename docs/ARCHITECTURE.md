# Beatify Architecture

A self-hosted multiplayer music trivia game that runs as a Home Assistant integration. This document is the top-down map of the system. For the why-was-this-decision-made nuance, follow the inline issue references (#NNN) into the GitHub history — every non-trivial path was driven by a specific user-reported bug or feature request.

> Last refreshed: 2026-05-04 against `main` at `26585cf4` (in the v3.3.3-rc1 line).

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
                │ Beatify back-  │   game/state.py (2075 LOC, 5 owned subsystems)
                │ end (HA inte-  │   server/ws_handlers.py (1309 LOC, ~40 message types)
                │ gration)       │   services/{media_player,tts,playlist}.py
                └───────┬────────┘
                        │
                ┌───────▼────────┐
                │ Music Assistant│   external HA add-on
                │  (MA)          │   talks to Spotify / Apple Music / YT Music /
                └───────┬────────┘   Tidal / Deezer
                        │
                ┌───────▼────────┐
                │ Smart speakers │   Sonos / HomePod / Alexa / generic MA target
                └────────────────┘

   Out-of-band:                            ┌────────────────────────┐
   "Request playlist" form ──────► CF Worker (beatify-api.mholzi    │
                                   .workers.dev) ──► GitHub Issue   │
                                   ───► manual enrichment ─────────►│
                                   ──► `playlists/community/*.json`│
                                   ──► next HACS release ──────────►│
                                                                    │
   Spec & full failure-mode walkthrough: docs/ — but the most       │
   common failure (worker GitHub_TOKEN expiry) is the reason        │
   playlist-requests.js + admin.js surface structured `error.code`  │
   to the UI as of v3.3.3 (#835 follow-up).                         │
                                                                    └─
```

## 2. Repo layout

```
custom_components/beatify/
├── __init__.py             # Home Assistant integration entry
├── manifest.json           # version + dependencies + HA constraints
├── config_flow.py          # First-run wizard config
├── const.py                # Constants (provider IDs, defaults, timeouts)
├── game/
│   ├── state.py            # The core game state machine (5 phases, 2075 LOC)
│   ├── playlist.py         # Playlist loading + filtering + provider URI resolution
│   ├── round_manager.py    # Per-round lifecycle (intro → playing → reveal → next)
│   ├── scoring.py          # Per-player scoring per round
│   └── ...
├── server/
│   ├── __init__.py         # async_register_static_paths → /beatify/static/
│   ├── ws_handlers.py      # ~40 WS message types (live FE↔BE protocol)
│   ├── playlist_views.py   # /beatify/api/playlist-requests endpoint (HA-side)
│   └── ...
├── services/
│   ├── media_player.py     # MA + Sonos + Alexa playback dispatch
│   ├── tts.py              # Gemini / Cloud TTS announcements
│   └── analytics.py        # Local error/event tracking
├── playlists/              # 24 bundled playlists (v3.3.3 line)
│   ├── *.json              # 11 default + 13 community (genre/region/era)
│   └── community/          # User-contributed, separate browse tab
├── translations/           # HA-internal (config flow, services)
└── www/                    # Frontend assets
    ├── admin.html          # Host UI (the "control panel")
    ├── player.html         # Guest UI (lobby + reveal)
    ├── dashboard.html      # Post-game stats screen
    ├── sw.js               # PWA service worker (CACHE_VERSION pattern)
    ├── i18n/               # 5 locales: en/de/es/fr/nl
    ├── js/
    │   ├── admin.js        # 4044 LOC, 8 logical sections (auth, wizard, modals, WS hub)
    │   ├── player.bundle.min.js  # ES module bundle
    │   ├── playlist-hub.js # The 3-tab playlist browser (v3.3.0 feature)
    │   ├── playlist-requests.js  # Submit + poll for user playlist requests
    │   └── i18n.js, party-lights.js, dashboard.js, ...
    └── css/
        └── styles.min.css

tests/
├── unit/                   # 19 test files, 442+ tests (pytest)
└── integration/            # WS protocol smoke tests
custom_components/beatify/www/js/__tests__/
└── *.test.js               # Vitest JS unit tests (35 currently)

scripts/
└── fix_broken_tracks.py    # Periodic URI-health automation
```

## 3. Game state machine

`game/state.py` owns five subsystems and references three more:

**Owned:**
1. **GamePhase** — IDLE / LOBBY / PLAYING / REVEAL / PAUSED. Transitions are gated by `_end_round_unlocked` and `_advance_phase`.
2. **Round lifecycle** — initialize → confirm intro → start playing → end round (timer or all-submitted) → reveal → broadcast → next round.
3. **Player roster** — admin (the host, a special player) + 0..N guests. Reclaim-by-name for WS reconnect (#790).
4. **Scoring** — per-player per-round, isolated try/except so one player's exception doesn't freeze the round (#816). Closest-wins handled in `apply_closest_wins`.
5. **Pause/resume** — `pause_game(reason)` captures phase + round state; `resume_game` restores the phase the user paused FROM (not always REVEAL — could be PLAYING or PAUSED itself with a stale-title cause).

**Referenced services:**
- `MediaPlayerService` → playback (see §4)
- `TTSService` → announcements
- `PlaylistService` → playlist load + URI resolution

**Round-flow defensive coding (since v3.3.2):**
- Every `asyncio.create_task` in the round-flow has an `add_done_callback` that surfaces unretrieved exceptions with a stack trace. Previously, a silent crash would leave the round frozen with no log — fixed for the #816 class of bugs.

## 4. Provider URI dispatch (the #768 / #805 / #808 story)

`services/media_player.py` lines 111–131 hold the design that took three issues to settle:

```python
_PROVIDER_URI_FIELDS: dict[str, tuple[str, ...]] = {
    "spotify":       ("uri_spotify", "uri"),
    "apple_music":   ("uri_apple_music",),
    "youtube_music": ("uri_youtube_music",),
    "tidal":         ("uri_tidal",),
    "deezer":        ("uri_deezer",),
}
```

The cascade in `_get_ma_uri_candidates(song)` walks ONLY the user-selected provider's fields. The original design (#768) walked all six providers in order, falling through if Spotify failed. That was wrong on Apple-Music-only setups: each round paid 4×15s of timeouts on Spotify/YT/Tidal URIs that MA had no provider configured for, before getting to the working Apple Music URI. After 3 cumulative play_song failures, the game force-paused and the admin couldn't recover. (#805 narrowed the cascade; @Levtos's stress-testing surfaced it.)

#808 added the storefront dimension on top: Apple Music URIs are per-country. A US-storefront track ID isn't in the DE catalog, so MA accepts the URI but can't resolve a stream — the speaker stays on the prior track. Fix: per-region URI map (`uri_apple_music_by_region`) for 2,204 ISRC-resolved songs, runtime resolver picks based on `hass.config.country`, and region-locked songs get filtered at playlist load.

#777 added the strict-detection invariant: if `media_title` doesn't change after the play_media call, the new track never started — fail and try the next URI. v3.3.3-rc1 hardens the same path against transient `hass.states.get()` exceptions (the lone xfailed test, finally fixed).

## 5. WebSocket protocol

`server/ws_handlers.py` registers ~40 message types. Categories:

- **Auth** — `admin_join`, `player_join`, `reconnect` (with name-based admin reclaim)
- **Game lifecycle** — `start_game`, `end_game`, `pause_game`, `resume_game`
- **Round** — `next_round`, `submit_guess`, `confirm_intro`
- **State sync** — `state_update` (broadcast to all clients), `phase_change`
- **Player management** — `kick_player`, `rename_player`
- **Playlist requests** — `submit_request`, `poll_requests`

The `state_update` broadcast carries the entire serialised game state (phases, players, current round, scores). Clients keep a local mirror updated; admin.js's WebSocket hub (lines ~3100–4044) reconciles it against the active view.

Failure modes:
- **WS dropped during reveal** — `reconnect` with same name returns admin to admin role, regardless of phase (#790).
- **HA restart** — admin.js retries with 20s budget (was 5s pre-#814), shows "Connecting…" inline rather than blocking native alert.

## 6. Playlist request flow

End-to-end from the host's "+ Add custom playlist" tap:

```
admin.js (lines ~2931-2961)              [user pastes Spotify URL]
        │
        │ POST {spotify_url}
        ▼
playlist-requests.js submitRequest       [Worker bridge]
        │
        │ POST https://beatify-api.mholzi.workers.dev/
        ▼
Cloudflare Worker                        [Dashboard-deployed, no repo]
    Decrypts URL → calls Spotify Web API → fetches playlist metadata
    → opens issue on github.com/mholzi/beatify with template body +
      `playlist-request` label
    Failure modes (#835 era): GITHUB_TOKEN expired → 500 / error:github_error
                              Spotify URL invalid → 400 / error:invalid_format
                              Playlist private/deleted → 404 / error:playlist_not_found
        │
        ▼
GitHub Issue                             [Manual enrichment workflow]
    Maintainer fetches tracks via Spotify API + iTunes (release year)
    + Last.fm (alt-artists), generates fun_facts, drops into
    `custom_components/beatify/playlists/community/<slug>.json`
        │
        ▼
Next HACS release                        [User pulls update]
    HACS sees new version → user upgrades → playlist appears in
    Playlist Hub's Community tab
```

The Worker has historically been the most fragile link — its source isn't in version control (Dashboard-only deployment). Followup in the v3.3.3 line: surface the worker's structured `error.code` in the UI (`playlist-requests.js:99` + `admin.js:2956`) so users see why their submission failed instead of an opaque "Failed to create request".

## 7. Frontend asset serving + cache-busting (#824)

`server/__init__.py:30` registers `/beatify/static/` → `<integration>/www/`. All JS / CSS / i18n JSON / images are served from there.

The cache-bust pattern (post-#824 regression):
- Every HTML page declares `<meta name="beatify-version" content="X.Y.Z">`.
- `i18n.js getVersionForCacheBust()` reads it, appends `?v=X.Y.Z` to JSON fetch URLs.
- Each release bumps that meta tag in admin.html / player.html / dashboard.html alongside `manifest.json` and `sw.js CACHE_VERSION`.
- Without this: a user upgrading from rc14 → rc18 would see service-worker-cached `en.json` from rc14 while the new admin.min.js referenced rc18 keys, producing raw `admin.home.waitingForGuests` strings on screen.

The `Makefile` build target wires this together: `make build` runs esbuild over admin / playlist-requests / player / etc., regenerates the `.min.js` bundles. Cache-buster query strings then point the browser at the fresh files.

## 8. PWA / Service worker

`www/sw.js` uses a cache-first strategy for `/beatify/static/*` with the version baked into `CACHE_VERSION`. Upgrade flow: bump CACHE_VERSION → service worker activates new version → old cache evicted. The pre-cache list covers admin.min.js, dashboard.min.js, player.min.js, i18n.min.js, vendor/qrcode.min.js, and CSS bundles.

A subtle pre-#824 bug: cache-first served a stale `i18n/<lang>.json` indefinitely because the JSON URL had no version query, so the SW kept returning the old cached version. Fixed by the `<meta beatify-version>` + `?v=` cache-bust pattern.

## 9. TTS announcements

`services/tts.py` (~82 LOC) calls `tts.speak` with both `entity_id` AND `media_player_entity_id`. Pre-#793, only `entity_id` was passed, which silently failed on every modern TTS engine (Gemini, Cloud, etc.) — they all need the media-player target explicitly.

`tts-settings.js` exposes per-game-event toggles: round start, guess submitted, time warning, reveal, winner. Each event maps to a templated phrase in the active language.

## 10. Test strategy

- **`tests/unit/`** — pytest, 442+ tests covering state.py, scoring, playlist filtering, provider URI dispatch. Heavy use of `_make_hass()` / `_make_state()` mocks for HA's state machine.
- **`tests/integration/`** — pytest, exercises WS handlers end-to-end via mocked HA + WS client.
- **`custom_components/beatify/www/js/__tests__/`** — vitest, 35 tests covering JS-side game logic (player-tour, wizard).
- **Burn-in CI** — flaky-test detection runs every test 10× weekly (Mon 06:00 UTC).
- **HACS validation** — `validate.yml` runs `hacs/action` + `hassfest` on every push.

Notable: `TestMAPollingResilience` (the formerly xfailed test, fixed in 26585cf4) verifies that transient `hass.states.get()` exceptions during MA playback confirmation don't abort the song — the safe-state helpers wrap the four read sites in `_play_via_ma`.

## 11. Build + ship

```bash
# Local dev
PATH=/opt/homebrew/bin:$PATH make build       # regenerates *.min.js bundles
npm test                                      # vitest JS suite (35 tests)
python3 -m pytest -q                          # pytest Python suite

# Release
# 1. Bump manifest.json version + sw.js CACHE_VERSION + 3× <meta beatify-version>
#    + admin.html/player.html cache-busters → new version
# 2. CHANGELOG.md entry under [<version>]
# 3. make build (regenerate .min.js)
# 4. git commit + push + tag
# 5. gh release create --prerelease (rc) or stable
```

HACS subscribers see new versions automatically (pre-release subscribers see rcs separately from stable).

## 12. Operational footprint

- **Telemetry**: zero external. The `analytics.py` module records error events to local HA storage; the dashboard surfaces them. No HTTP calls leave the user's instance unless THEY submit a playlist via the request flow.
- **Persistence**: game history → `GameRecord` entries in HA storage; survives HA restarts; fuels the "Your most-played" / "Recently played" shelves in the Playlist Hub.
- **State machine**: in-memory only. A HA restart mid-game ends the game (admin can rejoin once HA is back up — recovery banner offers Resume from PAUSED phase).
- **Resource use**: ~36 Python files, ~20 unminified JS files, 19 test files. Cold start ~1–2s. Per-round overhead dominated by speaker buffer wait (10–15s, MA-bound).

## 13. Known dragons

The wiki at `~/Development/Claude/beatifybot/wiki/` (private to the maintainer, BeatifyBot's knowledge base) holds the long-form synthesis on:
- Recurring URI-bug patterns (the dominant bug class, see synthesis/recurring-uri-bug-pattern)
- Recurring playback-bug patterns (state-sync fragility FE↔MA↔Speaker)
- External feedback that pre-empted GitHub issues (Reddit + Discussions surfaced the provider-mismatch bugs months before #768/#808)

If you're picking this up cold and hit a confusing failure mode, search closed issues by symptom — almost every weird playback case has a documented incident with the post-mortem comment.
