# Changelog

All notable changes to Beatify are documented here. For detailed release notes, see the individual files in `docs/` or the [Releases page](https://github.com/mholzi/beatify/releases).

## [Unreleased]

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
