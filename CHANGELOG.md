# Changelog

All notable changes to Beatify are documented here. For detailed release notes, see the individual files in `docs/` or the [Releases page](https://github.com/mholzi/beatify/releases).

## [Unreleased]

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
