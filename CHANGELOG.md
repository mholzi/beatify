# Changelog

All notable changes to Beatify are documented here. For detailed release notes, see the individual files in `docs/` or the [Releases page](https://github.com/mholzi/beatify/releases).

## [Unreleased]

## [3.3.2-rc10] - 2026-04-28

### Changed
- **Pause-recovery banner now teaches the actual fix (#808 follow-up).** When `pause_reason` is `media_player_error`, the banner used to say "Playback failed for the last 3 songs. Resume or end the game" — generic and unactionable. After @mholzi diagnosed his own #808 instance as "Apple Music provider needed re-authentication in MA settings", the banner now explicitly names the user's selected provider and points them at the exact recovery step: *"Playback failed for the last 3 songs. This often means [Apple Music] in Music Assistant needs re-authentication — Settings → Music Assistant → [Apple Music] → Reconnect, then click Resume."* Backend serializer surfaces `provider` in PAUSED state payloads; frontend renderer interpolates `{provider}` placeholder against locale-specific names.

### For contributors
- Added `provider` to PAUSED-phase state payload in `serializers.py`. Frontend reads `data.provider` for the banner template.
- New i18n keys per locale (en/de/es/fr/nl): `admin.pauseRecovery.mediaPlayerError` (with `{provider}` placeholder), `admin.pauseRecovery.mediaPlayerErrorGeneric` (provider-less fallback), `admin.pauseRecovery.providerSpotify`/`AppleMusic`/`YouTubeMusic`/`Tidal`/`Deezer` for display-name interpolation.
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc10`. `admin.min.js` + `styles.min.css` cache-busters bumped; minified rebuilt.
- 1 new serializer test covering `provider` in PAUSED payload. 427 passed, 1 xfailed.

### Out of scope (filed for later)
- Real preflight check via MA's WebSocket API (`config/providers/get_all`) so we can detect unauthenticated providers *before* the game starts and skip the 3×15s pause cycle. Filing as a separate enhancement issue — needs MA WS auth handling, schema versioning, and fallback paths.

## [3.3.2-rc9] - 2026-04-28

### Fixed
- **Apple Music wizard selection no longer silently coerced to Spotify (#808).** @Levtos's report against (the now-deleted) v3.3.2 tag exposed the originating bug behind the rc6+rc8 cascade work: `PROVIDER_APPLE_MUSIC` was missing from the `valid_providers` tuple in `StartGameView`, so any wizard selection of "apple_music" silently became "spotify" before reaching `game_state.create_game`. Pre-rc7 this was near-invisible because the cascade walked all six URI fields anyway; after rc7's provider-narrowed cascade (#805), Apple-Music users got Spotify-only candidates and every round failed before MA's resolver. Round 1 couldn't start, the game paused, and the integration was unusable on Apple-Music-only Music Assistant setups.

### For contributors
- Refactored the inline `valid_providers` tuple into module-level `_validate_provider()` so the rule is unit-testable.
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc9`. No frontend asset changes — HTML cache-busters unchanged.
- 13 new tests in `tests/unit/test_game_views.py` (round-trip for all 5 providers, explicit Apple-Music regression guard, invalid-input fallback). 426 passed, 1 xfailed.

## [3.3.2-rc8] - 2026-04-27

### Added
- **Resume-from-paused recovery UI (#805 follow-up).** When the game pauses due to a playback error, the admin now sees a warning banner at the top of the playing section: title, explanatory message keyed to `pause_reason`, optional `last_error_detail` line, and two buttons — Resume (calls new `resume_game` admin action) and End game. Previously the only PAUSED indicator was the timer label saying `⏸ Paused`, with no way to recover other than reconnecting.
- **`resume_game` admin WS action.** Calls `game_state.resume_game()` and broadcasts. Validates the phase is PAUSED before acting; surfaces ERR_INVALID_ACTION if the resume itself fails (e.g. no `_previous_phase` stored).
- **`pauseRecovery` i18n keys** in en/de/es/fr/nl: `title`, `mediaPlayerError`, `noSongsAvailable`, `resume`, `endGame`.

### Fixed
- **End game from PAUSED no longer rejected (#805 follow-up).** `admin_end_game` was only allowing PLAYING and REVEAL — clicking End on the (already-visible) PAUSED control bar silently failed with ERR_INVALID_ACTION. Added PAUSED to the allowed phases.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc8`. Bumped `admin.min.js` + `styles.min.css` cache-busters in `admin.html`. CSS + admin.js minified rebuild.
- 7 new tests across `test_websocket.py` (3 for `admin_resume_game`, 2 for `admin_end_game` from PAUSED) and `test_state.py` (2 for serializer surfacing `pause_reason` + `last_error_detail`). 413 passed, 1 xfailed.
- Serializer now includes `last_error_detail` in PAUSED-phase state payloads (frontend reads it for the recovery-banner detail line).

## [3.3.2-rc7] - 2026-04-27

### Fixed
- **MA URI cascade now respects the user's provider choice (#805).** @Levtos's Apple-Music-only setup paid 4×15s of timeouts every failed round because the cascade walked Spotify → legacy `uri` → Apple Music → YouTube Music → Tidal → Deezer regardless of the wizard provider. Three failed rounds in a row hit `MAX_SONG_RETRIES`, the game force-paused, and the WS handler then promoted PAUSED → END so admin couldn't recover. New `_PROVIDER_URI_FIELDS` map keys URI fields by provider; `_get_ma_uri_candidates()` only walks the user-selected provider's fields. `_resolved_uri` is still tried first; the same-provider fallback (e.g. legacy `uri` for Spotify) is preserved.
- **Game no longer ends silently after MA-error pause (#805 part 2).** When `start_round()` paused the game (media-player error / `MAX_SONG_RETRIES` exhausted), `admin_next_round` was unconditionally calling `advance_to_end()` and dropping the user onto the podium screen. Now: if `start_round()` returns False AND phase has transitioned to PAUSED, we leave it paused and broadcast that state so the UI shows the paused indicator instead. (A resume-from-paused admin button is filed as a follow-up.)

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc7`. No frontend asset changes — HTML cache-busters unchanged.
- Rewrote 5 cross-provider tests in `TestMAProviderFallback` to assert the new same-provider invariant. Added 2 new `TestAdminNextRoundPausedRecovery` tests in `test_websocket.py` covering the PAUSED-stays-paused path and a regression guard for natural end. 406 passed, 1 xfailed.

## [3.3.2-rc6] - 2026-04-26

### Fixed
- **Speaker is now actively stopped when stale-title is detected (#801).** @Levtos's playthrough showed `'Kill Bill'` continuing through multiple rounds while strict-detection (#795) correctly rejected URI candidates — the rejection logic worked, but nothing was telling the speaker to stop the prior track. Added a `media_stop` call in the stale-title branch of `_try_ma_play` (best-effort, failure swallowed since we're already returning False). The hard-stop only triggers on the explicit failure path; normal playback continues uninterrupted until the admin advances the round.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc6`. No frontend asset changes — HTML cache-busters unchanged.
- 1 new unit test in `test_media_player.py` covering `media_stop` called exactly once on stale-title detect. 402 passed, 1 xfailed.

## [3.3.2-rc5] - 2026-04-26

### Fixed
- **Round 1 no longer freezes for 10–15s on cold MA start (#803).** @Ziigmund84 reported the wizard kicking off the first round and sitting frozen on REVEAL while audio was already playing through the speaker. Root cause: the strict-detect fast-path in `_try_ma_play` required `media_position >= 1`. On a cold MA boot, the speaker reports `state=playing` and the correct `media_title` within a few seconds, but `media_position` lags at `0` for 10–15s while MA finishes warming up. The old fast-path didn't fire, so `_try_ma_play` waited the full `MA_PLAYBACK_TIMEOUT` before letting the round advance — even though playback was already healthy. Dropped the `position >= 1` requirement: `position_updated_at` advancing already filters out the queued-but-not-playing case (a queued track's timestamp doesn't move). Title-match + fresh `position_updated_at` is enough.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc5` (skipped `rc4` — that number is reserved for unmerged PR #802 on a separate branch). No frontend asset changes — HTML cache-busters unchanged.
- Renamed `test_ma_waits_for_position_ge_1` → `test_ma_fast_path_succeeds_when_title_matches_even_if_position_zero` and removed the now-redundant `test_ma_does_not_trigger_on_title_change_alone`. 401 passed, 1 xfailed.

## [3.3.2-rc3] - 2026-04-26

### Fixed
- **Game no longer advances while speaker is stuck on a prior track (#795).** Levtos's playthrough on AirPlay + Apple Music + MA had the speaker stuck on `'Sugar, Sugar'` then `'Lazy Sunday (Mono)'` for multiple rounds while position kept advancing — the rc5 #345 tolerance was treating "title unchanged + position changed" as success because position alone was advancing. But position-only-changing means the *prior* track is still playing in real time, not that a new track started. Tightened invariant: `media_title` MUST advance to something different from before the call. Position alone is no longer enough. The #345 slow-buffer tolerance is preserved when title genuinely changed (handles the "speaker reports new title late" case for legitimate slow buffers).

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc3`. No frontend asset changes — HTML cache-busters unchanged.
- Updated 1 existing test (renamed `test_ma_tolerates_slow_buffer_when_position_timestamp_advanced` → `test_ma_returns_false_when_title_unchanged_but_position_advances`, flipped expectation to `False`). 402 passed, 1 xfailed.

## [3.3.2-rc2] - 2026-04-26

### Fixed
- **Deezer via Music Assistant (#797)** — same shape of bug as #772 (Apple Music) but for Deezer. Beatify was converting `deezer://track/<id>` → `https://www.deezer.com/track/<id>`, which routed through MA's generic `http(s)://` branch to the **builtin** provider — and builtin doesn't know how to play Deezer. Result: `HomeAssistantError: No playable items found`. Pass through the native `deezer://track/<id>` form so MA routes directly to the Deezer provider domain. Reported by @Ziigmund84.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc2`. No frontend asset changes — HTML cache-busters unchanged.
- 1 new test in `test_media_player.py` covering the native Deezer URI passthrough. 402 passed, 1 xfailed.

## [3.3.2-rc1] - 2026-04-25

### Fixed
- **TTS announcements actually play now (#793)** — Beatify was calling HA's modern `tts.speak` service with only `entity_id` (the TTS provider). The service requires *both* `entity_id` AND `media_player_entity_id` — without the speaker target, audio generated but had nowhere to play, so announcements went silent on every modern TTS entity (Gemini, Cloud, etc.). Reported by @szszl0 on Gemini TTS.
  - `TTSService` constructor now takes both identifiers. The runtime path reuses the game's existing speaker (announcements come out of the same speaker as the music — natural).
  - `POST /beatify/api/tts-test` now requires `media_player_entity_id` in the request body and validates entity domains strictly (TTS entity must be `tts.*`, target must be `media_player.*`).
  - Admin "Test TTS" button + wizard "Test" button both pull the chosen speaker from the existing game settings and forward it. If no speaker has been picked yet, both surface a *"Pick a speaker first"* hint instead of silently failing.

### Added
- 6 new unit tests in `tests/unit/test_tts.py` covering the dual-entity wiring, missing-id defensive paths, unavailable-entity skips, and exception swallowing.
- 1 new i18n key per locale (en/de/es/fr/nl): `admin.ttsTestNoSpeaker`.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + `wizard.js?v=` + `admin.min.js?v=` + `tts-settings.js?v=` cache-busters → `3.3.2-rc1`. CSS unchanged.
- 401 passed, 1 xfailed.

## [3.3.1] - 2026-04-25

Stable promotion of the 3.3.1-rc line. See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.1) for the user-facing summary.

### Fixed
- **Apple Music via Music Assistant (#772)** — emit MA's native `apple_music://track/<id>` URI; the short `music.apple.com/song/<id>` URL was rejected by MA's parser. Closes the remaining failure from @Levtos's #768 follow-up.
- **Silent rounds when MA can't start a track (#777)** — strict-detection compares speaker `media_title` and `media_position_updated_at` before/after the wait; "neither moved" is now a hard failure that falls through to the next URI candidate. MA timeout extended 8s → 15s for AirPlay.
- **Admin can reclaim their own role during any phase (#790)** — same-name + `is_admin=true` reconnect during REVEAL/PLAYING is recognised as the existing admin returning. Bonus: `pause_game` now captures admin name on every reason, not just `admin_disconnected`.
- **Service worker scope mismatch (#780)** — moved `sw.js` to `/beatify/sw.js` so its `/beatify/` scope claim is allowed. The SW finally activates; all `CACHE_VERSION` bumps now do what they say.
- **Admin footer version label (#784)** — read from `manifest.json` at setup instead of a hardcoded constant that drifted to `v3.2.0-rc29` since April. Single source of truth, no GitHub Action dependency.
- **Wizard provider chips re-render on speaker change** — switching speakers in Step 1 no longer leaves stale chip-dimming in Step 2.
- **Admin i18n keys** (`admin.filterAll`, `admin.skipRound`) added across all 5 locales (#779).
- **6 stale unit tests** un-xfailed by fixing the actual test bugs (closes #788).

### Added
- **Wizard service-compatibility UX (#772)** — capability badges per speaker in Step 1 (*"All services"* / *"Spotify only"* / *"Spotify, Apple Music"*) and dimmed-with-lock provider chips in Step 2 with an explainer card pointing to Music Assistant. Continue is blocked until a supported provider is picked. Locale word order respected across en/de/es/fr/nl.
- **Emergency reset button** — small ⟲ icon in the admin header. One click ends any active game on the server, clears Beatify's localStorage, unregisters the service worker, and reloads. Backed by a new rate-limited `POST /beatify/api/force-reset` endpoint that doesn't require an admin token. Born from @Levtos's "großen roten Button" request.
- **Backend force-reset endpoint** — `POST /beatify/api/force-reset` (3/hour per IP, no auth — by design, since the situation that needs it is one where the admin token may be unreachable).

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + all HTML `?v=` cache-busters → `3.3.1`.
- CI restored after two months untracked: `test.yml`, `validate.yml`, `conftest.py`, `pytest.ini` re-tracked. 53 files re-formatted to ruff baseline. `_VERSION` constant deleted; obsolete `version-bump.yml` workflow removed.
- 17 new tests across MA stale-state detection, provider-capability gating, admin reclaim during REVEAL, pause-game admin-name capture. Total: 395 passed, 1 xfailed.
- 12 new i18n keys across en/de/es/fr/nl: capability badges (`admin.step1.cap*`), MA explainer (`admin.step2.explainer.*`), reset modal (`admin.reset.*`).

## [3.3.1-rc8] - 2026-04-25

### Fixed
- **Admin can reclaim their own role during any game phase (#790).** When the admin's WebSocket dropped silently during REVEAL or PLAYING (network blip, AirPlay-induced HA hiccup) and the browser tried to reconnect with the same name + `is_admin=true`, the join handler hit the *"Only allow new admin claim during LOBBY"* rejection at [`ws_handlers.py:113`](custom_components/beatify/server/ws_handlers.py#L113), removed the player from the game, and sent them to the name-entry screen — locking them out of their own game. Now the handler recognises a same-name admin reclaim by checking the existing player record's `is_admin=True` flag and allows the reconnect regardless of phase. New admins claiming during non-LOBBY phases are still rejected. Reported by @Levtos in #790.
- **`pause_game` always captures the admin name (#790).** Previously only `pause_game("admin_disconnected")` set `disconnected_admin_name`. Server-triggered pauses (`media_player_error`, `no_songs_available`) left the field empty, so even via the existing reconnect path the admin couldn't recover from those pauses. Now any pause stores the current admin's name, giving them a guaranteed recovery route.

### Tests
- 3 new tests covering: same-name admin reclaim during REVEAL, intruder claim during REVEAL still rejected, `pause_game` capturing admin name on `media_player_error` and `no_songs_available`.
- Total: 395 passed, 1 xfailed (the pre-existing #777 resilience test).

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.1-rc8`. No frontend asset changes — HTML cache-busters unchanged.

## [3.3.1-rc7] - 2026-04-25

### Fixed
- **Admin footer version label is correct again (#784).** The footer had been showing *"Beatify v3.2.0-rc29"* since mid-April regardless of which version was installed. Root cause: a `_VERSION = "3.2.0-rc29"` constant in [`server/base.py`](custom_components/beatify/server/base.py) was supposed to be auto-bumped by a GitHub workflow that hadn't run since April 15 (the `.github/workflows/` directory got untracked in [`6d056b35`](https://github.com/mholzi/beatify/commit/6d056b35) and GitHub Actions has no copy to execute). Replaced the constant with a read of `manifest.json` at integration setup time — single source of truth, no workflow dependency, can never drift again. Reported by @mholzi in #784.

### For contributors
- New helper `_read_manifest_version()` in `__init__.py`, called via `async_add_executor_job` to stay off the event loop.
- Version is cached in `hass.data[DOMAIN]['version']` and read by `_get_version(hass)` in `server/base.py` (signature changed from `_get_version()` — only one caller).
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.1-rc7`. No frontend asset changes — HTML cache-busters unchanged.
- The auto-bump workflow `.github/workflows/version-bump.yml` is now obsolete and can be deleted from the local-only copy. The other untracked workflows (`test.yml`, `validate.yml`, `pages.yml`) are a separate question — re-track them or accept local-only checks as the contract.

## [3.3.1-rc6] - 2026-04-25

### Added
- **Reset button — emergency escape hatch (#777 follow-up).** A small ⟲ button now sits in the admin header next to the analytics icon. Tapping it opens a confirmation modal (*"Reset Beatify? Ends any active game and forgets your last setup."*). On confirm, Beatify ends any active game on the server (no admin token required — by definition the user might not have one if state is stuck), clears the integration's localStorage keys, unregisters the service worker, and reloads onto the admin entry point. Reported by @Levtos: stuck on a stale lobby after an HA restart with no in-product way out.

### For contributors
- New backend endpoint: `POST /beatify/api/force-reset` (no auth, rate-limited to 3 per hour per IP — same blast radius as `/end-game` but the lower friction is intentional).
- Bumped manifest + `sw.js CACHE_VERSION` + `admin.min.js?v=` + `styles.min.css?v=` cache-busters → `3.3.1-rc6`.
- 4 new i18n keys per locale: `admin.reset.{tooltip,title,message,confirm}` (en/de/es/fr/nl).

## [3.3.1-rc5] - 2026-04-24

### Fixed
- **Silent playback failures no longer advance the round (#777)** — when MA couldn't actually start the new track (AirPlay silently skipping, Apple Music lookup returning "No playable items found", etc.) the speaker would keep playing the previous song while reporting `state: playing`. Beatify's wait-for-playback loop timed out and then returned success anyway ("Continuing anyway — MA may still be buffering"), advancing the question + countdown into a silent round. Now, if neither `media_title` nor `media_position_updated_at` changed during the wait window, it's treated as a hard failure — the fallback cascade tries the next URI candidate instead of pretending playback started.
- **MA playback timeout extended from 8s to 15s** (new `MA_PLAYBACK_TIMEOUT` constant). 8s was too aggressive for AirPlay setups (HomePod groups, Denon AirPlay) which legitimately take 10-12s to acknowledge a new track. Non-MA platforms (Sonos-direct, Alexa text-search) still use the original 8s.

### Tests
- 3 new tests covering the new stale-detection path and both #345 tolerance branches.
- 4 stale pre-existing test assertions cleaned up (they checked polling implementation details that haven't matched the event-based code in some time).
- 1 pre-existing resilience test xfail'd pending a separate fix for transient `states.get` exceptions.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.1-rc5`. No frontend asset changes, so no HTML cache-buster bumps.

## [3.3.1-rc4] - 2026-04-24

### Fixed
- **Service worker now actually activates (#780)** — `sw.js` was registered from `/beatify/static/sw.js` with scope `/beatify/`, which browsers block (a SW can only claim its own path or deeper). The SW has been silently failing to register since Story 18.5 shipped, meaning offline/cache-first asset serving was dead and every `CACHE_VERSION` bump since was a no-op. Added a dedicated `SwJsView` that serves the script from `/beatify/sw.js` so the wider scope registers cleanly. All three registration call sites (`admin.js`, `dashboard.js`, `player-core.js`) updated.
- **Missing i18n keys: `admin.filterAll` and `admin.skipRound` (#779)** — two keys were referenced in `admin.html` but absent from every locale JSON, logging `[i18n] Missing translation key:` warnings on every admin load. Non-English users silently got the HTML fallback ("All" / "Skip"). Added to all 5 locales.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.1-rc4`. Cache-busters bumped on `admin.min.js`, `dashboard.min.js`, `player.bundle.min.js` (all three regenerated because `serviceWorker.register` URL changed inside them). `wizard.js?v=` and `styles.min.css?v=` unchanged from rc3.

## [3.3.1-rc3] - 2026-04-24

### Fixed
- **Wizard provider chips now re-render when speaker changes (#772)** — going Back from Step 2, picking a different speaker, and returning to Step 2 used to show the *previous* speaker's chip dim-state. Caught via live test: after switching from a Sonos speaker to a Music Assistant speaker, Apple Music / YouTube Music / Tidal / Deezer all stayed locked even though MA supports them. Speaker-click handler now re-renders providers and clears `chosenProvider` if it became unsupported on the new speaker.
- **Explainer footer now uses `{platform}` placeholder** — the footer had hardcoded "Sonos" in every translation, so an Alexa user saw *"Prefer Spotify? It works on Sonos directly"* which is confusing/wrong. Reads correctly in each locale now (en/de/es/fr/nl updated).
- **Capability badge word order for non-English locales** — the *"Spotify only"* badge rendered as *"Spotify nur"* in German instead of *"nur Spotify"* (modifier goes first in German, Spanish, Dutch). The old `capOnly` key was a suffix word; replaced with `capOnlyTemplate` containing a `{provider}` placeholder so each locale controls its own word order.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + `wizard.js?v=` → `3.3.1-rc3`. CSS unchanged.
- i18n key rename: `wizard.step1.capOnly` → `wizard.step1.capOnlyTemplate` (a format string with `{provider}` instead of a standalone suffix word).

## [3.3.1-rc2] - 2026-04-24

### Fixed
- **Wizard translations for rc1 UX (#772)** — the capability badges ("All services", "only") and the Music Assistant explainer card in Step 2 were using hardcoded English fallbacks because the new keys weren't added to the i18n JSON files. Non-English locales (de/es/fr/nl) now get real translations instead of the English source string. The `_t()` helper also now forwards `{placeholder}` params through to `BeatifyI18n.t`, so the explainer interpolates the speaker's platform and the picked provider correctly in every language.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + `wizard.js?v=` → `3.3.1-rc2`. CSS unchanged.

## [3.3.1-rc1] - 2026-04-24

### Fixed
- **Apple Music via Music Assistant (#772)** — Beatify now emits Music Assistant's native `apple_music://track/<id>` URI instead of the short `https://music.apple.com/song/<id>` URL. The short URL fails MA's URI parser (needs `/{storefront}/{type}/{slug}/{id}`, 6+ path parts), so Apple-Music-only setups saw `No playable items found` on fallback. Also resolves the remaining Apple Music playback failure reported by @Levtos in the #768 follow-up.

### Added
- **Wizard service-compatibility UX (#772)** — picking a speaker that doesn't support every streaming service (e.g. Sonos) now surfaces that clearly in Step 1 with a capability badge (*"Spotify only"*, *"All services"*, *"Spotify, Apple Music"*). In Step 2, unsupported providers render dimmed with a lock icon; clicking one opens an explainer card with a one-click link to the Music Assistant integration docs. Continue is blocked until a supported provider is picked.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + `styles.min.css?v=` + `wizard.js?v=` cache-busters → `3.3.1-rc1`.

## [3.3.0] - 2026-04-23

Stable promotion of the 3.3.0-rc line. See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.0) for the user-facing summary.

### Added
- **Playlist Hub** (rc1–rc4) — new mobile-first playlist picker replaces wizard step 3. Browse bundled defaults, community playlists organized by country, and pass-through Music Assistant playlists in one place. Source tagging, local usage endpoints, labeled select pill, back button, select-and-start FAB, i18n across en/de/es/fr/nl.
- **Admin Dashboard Arcade refresh** (rc6) — chip strip (intro/closest-wins · round · submissions meter), animated cyan album-art timer ring, restructured reveal with motivator in the chip strip.

### Fixed
- **Music Assistant provider fallback (#768)** (rc5) — MA playback now falls through every alternate `uri_*` on a track when the primary doesn't resolve. Learned-preference cache so subsequent rounds start instantly on the working provider. Reported and verified by @Levtos.
- Share card footer domain corrected (beatify.fun → beatify.life).
- 5 broken streaming URIs across eurodance-90s and koelner-karneval.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + all HTML `?v=` cache-busters → `3.3.0`.

## [3.3.0-rc6] - 2026-04-21

### Added
- **Dashboard v3.2.1 Arcade.** Playing view replaces the top-right round indicator with a single chip strip (intro/closest-wins badge · round · submissions meter) and rings the album art with an animated cyan timer. Reveal view adopts the same chip-strip pattern and moves the motivational message into it.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` + `dashboard.min.css?v=` cache-buster → `3.3.0-rc6`. Other HTML cache-busters left untouched (those assets didn't change in this rc).

## [3.3.0-rc5] - 2026-04-21

### Fixed
- **Apple Music (and any non-Spotify) playback in Music Assistant (#768).** Users whose MA had only Apple Music configured saw every song fail with `Could not resolve spotify:track:... to playable media item` because Beatify always dispatched the URI matching the Start-UI provider pick, even when MA had no such provider. MA playback now falls back through every alternate `uri_*` field on a track when the primary URI doesn't resolve. The first field that succeeds is cached on the service instance, so subsequent songs skip the dead primary and play on first attempt. Sonos and Alexa paths are unchanged.

### For contributors
- 2 new methods on `MediaPlayerService`: `_get_ma_uri_candidates()` (ordered candidate builder, dedupes by converted URI, promotes learned field) and `_try_ma_play()` (extracted single-URI body). Orchestration lives in `_play_via_music_assistant()`.
- 10 new tests in `TestMAProviderFallback` cover candidate ordering, learned-preference caching, and the all-fail path.
- Bumped manifest + `sw.js CACHE_VERSION` + `?v=` cache-busters in admin.html and player.html → `3.3.0-rc5`.

## [3.3.0-rc4] - 2026-04-19

### Added
- **Curated bundled + By-Country community.** Bundled trimmed from 20 to 11 broad-appeal staples (dropped the 9 specialty playlists — Cologne Carnival, Schlager, Fiesta Latina, British Invasion, Yacht Rock, Pop Punk, Eurodance, 90s/00s Hip Hop, Gen Z). Those 9 moved to `community/` with full metadata (language, author, description, added_date, version). The 4 existing community playlists got language backfilled. Total: 24 playlists stays the same, but the split is now 11 bundled + 13 community.
- **🌍 By Country section in the Community tab.** New section-head divider groups per-language shelves under one umbrella. Deterministic ordering (DE > EN > ES > FR > NL > IT > PT > JA > KO > other). Meta line reads "N countries · M playlists". Renders only when at least one language has 2+ playlists. New i18n keys: `playlistHub.sections.{byCountry, countries}`.

### Changed
- Release notes at `docs/release-3.3.0.md` — final-release draft in the exact v3.2.0 GitHub-release format. This rc carries it as the body.

### For contributors
- 9 files moved via `git mv` so blame stays intact. 13 playlist JSONs now have complete metadata.
- New CSS rule `.plh-section-head` (~30 lines).
- Bumped manifest + `sw.js CACHE_VERSION` + every `?v=` cache-buster → `3.3.0-rc4`.

## [3.3.0-rc3] - 2026-04-19

### Added
- **Back button inside the Playlist Hub CTA bar.** Wizard step 3 now shows a single nav row at the bottom: `[+ request FAB] [Back] [count ✓] [Continue →]`. rc2 put the wizard's own `Zurück` / `Weiter` underneath the hub's CTA, so users saw two Backs / two Forwards stacked. rc3 hands both gestures to the hub — the wizard's `#wiz-next` and `#wiz-back` hide on step 3 and reappear on every other step.

### Fixed
- **Request-a-playlist FAB was invisible against the dark CTA bar.** rc2 used a near-transparent `rgba(255,255,255,0.05)` fill with a 1px cyan border, so the envelope glyph was essentially unreadable. rc3 gives it a solid cyan gradient with a dark envelope icon — a proper secondary CTA affordance instead of a decorative square.
- **Card-select affordance was unclear.** The faint empty circle in the top-right corner didn't read as "add to round" — users didn't know what tapping it did, and it collided visually with the card-tap-for-detail gesture. rc3 replaces it with a labeled pill: **`+ Add`** (pink) when unselected, **`✓ Added`** (neon green) when selected, pinned to the top-LEFT so the top-right cover-badge (COMMUNITY / decade / date-added) stays intact. Picked from four design variants, full board at `~/.gstack/projects/mholzi-beatify/designs/card-select-20260419/variants.html`.

### For contributors
- `PlaylistHub.mount()` gains two new options: `showBack: true` + `onBack()`. Standalone mounts can leave `showBack: false` to hide the button.
- New i18n keys: `playlistHub.pill.{add, added, ariaAdd, ariaRemove}` and `playlistHub.cta.back` in `en.json` + `de.json`. German pill uses `Hinzu` / `Drin` to fit the 10px caps type without awkward truncation; longer `Zur Runde hinzufügen` / `Aus Runde entfernen` go on the aria-label for screen readers.
- `.plh-check` CSS kept as a `{ display: none }` guard so stale rc1/rc2 cached markup doesn't re-surface if the `CACHE_VERSION` bump misses anyone.
- Bumped manifest + `sw.js` `CACHE_VERSION` + every `?v=` cache-buster → `3.3.0-rc3`. Headless-Chrome smoke test re-verified: pill toggles, Back callback fires, FAB contrast reads, no console errors. 17 `wizard.test.js` tests pass.

## [3.3.0-rc2] - 2026-04-19

### Fixed
- **Duplicate "Weiter" button on wizard step 3.** The Playlist Hub renders its own Continue CTA in its bottom bar, but the wizard's legacy `#wiz-next` button was still showing below it — two Continue buttons stacked. rc2 hides `#wiz-next` on step 3 and wires the hub's Continue directly into the wizard's `_advance()` path so state persistence stays in one place.
- **Cover-art titles were truncated on long playlist names.** The v3.3.0-rc1 picker just took the first 3 characters of the first word — "Greatest Metal Songs" read "Gre…", "Top 100 Dutch Classics" read "Top". rc2 rewrites the glyph picker: decade tag wins first (`80s`, `10s`), then emoji/flag in the name (🤘, 🇳🇱), then short first word, then word-initials (`GMS`), then a 2-char fallback. Sub-title now clamps to 2 lines instead of ellipsing at the first word, so "NASHVILLE COUNTRY GOLD" reads fully beneath a `10s` glyph.
- **Duplicate count badge inside the Continue button.** The pink "Weiter 1 →" button showed the selection count a second time next to the green "1 ✓" pill on its left. Count now lives only in the pill; the button itself reads "Continue →" with a proper SVG arrow icon.
- **Orphan "+ Neue Playlist anfragen" button bleeding through.** The legacy `#wiz-request-playlist` element had the HTML `hidden` attribute but the `.btn` class was overriding it with `display: flex`. Locked it with an inline `display: none !important`. The Hub still triggers the same underlying request modal via `click()`.
- **Detail-sheet Add/Remove CTA.** Now renders with a plus or minus SVG icon next to the label so the action is scannable, not just a word.

### For contributors
- `_coverGlyph()` in `playlist-hub.js` rewritten. New `_extractEmoji()` helper uses `\p{Regional_Indicator}` + `\p{Extended_Pictographic}` with a try/catch for engines without Unicode property escapes.
- `.plh-cover-glyph-long` class applied when the glyph exceeds 3 chars, scales the type 42px → 26px.
- `.plh-cover-sub` now uses `-webkit-line-clamp: 2` + `word-break: break-word` instead of single-line-nowrap.
- New hub option `onContinue(paths)` fires from the Continue CTA. Wizard passes a handler that syncs `chosenPlaylists` and calls `_advance()`.
- Bumped manifest + `sw.js` `CACHE_VERSION` + every `?v=` cache-buster → `3.3.0-rc2`.
- All 17 `wizard.test.js` tests still pass. Headless-Chrome smoke test re-run against the fixture data — 21 cards, all glyphs now anchor cleanly, no sub-title ellipsis on the 22-char test name.

## [3.3.0-rc1] - 2026-04-19

### Added
- **Playlist Hub replaces the flat wizard-step-3 picker.** Three-way segmented control surfaces **Bundled (22)**, **Community (47)**, and **Mine** — the community subfolder is now a first-class browse surface instead of being hidden inside the flat list. Horizontal-scroll shelves inside each tab: *Your most-played* and *Recently played* ride the top of Bundled (neon-green **LOCAL** pill signals the data is yours, never sent anywhere), then *Editor's Picks*, genre shelves (Heavy Metal, 80s Pop, Jazz…), and a *From the Community* peek. Community tab adds a request banner, curated *Editor's Picks*, *Popular in <language>* rows, *Recently added* (manifest-date derived), and a *Regional & Specialty* shelf. Mine tab wraps the existing request flow with colored status badges (Pending → Reviewed → Building → In Bundled) and a 4-step progress strip per request. Tapping a card opens a bottom-sheet with song count, language, added date, tags, streaming-provider coverage, and a single "Add to round" CTA that syncs with the wizard's `chosenPlaylists` Set.
- `/beatify/api/usage?kind=top|recent` — new HTTP endpoint powering the local-stats shelves. Aggregates the existing `GameRecord.playlist_names` history, 30s cache, no new schema.
- Playlist JSON records gain a `source` field (`bundled` | `community`) on `async_discover_playlists` based on whether the file sits inside the community subfolder. Also surfaces `author`, `description`, `language`, `added_date`, and `version` so the UI can render detail sheets and freshness badges without a second round-trip.

### Changed
- Wizard step 3 DOM shrinks to a single `<div id="playlist-hub-root">`; the legacy `#wiz-request-playlist` button is retained hidden so the Hub can trigger the existing Spotify-URL request modal via `click()`. No changes to the request API or persistence path.
- i18n: adds the full `playlistHub.*` key tree to `en.json` + `de.json` (135 new lines each). Remaining locales (es, fr, nl) fall back to English defaults until translated.

### For contributors
- New ES module: `custom_components/beatify/www/js/playlist-hub.js` (~1000 lines). Owns all state, event delegation, data fetching, and rendering for the 6 hub views. Exports `mount()`, `unmount()`, `getSelection()`, `setSelection()`, `refresh()`, `getPlaylistByPath()`. Wizard passes `initialPlaylists` so the hub reuses the already-fetched `/api/status` payload instead of hitting it twice.
- ~1300 lines of CSS appended to `styles.css` under the `.plh-*` namespace. Every value reads from the existing DESIGN.md custom properties — no new tokens.
- New `UsageView` at `server/stats_views.py:231`, registered in `__init__.py`. `AnalyticsManager` gains `get_top_playlists(limit)` and `get_recent_playlists(limit)`.
- Bumped manifest, `sw.js` `CACHE_VERSION`, and every `?v=` cache-buster → `3.3.0-rc1`. `make build` regenerated `styles.min.css` (+40 KB from the hub styles).
- All 17 existing `wizard.test.js` tests pass. Runtime-smoke-tested via a standalone headless-Chrome harness with fixture data: 5 shelves + 21 cards on Bundled, 3 request cards on Mine, zero console errors across tab switches.
- **Known gap:** not yet exercised against a live HA install. The feature is shipping as a pre-release specifically so opt-in testers can poke at it. Report issues on the release page.

## [3.2.0-rc40] - 2026-04-19

### Changed
- **Share card redesigned as a vinyl record** (DESIGN.md share-card Variant D). The old PNG used an off-brand purple gradient (`#0f0c29` → `#302b63`) that violated the DESIGN.md palette — purple is reserved for analytics + the steal power-up. Replaced with a navy base + pink/cyan radial glows, the Beatify wordmark in the top-left (`Beat` white, `ify` pink-to-cyan gradient), an optional gradient `🏆 WINNER` badge in the top-right for the rank-1 player, a **180px black vinyl disc** with concentric groove rings as the centerpiece, a pink→cyan gradient label at the center with the player's score in big 48px Outfit 900 + "PTS" below, the player's name + rounds-correct count on one line beneath the vinyl ("jkjk · 10/10"), the playlist in italic quotes ("Top 100 Power Ballads"), and a stats footer with cyan-highlighted numbers ("1 exact · 🔥1 streak · beatify.fun"). The whole render waits for `document.fonts.ready` before drawing so Outfit + Inter are used instead of falling back to system-ui.

### For contributors
- `generateVisualCard()` in `player-end.js` rewritten end-to-end — same 800×800 target, same emoji-grid parsing (stats extracted from "N/N correct · Streak: N" and "N Exact · N/N Bets" lines), same native share → download fallback. `emoji_grids` text output is unchanged; the Copy Text button still copies the old multiline format so text-only sharing keeps working.
- New Canvas techniques: `createRadialGradient` for the vinyl glow + grooves, concentric `ctx.arc + ctx.stroke` for the groove rings, specular highlight via a top-left-weighted radial gradient, per-span color + font mixing for the stats footer ("1" in cyan Outfit, "exact" in muted Inter).
- Winner badge is conditional on `playerLine.indexOf('👑') !== -1` — the server already marks the winner's grid with a crown emoji, so no new shareData fields needed.
- Regenerated `player.bundle.min.js` (89.0 KB, up from 87.4 KB — ~1.6 KB net increase for the vinyl rendering logic). Bumped manifest, sw.js `CACHE_VERSION`, and `?v=` cache-busters → `beatify-v3.2.0-rc40`. All 24 Vitest tests pass.
- Design artifacts: `~/.gstack/projects/mholzi-beatify/designs/share-card-20260419/preview.html` (4-variant mockup with annotations on the tradeoffs).

## [3.2.0-rc39] - 2026-04-19

### Fixed
- **Reveal cards were rendering at different widths.** The `.reveal-container--duel` class I added in rc36 inherited `align-items: center` from the base `.reveal-container`, which in a column flex lets each card size to its content. So the artist-reveal card read narrower than the fun-fact card, and the standings card shorter than both. Added a `--duel` rule mirroring the `--compact` variant (`align-items: stretch`, matching padding/gap), so every card-section on the reveal screen now has the same width.
- **Gameplay submission tracker was rendering 40px avatar circles instead of tiny dots.** `renderSubmissionTracker` emits a nested `.player-avatar` inside each `.player-indicator`, and my earlier arcade CSS hid `.player-name` + `.player-badge` but not `.player-avatar`. The legacy avatar sizing leaked through. Now `.arc-submission-dots .player-indicator > *` collapses every child so the parent is the sole 12px dot.
- **Submission strip no longer crowds the in-game leaderboard.** Removed `margin-top: auto` that was trying to push the strip to the bottom — with the leaderboard + admin control bar sitting below, it was forcing a weird gap. Strip now flows naturally below the bet/submit actions.

### Changed
- **Artist / movie challenge now reads as a "quiz card".** The `.arc-tiles` section gained a subtle cyan-tinted gradient background + thin cyan border + inner glow, so the challenge feels like a distinct element rather than tiles floating on the page background. The 3D tile buttons still pop because they have their own drop-shadow on top.

### For contributors
- 4 CSS rule additions/edits in `styles.css`; no JS, no HTML, no i18n changes. Regenerated `styles.min.css`. Bumped manifest + sw.js CACHE_VERSION + `?v=` cache-busters to rc39.

## [3.2.0-rc38] - 2026-04-19

### Changed
- **Hide the outer Beatify header on the learning-mode screens.** The post-QR onboarding tour and the transitional Ready screen have their own branding inside each view (step-progress header on the tour cards, massive wordmark hero on the Ready screen). The outer \`.player-header\` with its small wordmark was double-stacking on top, making the tour feel cramped and the Ready screen's hero wordmark fight the tiny one above it. `showView()` now toggles `body.is-learning-screen` when either `#tour-view` or `#ready-view` is active; a single CSS rule hides `.player-header` while that class is set. Lobby, game, reveal, and end screens are unaffected.

### For contributors
- 1-line behavior change in `player-utils.js`'s `showView()` plus a 1-rule CSS addition. No JS API changes.
- Connection indicator (inside `.player-header`) is also hidden on the tour/ready screens — acceptable because the tour is client-side-only until the final `player_onboarded` WebSocket message, and if that fails the existing reconnect flow lifts `showConnectionLostView` regardless of the indicator.
- Regenerated `player.bundle.min.js` (87.4 KB). Bumped manifest, sw.js `CACHE_VERSION`, and `?v=` cache-busters → `beatify-v3.2.0-rc38`.

## [3.2.0-rc37] - 2026-04-19

### Changed
- **Gameplay screen redesigned arcade-style (Variant D).** The active-round view swaps from a vertical stack of card-sections (sticky header · album · submission tracker · artist challenge · movie challenge · year selector · leaderboard) to a Kahoot/Jackbox-style layout with the year-guess as the hero. New top-to-bottom order: a three-up arcade header (pulse-orb album · Round N of M · neon timer circle) · optional chip row (steal unlocked · closest-wins · intro · final) · massive 128px year number (clamps down on narrow phones) · compact slider row with round − / + buttons · artist/movie challenges as 2×2 tappable tiles with drop-shadow 3D feel · optional "No bonus this round — nail the year" dashed filler · bet (compact) + submit (gradient pink 3D button) in a bottom row · full-width steal button when unlocked · submission dots at the very bottom.
- **Submit flow now transforms the screen instead of hiding buttons.** After a player submits, the year turns green (`year-xxl--locked`), the slider locks (55% opacity + green thumb), a green "✓ Locked in · waiting for N more" banner appears above the duel, the bet button freezes on its current state, and the submit button morphs into a ghost "Waiting for others" with a cyan pulse dot. Everything stays visible — no layout reflow, no mystery disappearances.
- **Timer turns red + pulses at ≤ 10 seconds.** The neon circle flips from pink to red with an 0.8s scale pulse (honors `prefers-reduced-motion`). Old digit-level timer-critical classes retained for compatibility.
- **All chip-row badges collapse to a single row** above the year. Wrapper auto-hides when every chip is hidden — no empty margin band on default rounds.
- **No-bonus rounds get a copy nudge** — dashed "🎵 No bonus this round — nail the year" filler preserves layout height and gives the empty space a purpose.

### For contributors
- `player.html` reveal section rewritten in place. Preserved IDs so existing JS paths continue to work: `album-cover`, `current-round`, `total-rounds`, `timer`, `year-slider`, `year-decrement`, `year-increment`, `selected-year`, `bet-toggle` (with `bet-icon` + `bet-label` children), `submit-btn`, `steal-btn`, `submitted-confirmation` (kept as a hidden residual node), `artist-options`, `artist-challenge-container`, `movie-options`, `movie-challenge-container`, `submission-tracker`, `submitted-players`, `intro-badge`, `closest-wins-badge`, `last-round-banner`, `steal-indicator`, `game-difficulty-badge`, `game-leaderboard`, `intro-splash`. New IDs: `arc-pulse-orb`, `timer-neon`, `arc-chip-row`, `year-display-arc`, `submitted-banner`, `submitted-banner-text`, `no-bonus-filler`, `arc-submission-count`.
- `player-game.js`: `updateGameView` now calls two new helpers — `syncArcChipRow()` (hides the chip-row wrapper when every child chip is hidden) and `syncNoBonusFiller(data)` (shows the filler when neither challenge is active). `renderSubmissionTracker` now populates `#arc-submission-count` with "N of M submitted" / "All in" and updates the submitted-banner text with the remaining count. `handleSubmitAck` + `resetSubmissionState` extended to toggle `.year-xxl--locked`, `.slider-arcade--locked`, `.submit-arc--waiting`, the submitted banner, and the bet button's disabled state. `startCountdown` toggles `.timer-neon--warn` at ≤ 10s. `showStealUI` / `hideStealUI` both call `syncArcChipRow` so the wrapper tracks steal state live.
- `styles.css` (+~460 lines) — namespaced `.arc-header`, `.arc-pulse-orb`, `.arc-round-center`, `.timer-neon`, `.arc-chip-row`, `.arc-chip--*`, `.year-xxl`, `.submitted-banner`, `.slider-arcade*`, `.slider-btn-year`, `.year-slider-arcade` (with `::-webkit-slider-thumb` + `::-moz-range-thumb`), `.arc-tiles`, `.arc-tiles-grid`, `.bonus-filler`, `.arc-actions`, `.bet-arc`, `.submit-arc`, `.steal-btn-full`, `.arc-submission-strip`. All motion gated by `prefers-reduced-motion: reduce`. Existing `.artist-option-btn` / `.movie-option-btn` classes are restyled inside `.arc-tiles-grid` so the JS that emits those elements keeps working unchanged.
- i18n: new keys `game.betShort`, `game.noBonusThisRound`, `game.lockedIn`, `game.lockedInWaitingCount`, `game.lockedInAllSubmitted`, `game.waitingForOthers`, `game.allSubmitted` across all 5 locales.
- Regenerated `player.bundle.min.js` (87.3 KB). Bumped manifest, sw.js `CACHE_VERSION`, and `?v=` cache-busters → `beatify-v3.2.0-rc37`. All 24 Vitest tests pass · all 5 locale JSONs valid · build clean.
- Design spec: `~/.gstack/projects/mholzi-beatify/designs/gameplay-20260419/preview-d-full.html` — 4 states covered (active · submitted-waiting · steal modal · no-bonus+urgency). Open questions from the spec left open: full-width vs. compact steal button (chose full-width as spec recommends); movie+artist-both-active — stacked as two separate tile grids (arc-tiles sections are independent); intro round splash unchanged.

## [3.2.0-rc36] - 2026-04-19

### Changed
- **Round-reveal screen redesigned around the Guess Duel.** The old stack of card-sections (song hero, year-was, personal result, all guesses, leaderboard, round analytics) is replaced by a cleaner hierarchy: compact song strip at top, optional chip row (bet / streak / other mode indicators), the duel itself (your guess × gap-count × correct year, with the emotion label above), a single "You earned · +N pts" score row, then the conditional cards (artist challenge · movie challenge · fun fact) and a compact standings list. The emotional peak is the duel — your number next to the correct number, separated by the "× N years" delta. Same data as before, but told as a comparison instead of a report.
- **Full points breakdown moved into a bottom-sheet popup.** The main screen shows only the final number (e.g. `+120`). Tap the ⓘ beside it and a sheet slides up with base score, speed bonus, streak bonus, artist/movie/intro bonuses, the bet multiplier, and the total. Keeps the main screen clean; preserves every data point for players who want the math.
- **Round analytics moved into a second bottom-sheet popup.** Song difficulty (stars + "only N% guess it right"), avg guess, closest player, fastest submit time, play-count across all Beatify games, and furthest-off list. Opened by the ⓘ in the header next to the difficulty badge. The section no longer occupies vertical space on the main screen unless the player asks for it.
- **Bottom sheets use a reusable component** — slide-up animation, swipe-handle, ✕ close button, tap-outside-to-dismiss, Escape-to-close. Animation honors `prefers-reduced-motion: reduce`. Standards-compliant `role="dialog" aria-modal="true"` + focus moves to the close button on open.

### For contributors
- `player-reveal.js`: added `renderDuel`, `renderChipRow`, `renderScoreRow`, `renderPointsBreakdown`, `renderRoundStatsSheet`, `computeTotalPoints`, plus `setupRevealSheets` (exported, wired once from `initAll` in `player-core.js`). `updateRevealView` now stashes context on `state.lastRevealContext` so the sheets can lazily render when opened. The old `renderPersonalResult` and `renderPlayerResultCards` are no longer called for the reveal view (left in the file for potential reuse; can be removed once confirmed no other code path hits them).
- `showRevealEmotion` now detects the new `.duel-emotion` element and writes just the main phrase (no subtitle) — the duel's gap number already communicates "N years off" so the subtitle is redundant. Falls back to the legacy two-line rendering if the element keeps the old class.
- `player.html`: reveal-view rewritten. New elements: `#duel-your-year`, `#duel-gap-count`, `#duel-gap-unit`, `#reveal-chip-row`, `#reveal-total-pts`, `#score-row-subtitle`, `#points-breakdown-btn`, `#round-stats-btn`. Two new bottom-sheet modals at the body tail: `#points-breakdown-sheet` and `#round-stats-sheet`. Legacy `#song-difficulty`, `#round-analytics`, `#round-analytics-content`, `#reveal-leaderboard-summary` kept as hidden placeholders so any residual DOM-query in `player-reveal.js` doesn't null-dereference.
- `styles.css`: ~400 lines added under a clear "Round-reveal v2" section. All class names namespaced — `.reveal-header-v2`, `.song-strip*`, `.chip-row`, `.duel*`, `.score-row*`, `.sheet*`, `.breakdown*`, `.stats-grid`, `.stats-card`, `.difficulty-visual`, `.furthest-list`. The legacy `.result-card`, `.personal-result-section`, `.reveal-results-grid`, `.reveal-year-section` styles are still shipped because some are shared with end-view and dashboard views (kept for safety until future grep-and-clean pass).
- i18n: new `reveal.duel.*`, `reveal.chip.*`, `reveal.breakdown.*`, `reveal.stats.*`, plus `reveal.unknownSong` / `reveal.unknownArtist`. 26 new keys × 5 locales. Existing `reveal.emotions.*`, `reveal.exact`, `reveal.yearOff`, `reveal.yearsOff`, `reveal.noSubmission` all reused.
- Regenerated `player.bundle.min.js` (85.7 KB). Bumped manifest, sw.js `CACHE_VERSION`, and `?v=` cache-busters → `beatify-v3.2.0-rc36`.
- Design mockups (4-variant exploration + final Variant B full spec with popups) at `~/.gstack/projects/mholzi-beatify/designs/round-reveal-20260419/`.

## [3.2.0-rc35] - 2026-04-19

### Changed
- **Player lobby now uses the Jackbox-style tile grid.** The "Players in Lobby" section switches from flat chip-style cards to the same tile grid admin's home-view uses (rc27). Each player renders as a square tile with a big initial letter in Outfit 900, name below, colored gradient + neon glow, and a corner marker identifying their role. Host wears the pink "leader" variant with a 👑 crown at top-right; guests cycle cyan → green → orange → dim-cyan in join order so a mixed lobby reads as individual players at a glance; the current player gets a cyan "YOU" chip in the same top-right slot as the crown (they never collide — `is_admin` resolves to crown first, non-host-me resolves to chip, admin-viewing-themselves shows crown only). The 🎮 icon next to "Game Lobby" is gone for a cleaner header. Disconnected players dim to 50% with a small "away" badge pinned at the bottom of the tile. New-join animation survives the pattern change.
- CSS additions are namespaced under `.player-tile`, `.player-tile--c2/c3/c4/host`, `.player-tile-initial`, `.player-tile-name`, `.player-tile-crown`, `.player-tile-you-chip`, `.player-tile-away` — parallel to admin's `.home-player-tile*` so the two grids stay easy to diff.

### For contributors
- `renderPlayerList()` in `player-lobby.js` now pre-computes a `variantMap` (name → `host`/`c1`/`c2`/`c3`/`c4`) from the sorted player list in a single pass, then the per-tile renderer looks up the variant. This keeps the virtual-scrolling API unchanged (single-arg renderer) while preserving join-order color stability.
- The legacy `.player-card` / `.player-cards-grid` / `.you-badge` / `.away-badge` CSS is still shipped because it's used by `#reveal-results-cards` (All Guesses reveal panel) and the `#reveal-leaderboard-list`. Only the lobby's container class changed (`player-cards-grid` → `player-tiles-grid`).
- Regenerated `player.bundle.min.js` (86.5 KB) and `styles.min.css`. Bumped manifest, sw.js `CACHE_VERSION`, and `?v=` cache-busters → `beatify-v3.2.0-rc35`.
- Mockup + 3-variant iteration preserved at `~/.gstack/projects/mholzi-beatify/designs/player-lobby-tiles-20260419/preview.html`.

## [3.2.0-rc34] - 2026-04-19

### Fixed
- **"End" button stuck showing "ENDING…" after a rematch.** The initial game ended fine, but after clicking Rematch and playing a second round, tapping End changed the label to "ENDING…" and froze — the button was actually disabled from the previous game's end action. Root cause: `handleEndGame()` disables the button and swaps its label on click, but `updateControlBarState()` (which runs on every phase transition) only reset the Stop and Next buttons, never the End button. So the stale `disabled=true` + "ENDING…" label persisted across `hideAdminControlBar()` → rematch → `showAdminControlBar()`, and the next click bounced off a dead button. Now `updateControlBarState` also resets `end-game-btn` on any PLAYING or REVEAL transition — every new round's admin bar starts with a clickable End button under its proper `admin.end` label.

## [3.2.0-rc33] - 2026-04-19

### Fixed
- **`connectWebSocket(newName)` silently no-ops when a WS is already open under a different name.** The guard in `player-core.js` was blanket — any call with a live WS returned early. That meant if a user's session was restored via cookie and they later tried to rejoin under a new name (happens in admin-handoff and leave-then-rejoin flows), the client flipped `state.playerName` locally but never sent a `join` to the server. The server kept the old identity forever, and the player was invisible to themselves in the lobby. Now the guard is smarter: same-name call still no-ops (correct), but a different-name call sends `leave` (for non-admin), closes the old WS, clears the session cookie, and opens a fresh connection with the new name. Admin identity is preserved on close (admin can't `leave`, so we skip that step). Caught during live browser simulation of rc32 onboarding.

## [3.2.0-rc32] - 2026-04-19

### Fixed
- **Player onboarding tour, ready screen, and lobby were rendering on top of each other.** Caught during live browser simulation: after a new player completed the 4-card tour, all three views stacked simultaneously instead of transitioning. Root cause: `tour-view` and `ready-view` weren't in `player-utils.js`'s `allViews` array, so `showView()` didn't add `hidden` to them when switching to another view. They stayed `display: flex` while the lobby also showed. Added both to the array. `showView('lobby-view')` now correctly hides the tour and ready overlays.
- **Tour "Next" button lost its `data-i18n` binding after the first render.** `renderCard()` overwrote the button's `innerHTML` with a plain span. If the admin switched game language mid-tour, the button's label stayed stale because `BeatifyI18n.initPageTranslations()` had nothing to retranslate. The replacement span now carries `data-i18n="onboarding.nextBtn"` (or `onboarding.letsPlay` on the final card) so language changes propagate.
- **`aria-valuenow` on the tour progress bar was static at `1` for the whole tour.** Screen readers announced "Step 1 of 4" through every card. Now updates in `renderProgress()` alongside the step-count text.

### For contributors
- Live browser simulation found one unrelated pre-existing bug worth flagging for a future fix: when a returning player tries to join under a new name after `connectWithSession` already restored their session, `connectWebSocket(newName)` silently returns early (WS guard) so the name change never reaches the server. Out of scope for this fix but tracked.
- Regenerated `player.bundle.min.js` (85.8 KB). Bumped `?v=` cache-busters in `player.html` (JS) and `admin.html`, and SW `CACHE_VERSION` → `beatify-v3.2.0-rc32`. Manifest bumped to rc32 (rc31 shipped with manifest still on rc30 — corrected here).

## [3.2.0-rc31] - 2026-04-19

### Changed
- **Player end-of-game podium redesigned as a hero-winner poster.** The player-screen end view (`player.html` → end-view) no longer uses the generic gold/silver/bronze three-column stands. The #1 player is now the layout: their name rendered at 40–64px (clamped for long names) in Outfit 900 with the pink→cyan wordmark gradient from DESIGN.md, their score in cyan with the brand glow treatment, framed by a pink-bordered hero card with a soft pink-cyan background wash and `0 0 40px rgba(255,45,106,0.18)` glow. #2 and #3 demote to compact chips in a two-column grid below (medal + name + score), so the winner moment actually feels like a moment instead of fighting the rest of the page for attention.
- **"Your Result" card gets a matching pink-leaning gradient treatment** with a 28px pink glow, and the rank number bumps up to `--font-size-4xl` in Outfit 900 for a stronger personal-result read. Stat values (best streak, rounds, bets) switch to Outfit 800 to match the hero type system.
- **DOM is unchanged.** Same `.podium` markup in `player.html:503-522`; the restyle is purely CSS under `body.theme-dark`, so existing JS bindings in `player-end.js` (`#podium-{N}-name`, `#podium-{N}-score`, `.hidden` slot toggling for 1/2-player games) keep working without touching `updateEndView()`. Dashboard.html uses a separate `.dashboard-podium` class and is unaffected.
- **Graceful collapse for short games.** If a 1- or 2-player game hides `.podium-2`, `.podium-3` promotes to the `second` grid area so it doesn't look orphaned on the right.
- Regenerated `styles.min.css` (180.4 KB). Bumped `?v=` cache-buster in `player.html` (1.8.0 → 1.9.0) and SW `CACHE_VERSION` → `beatify-v3.2.0-rc31`.
- Design artifacts (as-is snapshot, 3 explored variants, comparison board, rendered QA) live at `~/.gstack/projects/mholzi-beatify/designs/end-game-podium-20260419/`.

## [3.2.0-rc30] - 2026-04-19

### Added
- **Player onboarding v2 — four-card tour teaches the game before the host starts.** New players who scan the QR code no longer land on a bare lobby with a collapsed "How to Play" accordion most of them ignore. Instead they drop into a swipeable 4-card tour that teaches the core mechanics in the order they'll encounter them: guess the year (slider preview with animated cyan year glow), double-or-nothing bet (shows `12 × 2 = 24` neon-green reward), steal an answer (cyan target picker), guess the artist (2×2 bonus grid matching the in-game component). Each card has explicit Skip + Next buttons, a 4-segment gradient progress header that reuses the admin first-run wizard pattern (`.wiz-progress`), and auto-advances after 4 seconds unless tapped. Final card reads "Let's play →" to mark the transition. See DESIGN.md § "Player onboarding — post-QR education" for the full spec.
- **Ready screen with waiting pulse.** After the tour (or a skip), players see a branded Beatify wordmark + "You're in, {name}!" + animated cyan waiting pulse + live player count meta line ("4 players in lobby · Normal difficulty") for ~1.4s before the lobby takes over. This is the Showtime moment between tour and lobby.
- **"Replay the tour" link in the lobby.** Pink dashed-border button replaces the old collapsed "How to Play" accordion. Re-enters the 4 cards as a no-pressure refresher — no server ping, no re-flag write.
- **Host visibility gate — admins see players still on tour as dashed tiles with a cyan TOUR badge.** Host-side player grid (home-view) renders LEARNING players with a dashed outline, 72% opacity, and a cyan "TOUR" badge in the top-right corner. An amber warning banner above the Start button reads "⚠️ N player(s) still learning the rules". The Start button stays clickable (no hard-disable, per DESIGN.md) but fires a confirm modal — "N player is still learning the rules. Start anyway?" — to prevent accidental starts. Other players never see the TOUR badge on peers; peer pressure lives on the host alone.
- **Server-side `onboarded` flag on `PlayerSession`.** New bool field (defaults to False) that flips True when the client sends `player_onboarded`. Included in the broadcast `players` payload so the host can render LEARNING state in real time. Persists across reconnects and rematches — if you already did the tour, you won't redo it. Client-side localStorage (`beatify_onboarded_v2`) is the authoritative "don't show again" flag for returning players; server is the authoritative host-view signal.
- **New WebSocket message `player_onboarded`.** Idempotent: re-sending for an already-onboarded player is a no-op. Dispatched via the existing `_message_handlers` registry in `websocket.py`; handler in `ws_handlers.py` broadcasts state on flip.
- **i18n keys across all 5 locales.** New `onboarding.*` namespace (26 keys) covers the full tour, ready screen, replay link, warning banner, and confirm modal. Translations hand-written for en / de / es / fr / nl; each caption is ≤8 words to match the DESIGN.md spec.

### Changed
- **The old collapsed "How to Play" accordion in the player lobby is gone.** Replaced by the new tour + "Replay the tour" link. The 4 i18n keys `lobby.howToPlayStep1-4` are kept in place (still shipped in each locale) in case anything else references them, but no UI surface reads them anymore.

### For contributors
- New module: `custom_components/beatify/www/js/player-tour.js` (ES module, imported by `player-core.js`). Exports `shouldShowTour`, `startTour`, `replayTour`, `forceExit`, `setupTour`, `updateReadyCount`, `isActive`. Tour state is module-local; `setupTour()` is wired once from `initAll()`. Returning-player short-circuit: if `localStorage.beatify_onboarded_v2 === '1'` but the server hasn't heard yet, the check function sends `player_onboarded` inline and skips the tour — keeps the two sides in sync.
- Routing change in `player-core.js`: LOBBY phase handler now consults `shouldShowTour(currentPlayer)` before deciding between `tour-view` and `lobby-view`. PLAYING phase handler calls `forceExit()` if the tour was still active when the game started — avoids a dead tour screen when the host starts early.
- `PlayerRegistry.get_players_state()` now includes `onboarded` in the per-player dict. Admin and player clients receive the same list; filtering (admin sees TOUR badges, players don't) is done client-side.
- Styles added at the tail of `styles.css` (~400 lines) — all namespaced under `.tour-*`, `.ready-*`, `.replay-tour-link`, `.home-player-tile--learning`, `.home-player-tile-tour`, `.home-learning-warning`. All animations gated behind `prefers-reduced-motion: reduce`.
- Regenerated `admin.min.js` (71.5 KB), `player.bundle.min.js` (85.6 KB, up from ~83 KB before the tour module), `styles.min.css` (177.1 KB). Bumped `?v=` cache-busters in `player.html` (1.7.0 → 1.8.0 CSS, rc29 → rc30 JS) and `admin.html`, and SW `CACHE_VERSION` → `beatify-v3.2.0-rc30`.
- Design artifacts for the mockup + spec review round live at `~/.gstack/projects/mholzi-beatify/designs/player-onboarding-20260418/preview.html`.

## [3.2.0-rc29] - 2026-04-18

### Fixed
- **Admin redirect to `/play` after Start game asked for the name again.** The identity wasn't handed over — three compounding issues:
  1. **Admin-side cookie couldn't survive HTTPS.** `admin.js` set `beatify_session` with `path=/` and **no `Secure` flag**. Over Nabu Casa's HTTPS tunnel the cookie was silently rejected, and the path differed from `player-core.js`'s `path=/beatify`. Now matches player-core exactly — `path=/beatify; SameSite=Strict; Secure` on HTTPS.
  2. **Fresh name-based join raced with the server's disconnect event.** When `/play` loaded it called `connectWebSocket(name)` which sent a **new** `{type:'join', name, is_admin:true}`. If admin.js's WS disconnect event hadn't been processed server-side yet, [player_registry.add_player:101](custom_components/beatify/game/player_registry.py:101) returned `ERR_NAME_TAKEN` (the existing player was still flagged `connected=True`). Fixed by preferring `connectWithSession()` — which sends `{type:'reconnect', session_id}` and matches the player by session regardless of disconnect timing.
  3. **Session wasn't reliably available on `/play`.** Even with the cookie, timing edges still bit us. `handleSwitchToPlayerView` now also stores the session in `sessionStorage` AND appends it as a `?session=<id>` URL param; `player-core.js initAll` restores the cookie from either source before deciding how to connect.
  Also: gated the auto-redirect at LOBBY → PLAYING on `adminSessionId` being set (not just `adminPlayerName`) so we never redirect before `join_ack` has arrived with the session.

Regenerated `admin.min.js` + `player.bundle.min.js` (was last bundled Apr 18 12:56 — 3 rc's behind). Bumped `?v=` in `admin.html` and `player.html` + SW `CACHE_VERSION` to `beatify-v3.2.0-rc29`.

## [3.2.0-rc28] - 2026-04-18

### Fixed
- **Spiel starten / Start game button did nothing on click.** `startGameplay()` looked up `#start-gameplay-btn` — a legacy lobby button deleted in rc25. The null-check on line 1863 instantly returned, so no WS `start_game` or REST fallback ever fired. Rewired the function to target `#home-start-game` (the actual home-view button) and made the button-state handling tolerant of the button not being present.

### Changed
- **More breathing room above the player tiles.** Added `margin-top: var(--space-lg)` to `.home-players` so the tile grid sits away from the "N playlist requests" pill / meta line above it.

## [3.2.0-rc27] - 2026-04-18

### Changed
- **Home-view player chips → Jackbox-style tile grid.** Chose Option B from the design mockup: each joined player renders as a square color-block tile (initial + name), 84 px min-width in a `repeat(auto-fill, minmax(84px, 1fr))` grid. The host always wears the pink-primary variant with a 👑 crown badge (DESIGN.md "leader highlights"); guests cycle through the brand neon palette in join order — cyan → green (`--color-success-neon`) → orange (`--color-warning-alt`) → dim cyan, then wrap. Each tile gets a gradient background + colored border + matching glow so a mixed lobby reads as individual players at a glance, not an anonymous chip row. Empty state stays as a single dashed full-width pill. Ships with regenerated `admin.min.js` + `styles.min.css`, bumped `?v=` cache-busters in `admin.html`, and SW `CACHE_VERSION` → `beatify-v3.2.0-rc27`.

## [3.2.0-rc26] - 2026-04-18

### Fixed
- **CRITICAL: browsers were still running rc21 JavaScript.** Every release since rc22 (the "Join as player → No active game found" fix, auto-switch to player view, admin chip, Revanche returning to home-view, legacy lobby removal) shipped source-only changes — but three layers conspired to freeze the browser on rc21:
  1. `admin.min.js` hadn't been regenerated since Apr 18 12:56, so the bundle the browser actually loads was pre-rc22. Source-to-minified gap was 4 rc's wide.
  2. `<script src="…admin.min.js?v=3.2.0-rc21">` — the cache-buster query string in `admin.html` hadn't been bumped either, so even after the file changed, browsers kept the cached version.
  3. `sw.js` `CACHE_VERSION = 'beatify-v3.2.0-rc21'` — the service worker was also frozen, serving old assets from its own cache and never invalidating.
  Regenerated `admin.min.js` and `styles.min.css` from current sources, bumped every `?v=` query in `admin.html` to rc26, and bumped `CACHE_VERSION` to `beatify-v3.2.0-rc26`. Users will now actually pick up the rc22-rc25 fixes on their next load.
- **`<strong>` tag rendered literally in the "Request new playlist" note.** `admin.playlistCriteria` embedded raw HTML, but `initPageTranslations()` uses `textContent` so the markup showed as plain text ("&lt;strong&gt;Hinweis:&lt;/strong&gt; …"). Split into `playlistCriteriaLabel` + `playlistCriteriaBody` across de/en/es/fr/nl and wrapped in real `<strong>` + `<span>` elements in `admin.html`.

## [3.2.0-rc25] - 2026-04-18

### Removed
- **Legacy admin lobby dropped.** The pre-rc12 `#lobby-section` + `#existing-game-section` markup and all associated rendering logic have been deleted. After rc24 made the home-view the canonical LOBBY landing for every admin flow (initial creation + Revanche + reload), the legacy section had no reachable call path. Total: ~376 lines removed across `admin.html`, `admin.js`, `styles.css`.
  - `showLobbyView` is now a thin delegate to `BeatifyHome.renderSession` (keeps the WS-disconnect REST-polling fallback so home-view chips stay fresh).
  - Dead functions deleted: `showExistingGameView`, `rejoinGame`.
  - Dead event wiring removed: `#rejoin-game`, `#end-game-existing`, `#start-gameplay-btn`, `#participate-btn`.
  - `setupQRModal()` stopped binding `#admin-qr-container` (gone) and is now called once at init instead of on every LOBBY state push — fixes an incidental leak that attached a new document-level escape listener per WS update.

### Kept
- **Shared with `player.html`:** `.lobby-container`, `.lobby-container--compact`, `.lobby-header-compact`, `.lobby-actions`, `.lobby-actions--sticky`, `.stat-badge-bar`, `.qr-section`, `.qr-section--compact`. These CSS rules stay — they dress the player-page lobby.

## [3.2.0-rc24] - 2026-04-18

### Fixed
- **Revanche landed on the legacy admin lobby instead of the home-view.** The LOBBY → PLAYING transition calls `BeatifyHome.exit()` to drop `home-mode`, but there was no symmetric re-entry when a rematch created a new LOBBY. `showLobbyView`'s home-mode gate therefore failed and rendered `#lobby-section` (the pre-rc12 inline form) instead of the home-view. `handleAdminStateUpdate` now calls `BeatifyHome.enter()` whenever state comes back as LOBBY and `home-mode` isn't set — so Revanche drops the admin back on the QR + player chips, matching the original post-wizard landing. Restart still reopens the wizard (intentional: Restart = fresh incl. new playlist selection).
- **Wizard Step 4 difficulty chips didn't translate.** `DIFFICULTIES` in `wizard.js` pointed its labels at `wizard.step3.easy/normal/hard` — but difficulty is a Step 4 feature and those keys only exist under `wizard.step4` in all 5 locales. Non-English users always saw the English fallbacks ("Easy / Normal / Hard"). One-line fix: `step3` → `step4`.

### Changed
- **"Join as player" CTA oversized.** Vertical padding `md` → `lg`, font-size `base` → `xl` + weight 700, radius `xl`, glow pushed 40 → 48 px at 30% alpha, icon 18 → 26 px with thicker stroke. The single most important action on the home-view now reads as such.

## [3.2.0-rc23] - 2026-04-18

### Changed
- **Admin who joined as player auto-flips to the player UI on PLAYING.** Previously, after "Join as player" → Start game, the admin still saw the admin-playing view (blurred art, countdown, control bar) and had to click "Player View →" to actually play. Now `handleAdminStateUpdate` detects `adminPlayerName` at the LOBBY → PLAYING transition and calls `handleSwitchToPlayerView()` automatically. The admin still retains control via the slim admin-control-bar baked into `player.html`.
- **Home-view player chips made prominent; admin gets pink "leader" treatment.** Chip padding bumped 4/10 → 8/14, font-size `xs` → `base`, border `1px/40%` → `1.5px/55%`, added soft cyan box-shadow. New `.home-player-chip--admin` modifier renders the host with pink primary accent + `--glow-primary` + 👑 (reuses the existing `.admin-badge` pattern). Row gap and max-width bumped to accommodate the bigger chips. Follows DESIGN.md: pink reserved for "leader highlights, primary CTAs".
- **Removed `+10s` and `Lights` buttons from the admin control bar.** The bar now matches `player.html`'s slim variant (Stop / Down / Up / Skip / End). Orphan `adminSeekForward()` handler deleted along with the event wiring.

## [3.2.0-rc22] - 2026-04-18

### Fixed
- **Wizard descriptions didn't translate on language change.** The `_t()` helper in `wizard.js` called `window.BeatifyI18n.translate()` — a method that doesn't exist on the i18n module (it only exports `t()`). So every dynamically-rendered description (game-mode hints on Step 4, difficulty hint, Party Lights desc, TTS announcement desc on Step 5) silently fell through to the English fallback regardless of the selected language. The language-switch handler was already re-rendering; it just couldn't reach the new strings. One-character fix: `translate` → `t`.
- **"Join as player" on home-view could error with "No active game found".** `handleAdminJoin`'s home-mode fast-path required `adminWs.readyState === OPEN`. When the socket was mid-reconnect (fresh load race, transient disconnect), the flow fell through to the legacy `/beatify/play` redirect branch — which errored with `alert("No active game found")` when `currentGame.game_id` was stale, and in the good case navigated away from the home-view (violating the rc18 promise). Now in home-mode we never fall through: if the WS isn't open, we kick `connectAdminWebSocket()`, poll for OPEN (≤5 s), then send the join. On timeout, a clearer `admin.home.wsReconnecting` message replaces the misleading "No active game found" alert. Added the new i18n key across de/en/es/fr/nl.

## [3.2.0-rc21] - 2026-04-18

### Fixed
- **Playing-phase year + fun-fact spoiler for admin-players.** The guard in `showAdminPlayingView` only checked the cached `isPlaying` flag, which is briefly `false` on WS reconnect or before `join_ack` races a `state` broadcast. During that window the admin-only year (`📅 1984`) and fun fact rendered for the current round while the countdown was still ticking. Now the guard also inspects the incoming player list — if anyone is flagged `is_admin`, the spoiler is hidden regardless of the cached flag.
- **Missing `reveal.soClose` i18n key.** The reveal emotion summary ("avg guess within 3 years") rendered the literal key `reveal.soClose` instead of the localized string. Added to all 5 locales: So close! / So knapp! / ¡Muy cerca! / Si près ! / Heel dichtbij!.
- **Version drift in admin footer.** `server/base.py` `_VERSION` was pinned at `3.2.0-rc8` while `manifest.json` advanced to rc20, so the admin footer and HA integration status showed the wrong version. Bumped `_VERSION` alongside the manifest. The `version-bump.yml` workflow still pointed at the old `views.py` path (from before `_VERSION` moved to `base.py`), so future releases drifted silently — workflow updated to target `base.py`.
- **Game-Over podium rendered empty 2nd and 3rd slots** for single-player / two-player games, showing "---" placeholders with medals. Now `player-end.js` toggles `.hidden` on `.podium-place.podium-N` when no player occupies rank `N`.

## [3.2.0-rc20] - 2026-04-18

### Fixed
- **Home-view overlapped the admin-playing UI** after LOBBY → PLAYING transition. `body.home-mode` stayed on and `#home-view` never hid, so the QR + "Waiting for guests…" stacked on top of `#admin-playing-section` + `#admin-control-bar`. Now `handleAdminStateUpdate` calls `BeatifyHome.exit()` for any phase that isn't LOBBY.
- **Start game with zero players was allowed.** Clicking Start game on home-view with an empty player list cheerfully transitioned the server to PLAYING with nobody to answer. Now the click is blocked with a clear prompt (all 5 locales) telling the admin to join or have a guest scan the QR first.

## [3.2.0-rc19] - 2026-04-18

### Changed
- **Join as player button moved above the Back / Start game row.** Now a full-width prominent CTA inside the home-stage column, sitting right above the lower CTA bar. Previously it was wedged into the CTA bar itself; the new placement makes the "join before starting" step unmissable without crowding the back/start chrome.

## [3.2.0-rc18] - 2026-04-18

### Changed
- **Admin stays on home-view after "Join as player"** instead of redirecting to the legacy player lobby. The existing admin WebSocket (already authenticated via `admin_connect`) now sends `{type:'join', name, is_admin:true}` when the admin enters their name in home-mode. The server adds the same socket to `game_state.players`, the state broadcast loops back through `handleAdminStateUpdate` → `showLobbyView` → `BeatifyHome.renderSession`, and the admin's name appears in the home-view player chips without leaving the new UI. Legacy redirect path (#653) is preserved for non-home-view contexts (e.g. rematch).

## [3.2.0-rc17] - 2026-04-18

### Changed
- **Home-view CTA bar reshuffled** around the actual admin flow:
  - **End game is hidden while the LOBBY is live.** Ending a session nobody joined isn't a meaningful admin action; it now only surfaces for PLAYING (and other mid-game phases).
  - **Print QR button removed.** The QR is already tap-to-enlarge; dedicated print felt like noise.
  - **Join as player promoted to the CTA bar** as a primary-style button, shown until the admin has registered. While visible, Start game demotes to a ghost button so the eye lands on Join first. This enforces the correct flow: admins must join before starting.

## [3.2.0-rc16] - 2026-04-18

### Fixed
- **Wizard Step 4 "Ansagesprache" didn't switch the UI language.** Picking Deutsch / Español / Français / Nederlands only updated `chosenLanguage` in wizard state — no call to `BeatifyI18n.setLanguage()`. The UI stayed in English for the rest of the wizard and only actually switched on the next page load. Now the chip click fetches the locale file and re-renders translations immediately.

## [3.2.0-rc15] - 2026-04-18

### Fixed
- **Home-view auto-start was STILL broken after rc13** — verified live against the deployed instance. Three root causes:
  - `startGame()` bailed in home-mode because the legacy `#start-game` button stays `disabled` (nothing in home-mode clicks it to enable). Added a `body.home-mode` bypass so programmatic calls from the home-view don't trip the legacy in-flight guard.
  - `renderPlaylists()` reset `selectedPlaylists = []` on every `loadStatus()` without restoring from `localStorage`. Added a localStorage-restore pass mirroring the existing `STORAGE_LAST_PLAYER` flow in `renderMediaPlayers()`.
  - Wizard Done summary showed "unnamed room" for Sonos speakers whose `entity_id` is `media_player.unnamed_room` but whose `friendly_name` is the real room ("Esszimmer"). Now prefers `friendly_name` from `/api/status` and falls back to the entity-id strip.

## [3.2.0-rc14] - 2026-04-18

### Fixed
- **Static files served with 31-day `Cache-Control: max-age=2678400`** — combined with HACS updates that don't always touch every file, users ended up with `admin.html` pointing at `?v=3.2.0-rcN` while the browser held onto a month-old `admin.min.js` under that same URL. Flipped `cache_headers=False` on the `/beatify/static/` route so the browser revalidates via ETag / Last-Modified on every load and picks up fresh bytes the moment the file on disk changes.

## [3.2.0-rc13] - 2026-04-18

### Added
- **Dynamic difficulty hint on wizard Step 4** — picking Easy / Normal / Hard now shows the exact point distribution under the pills (mirrors `DIFFICULTY_SCORING` in `const.py`). All 5 locales updated.
- **Back button on wizard Done step** — was hidden on Step 6 only; now visible on all steps after Step 1.
- **+ Request new playlist** CTA on wizard Step 3, opens the existing `#request-modal` form (lifted above the wizard overlay via z-index).

### Changed
- **Service line on Done summary** now reads "Apple Music" instead of `apple_music` (looked up from the PROVIDERS array, not a generic underscore-strip).
- **Home-view "Edit setup" relabelled to "Back"** for consistency with the wizard's Back button (Zurück / Atrás / Retour / Terug).
- Removed the duplicate "+ Request new playlist" button from the home-view requests modal footer (single entry-point now lives on wizard Step 3).

### Fixed
- **Home-view auto-start was broken** — `startGame()` bailed out because the legacy `#start-game` button was missing/disabled, and `selectedPlaylists` was never hydrated from the wizard's localStorage. Result: no QR, no join URL, no Cast-to-TV link, no Join-as-player button, and "Spiel starten" was a no-op. New `BeatifyHome.hydrateFromStorage()` bridges `beatify_last_player` + `beatify_game_settings` into the admin globals before auto-creating the LOBBY session.

## [3.2.0-rc12] - 2026-04-18

### Added
- **Home-view is now universal** — every admin load drops you on the Ready-to-host screen. Unconfigured users see a "You haven't set up yet" empty-state with a single full-width **Start setup** CTA that opens the wizard. Configured users see the QR + players as before.
- **End game, Print QR, Join as player** utility buttons on the home-view — all conditional on an active LOBBY session, all delegating to the existing flows.
- **Live QR tap-to-enlarge** on the home-view — reuses the existing `#qr-modal`.
- **My Requests pill + inline modal** on the home-view — visible only when pending requests exist. Tap opens a modal inside home-mode (no navigation away) showing full request info (thumbnail / name / status / relative time / Update button) with a "Request new playlist" CTA that opens the submit form directly.
- **Game modes on wizard Step 4** — Artist Challenge, Intro Mode, Closest Wins toggles with the full explanation from admin. Persists into `beatify_game_settings` the same way admin.js reads it.
- **Party lights mode + WLED presets** on wizard Step 5 — Static / Dynamic / WLED chips, and when WLED is selected, 6 phase-preset inputs (LOBBY / PLAYING / REVEAL / STREAK / COUNTDOWN / END).
- **TTS test announcement** button on wizard Step 5 — sends a sample announcement via the existing `/beatify/api/tts-test` endpoint.
- **Deezer provider** chip on wizard Step 2.

### Changed
- **Edit setup** on home-view now reopens the wizard at Step 1 (not the legacy admin sections). Wizard hydrates from localStorage so previous picks stay preselected.
- **End-of-game "Start New Game"** now routes through the wizard at Step 1.
- Step 3 copy updated to reflect multi-pick: "Pick one or more..."
- `renderRequestsList()` refactored to share a row builder with the home-view modal. Both views render identical info. The legacy section is now null-safe — its eventual deletion is a no-op for the rendering code.

### Fixed
- Removed redundant "Step X of Y" label next to the wizard wordmark (the segmented progress bar already shows position).
- Fixed double Beatify logo on the wizard Done step — big hero wordmark was colliding with the top-bar wordmark.
- Done-screen summary card now renders with proper flex layout, uppercase labels, and correct spacing between label and value (was invalid `<div>` inside `<p>` with no styles).
- Step 1 speaker + Step 3 playlist avatar blocks now contain proper SVG glyphs (were empty gradient squares).

## [3.2.0-rc11] - 2026-04-17

### Added
- **Admin home view** — after finishing the wizard (or returning configured), the admin lands on a branded "Ready to host" screen instead of the raw setup page: cyan eyebrow, big **Beatify party** wordmark, glowing hero card with a QR glyph, meta line confirming playlist + game mode, and an "Edit setup / Start game" CTA bar. The real QR + player list appear after Start game creates the session. Design is Variant A "QR Hero" from the lobby mockup storyboard.
- **Multi-select playlists** on wizard Step 3. Tap to toggle, count badge on Continue, checkmark on selected rows. Persists to `beatify_game_settings.selectedPlaylists` so admin's Playlists section shows all picks.
- **Expandable Lights & Voice detail panels** on wizard Step 5. Toggle on to reveal:
  - **Lights:** checkbox list of your HA lights + intensity chips (Subtle/Medium/Party) — persists to `beatify_party_lights`
  - **Voice:** TTS entity-id input + announcement checkboxes (Game start / Round winner) — persists to `beatify_tts`
- **Speaker + playlist row icons** on wizard Steps 1 and 3 — SVG glyphs render inside the avatar block.

### Fixed
- Double **Beatify** logo on the Done screen — the small top-bar wordmark now hides when the big hero wordmark is visible.

## [3.2.0-rc10] - 2026-04-17

### Changed
- **First-run wizard is now a 5-step flow** (was 3 required + 1 optional). Playlist and game mode are separate steps so each gets proper attention:
  1. Speakers
  2. Music service
  3. Playlist (pick a curated pack)
  4. Game mode (difficulty / time per round / announcement language)
  5. Lights + Voice (optional, capability-gated — 2 cards instead of 4)
- Final screen CTA is now **"Go to lobby"** — lands you on the admin's Start Game button with every choice already populated (no re-selecting).
- Step 1 now shows proper brand casing: **Sonos**, **Music Assistant**, **Alexa** (was the raw lowercase HA platform slug).

### Removed
- OAuth prompt on Step 2 (music service). Beatify never ran its own OAuth flow — authorization happens at the Home Assistant level via Music Assistant or HA's own integrations, so the prompt was misleading. Step 2 is now just a provider pick.
- Dead `.wiz-oauth-status` CSS.

### Fixed
- Wizard choices now persist into `beatify_game_settings` using the exact keys `admin.js` already reads at load time. After finishing the wizard, the admin's speaker / provider / playlist / difficulty / timer / language chips are all pre-selected. The first thing you see is the Start Game button.

## [3.2.0-rc9] - 2026-04-17

### Added
- **First-run wizard** for the admin screen. New users land on a full-screen 3-step onboarding (Speakers → Music service → Playlist) with an optional 4th "level up" step (Party Lights, Voice/TTS, Game tuning) that gates toggles on the HA capabilities that are actually available. Completion shows a live demo preview and a "Start first game" CTA. Documented in `DESIGN.md` under `## Patterns`.
- **`/beatify/api/capabilities`** endpoint — reports whether HA has `light.*` entities and a `tts.*` service registered. Powers the wizard's Step 4 gating.
- **Vitest** for JS unit tests. 17 tests cover the wizard's state machine (resume-at-step, trigger, pill visibility) including private-mode and malformed-JSON edge cases.
- **DESIGN.md** — authoritative design system reference (neon party-show aesthetic, typography, color, spacing, motion, patterns, anti-patterns) with a risk log for deliberate category departures.
- **Wizard localization** — EN + DE + ES + FR + NL.

### Fixed
- `.gitignore` no longer shadows files in `custom_components/beatify/` — the `beatify/` ignore rule was anchored to `/beatify/` at the repo root.

## [3.2.0-rc8] - 2026-04-16

### Fixed
- Launcher now re-opens admin in a popup from desktop browsers. PR #664 over-reached: its iframe detection treated the HA sidebar (which is always iframed on desktop) as a WebView and forced same-tab navigation. Popup-blocked fallback still covers genuinely blocked popups.

## [3.2.0-rc7] - 2026-04-16

### Removed
- **Spotify playlist import feature** removed entirely. Spotify's November 2024 Web API deprecation + 2026 account-level restrictions make the Client-Credentials flow unable to read playlists for new apps — even public user-created ones. Rather than ship a broken feature, the import UI, credentials storage, server endpoints (`/beatify/api/spotify-credentials`, `/import-playlist`, `/edit-playlist`, `/spotify-search`), Python service (`services/spotify_import.py`), and inline playlist editor are all removed. Playlists can still be added manually via JSON in `config/beatify/playlists/`.

## [3.2.0-rc6] - 2026-04-16

### Fixed
- Import now shows a clear error for inaccessible Spotify playlists (private, algorithmic, region-locked) instead of a raw aiohttp 403 stacktrace (#729)
- `_sanitize_error` no longer redacts URL paths — the base64 pattern matched `/v1/playlists/...` because `/` was in the character class (#729)

## [3.2.0-rc5] - 2026-04-16

### Fixed
- Collapsible section headers now use event delegation on `document.body` — robust against duplicate listener attachment and late DOM insertion (#727)

## [3.2.0-rc4] - 2026-04-16

### Fixed
- Spotify Import section header now has toggle aligned right (added `section-summary` placeholder for layout parity)
- Regenerated stale `admin.min.js` — production was missing PR #718 features (progress polling, duplicate handling)
- Bumped cache-busters in `admin.html` from `v=3.0.4` to current version so browsers pull fresh assets (#725)

## [3.2.0-rc3] - 2026-04-16

### Fixed
- Re-enabled Spotify Playlist Import UI in the admin dashboard — the section was hidden by an unterminated HTML comment in `admin.html` (#723)

## [3.2.0-rc2] - 2026-04-16

### Security / hardening
- Rate limiting on Spotify credential, import, and search endpoints (#712)
- Input length limits on credential, import, search, and edit endpoints (#703)
- Credential-scrubbed error responses — no base64 `Authorization` echoes (#690)
- Removed server-side filesystem path from import response (#704)

### Fixed
- **Critical**: Restored `URI_PATTERN_*` constants in `const.py` — removed by mistake in #687, breaking integration load (#688, #719)
- Tightened Spotify URL parsing — hostname validation + exact 22-char ID match (#699, #711)
- Tolerant year parsing — malformed `release_date` no longer crashes imports (#700)
- `MAX_YEAR` is now dynamic (current year + 1); was hardcoded to 2030 (#706)
- `validate_playlist()` now checks for missing title / artist fields (#697)
- Playlist file writes are atomic (tempfile + rename) (#696, applies to import and editor)
- Duplicate-name detection on import; admin is prompted to overwrite (#695)
- Disk-full / permission errors return friendly messages instead of opaque 500 (#710)
- `async_ensure_playlist_directory` no longer runs blocking I/O on the event loop (#717)
- Discovery counts validate URI pattern — no more inflated provider counts (#708)
- Empty playlists excluded from discovery (#716)
- `get_remaining_count()` clamped at 0 (was returning negative values) (#707)
- Zero-playable-song combinations now fail fast with a clear error (#709)
- Odesli 429 rate-limits logged at WARNING instead of silently swallowed (#694)
- Imported tracks now carry both `uri` (legacy) and `uri_spotify` (canonical) (#705)
- `_VERSION` in `server/base.py` now tracks manifest (was stuck at `3.0.4`)

### Performance
- Spotify client-credentials tokens are cached for their lifetime (#691)

### UX
- Playlist import now shows in-flight progress updates (#714)

### Notes
- #689 (`requires_auth = True` on admin endpoints) intentionally not applied — the "Frictionless access per PRD" policy stands. Rate limiting, input length limits, and credential scrubbing reduce the remaining attack surface.

## [2.7.0] - 2026-03-01

### Added
- **PWA support** — Add to Homescreen install prompt on admin screen + explicit install button in header
- **Shareable result cards** — Wordle-style emoji grid on end screen; native share sheet on mobile, card download on desktop
- **Revanche (Rematch)** — Players rematch directly from the end screen without re-scanning QR codes
- **Greatest Metal Songs playlist** — 52 tracks across all major metal subgenres (1970–2020), fully enriched (certifications, awards, streaming URIs)
- **Dutch Top 100 enriched** — fun_facts in 4 languages + alt_artists for *Top 100 Allertijden Nederlandstalig*
- Community playlist subdirectory now scanned and copied to HA playlist dir on startup

### Fixed
- Session cookie preserved on game end (was cleared, breaking Revanche reconnect)
- Admin redirect to /beatify/admin removed from game-end handler (was navigating away before Revanche)
- Start button reset from "Starting..." state when returning to lobby after rematch
- End screen scrolls to top automatically when shown
- Game content hidden behind emoji reaction bar + admin bar on mobile (padding-bottom 80px → 140px)
- Share component hidden when playerName lookup failed in single-player games
- All minified assets regenerated (fixes were invisible in earlier builds due to stale .min files)

### Changed
- 22 playlists · 2,415 songs · 4 music platforms · 4 languages

## [2.4.0] - Unreleased

### Added
- **Tidal streaming support** — Fourth music provider alongside Spotify, Apple Music, and YouTube Music
- **Movie Quiz Bonus** — Guess the movie a song is from for tiered bonus points (5/3/1 by speed)
- **French language** — Fourth UI language (EN, DE, ES, FR)
- **British Invasion & Britpop playlist** — 100 tracks from The Beatles to Blur
- **Summer Party Anthems playlist** — 112 feel-good tracks from 1957-2020
- **Film Buff superlative** — Award for most movie bonus points

### Changed
- All 18 playlists enriched with Tidal URIs (90%+ coverage)
- Total catalog: 18 playlists, 2,008 songs, 4 languages, 4 music platforms

## [2.3.2] - January 2026

### Added
- **Motown & Soul Classics playlist** — 100 tracks
- **Disco & Funk Classics playlist** — 76 tracks with 100% chart data coverage
- **Fiesta Latina 90s playlist** — 50 Latin party anthems

### Changed
- Added artist/title metadata to Movies & Schlager playlists (222 tracks)
- 82 new Apple Music and YouTube Music URIs across Movies and Power Ballads
- New `enrich_playlists.py` script for automated cross-platform URI lookup

## [2.3.0] - January 2026

### Added
- **Tag-based playlist filtering** — Filter by decade, genre, region, mood in Admin UI
- **Pure Pop Punk playlist** — 100 tracks
- **Yacht Rock playlist** — 100 tracks
- **90er Hits playlist** — 32 tracks

### Changed
- 80er Hits expanded from 100 to 125 tracks

## [2.2.0] - January 2026

### Added
- **YouTube Music support** — Third music provider
- **Playlist requests** — Users can request Spotify playlists from the Admin UI
- **80er Hits playlist** — 100 tracks

## [2.1.0] - January 2026

### Added
- **Multi-platform speaker support** — Auto-detection for Music Assistant, Sonos, and Alexa
- **Dynamic music service selector** — Shows only compatible services per speaker
- **Cast device guidance** — Helpful hints for Chromecast/Nest users

### Fixed
- Language selector chips not updating translations
- Music service section visible during gameplay

## [2.0.2] - January 2026

### Fixed
- Artist bonus showing `{points}` placeholder instead of actual value
- Gold badge text unreadable in dark mode
- HA Mobile App popup blocked issue
- README broken anchor link

### Changed
- Async metadata fetch reduces round transition wait from ~2-3s to ~500ms
- Parallel WebSocket broadcasts with debouncing for faster lobby updates
- Reveal screen section reorder: Fun Facts, Artist, Your Result, All Guesses

## [2.0.1] - January 2026

### Fixed
- Early reveal phase transition when playing solo
- `ReferenceError: i18n` in early reveal toast

## [2.0.0] - January 2026

### Added
- **Live emoji reactions** — 5 emojis during REVEAL phase, visible to all players
- **Artist Challenge mode** — +5 points for guessing the artist, alt names supported
- **Early reveal** — Round ends instantly when all players submit
- **One-Hit Wonders playlist** — 98 tracks
- **Kölner Karneval playlist** — 291 tracks

### Changed
- Complete UI redesign: collapsible admin sections, unified lobbies, compact reveal view

## [1.6.0] - January 2026

### Added
- **Live emoji reactions** — React during reveals with floating emojis
- **Collapsible lobby sections** — How to Play and QR code collapse for returning players
- **Sticky Leave Game footer** — Always visible exit button
- **One-Hit Wonders playlist** — 98 tracks
- **Kölner Karneval playlist** — 291 tracks
- Analytics icon in admin header

## [1.5.0] - January 2026

### Added
- **Admin analytics dashboard** — Game stats, trends, playlist rankings, error monitoring
- **Per-song statistics** — Guess rates and difficulty scores
- **Service worker** — Caching for instant repeat visits
- **Music Assistant native playback** — Uses `music_assistant.play_media` service
- **Styled confirmation dialogs** — Replaces browser `confirm()` popups
- **Game settings display** — Rounds and difficulty visible in player lobby

### Changed
- 53% smaller JavaScript bundles
- Lazy loading for leaderboard, virtual scrolling for 15+ players
- Adaptive animation quality based on device capabilities

## [1.4.0] - January 2026

### Added
- **Spanish language support** — Full UI and playlist content
- **German playlist content** — Fun facts and awards for all 370 songs
- **TV Dashboard improvements** — Round stats, fun facts, easier discovery
- **Invite late joiners** — QR popup during gameplay
- **Admin lobby makeover** — Dark theme, real-time player list
- **Late join during REVEAL phase**

### Fixed
- Alexa Spotify playback
- Race condition with translations loading before UI render
- Player count not translating properly

## [1.3.0] - January 2026

### Added
- **Steal power-up** — Build a 3-streak, copy another player's answer (max 1 per game)
- **End-game superlatives** — Speed Demon, Hot Streak, Risk Taker, Clutch Player, Close Calls
- **Song difficulty rating** — 1-4 star ratings based on player accuracy history
- Pre-flight speaker checks and smart retry logic

## [1.2.0] - January 2026

### Added
- **Rich song information** — Chart history, certifications, awards, fun facts on reveals
- **Game statistics** — Performance tracking with all-time averages
- **Confetti celebrations** — Gold bursts for exact guesses, fireworks for winners
- **Mystery mode** — Blurred album covers during guessing
- **Eurovision Winners playlist** — 72 tracks (1956-2025)

## [1.1.0]

### Added
- **Difficulty presets** — Easy, Normal, Hard scoring modes
- **Customizable round timer** — 15s, 30s, or 45s
- **Round analytics** — Guess distribution, accuracy stats, speed champions
