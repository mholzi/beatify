# Changelog

All notable changes to Beatify are documented here. For detailed release notes, see the individual files in `docs/` or the [Releases page](https://github.com/mholzi/beatify/releases).

## [Unreleased]

- Added 70 tracks to Iskelmäklassikot community playlist (#1476).

## [4.1.0-rc9] - 2026-06-13

### Changed
- **Consolidated the user-facing v4.1.0 release notes.** The release notes now cover the whole 4.1.0 line in one place — the Spotlight Stage / Round-Delta / Podium Stage / Broadcast Lower-Third reveal-and-dashboard redesign (rc1–rc8) alongside the Amazon Music provider, the screen-wake / TV-reconnect / login-loop reliability pass, the storefront-aware Apple Music fix, the Title & Artist polish (including the "Name the Song" start fix), and the security pass. This is the release candidate for stable 4.1.0; no functional code change since rc8.

## [4.1.0-rc8] - 2026-06-13

### Changed
- **TV dashboard reveal redesigned as "Broadcast Lower-Third" (design-shotgun).** The spectator reveal screen is rebuilt to match the shipped Spotlight/Podium language: a now-revealing card (cinematic cover + title/artist), this-round results, a standings card, and a full-width lower-third band that announces the answer. In year mode the band is the big pink→cyan year hero AND a "🎤 the artist — <winner> +5" chip now surfaces the guess-the-artist mini-game result (it was never shown on the TV before). In "Name the Tune" mode the year hides and the band announces the title + artist with the Crowd Court "close calls decided" verdicts. Element ids are preserved so the existing renderers (leaderboard, top guesses, TA voting, fun fact, difficulty, countdown) keep working; a new `renderDashboardArtistChallenge` adds the year-mode artist result. Scoped under `#dashboard-reveal .reveal-broadcast`.

## [4.1.0-rc7] - 2026-06-13

### Fixed
- **"Name the Song" (Title & Artist) mode no longer starts as a year-guess game.** The wizard saved the chosen mode, but the admin home→start hydration path (`admin.js` `hydrateFromStorage`) copied every game-mode flag from saved settings into `adminState` *except* `titleArtistMode`, so the start payload sent `title_artist_mode: false` and players got the year input instead of the title/artist text fields. The settings→`adminState` mapping is now a single shared helper (`applyStoredGameSettings` in `admin/util.js`) covering all five mode flags, with unit tests — so a new mode flag can't be dropped on this path again.

### Changed
- **Reveal host buttons are now equal-sized.** "Invite Players" and "Next Round" share the same box metrics (width + height); only their colour differs (pink primary vs ghost).

## [4.1.0-rc6] - 2026-06-13

### Changed
- **Reveal artist-result + fun-fact tightened (design-shotgun).** Two tall stacked cards on the year-mode reveal collapse into less scroll. The artist-challenge result no longer gets its own card — it folds into the song-strip card as a slim inline row (🎤 artist + a green "got it" / muted "nobody guessed" chip). The Fun Fact card now leads with the chart/cert/award badges as prominent tiles (📊 / 💿 / 🏆) and demotes the prose to a trimmed two-line hook, so it reads at a glance before auto-advance instead of as a wall of text. HTML + `#reveal-view`-scoped CSS only; `renderArtistReveal` is unchanged (same element ids, relocated).

## [4.1.0-rc5] - 2026-06-13

### Changed
- **TV dashboard game-over screen redesigned as "Podium Stage" (design-shotgun).** Removed the "Share Results" emoji-grid card (sharing is a player-phone action, not a shared-TV one) and rebuilt the end screen as a one-glance broadcast finale: a gradient "GAME OVER" header with a rounds/players meta line, a three-column stage — full standings (places 4+, with the in-game leaderboard scroll-box override so everyone shows) · a crowned gold winner podium with player-coloured avatars · a **Game Highlights reel** — and a superlatives award row across the bottom. The highlights data (Issue #75: exact-year calls, streaks, photo-finishes, heartbreakers) was always sent by the server but never rendered on the TV; it now drives the reel, localised. The stats-comparison ("vs all-time average") survives as a slim header pill. All scoped under `.end-stage-layout` so the in-game leaderboard and reveal are untouched.

## [4.1.0-rc4] - 2026-06-13

### Changed
- **Reveal standings redesigned as a "Round-Delta Ledger" (design-shotgun).** The reveal's Standings card no longer shows a plain rank · name · total list. Each row now fuses the overall standing with the round outcome: rank + movement arrow (▲/▼/–), a player-coloured avatar, the player's name with a "YOU" tag, their guessed year and accuracy ("1985 · 3 off", or "Exact!" in green), event chips (🔥 streak, 🥷/🎯 steal, 🎲 bet), and a big cumulative total with this round's +delta beneath it in neon green. Standing-first emphasis; lower ranks taper-dim; the current player's row is pink-rimmed; everyone is shown (no scroll box). A reveal-scoped `renderRevealStandings()` + `.rstand-*` styles replace the shared leaderboard renderer for the reveal surface only — the in-game leaderboard and TV dashboard are untouched.

## [4.1.0-rc3] - 2026-06-13

### Fixed
- **Spotlight Stage reveal: removed the large empty gap below the year cards.** The rc1 skin's "lift content above the backdrop" rule (`#reveal-view .reveal-container--duel > *`) also matched the full-screen confetti `<canvas>`, overriding its `position: fixed` to `relative` — so the canvas dropped into normal flow and added ~180px of empty space between the duel and the score card. The rule now excludes `.confetti-canvas`, so the score card sits directly below the year cards again.

## [4.1.0-rc2] - 2026-06-13

### Fixed
- **Spotlight Stage reveal: no more bright album-art band below the year cards.** The album-art backdrop was capped in height but scaled and blurred, so its tail poked out below the scrim as a hard, brightly-coloured band under the duel cards (yellow for a yellow cover, etc.). The backdrop now fades to transparent via a mask before its box ends and is toned down (lower opacity), so the glow dissolves cleanly into the dark stage as intended.
- **Hide the big Beatify wordmark during active play.** The 72px header wordmark is redundant chrome on the guessing round and the reveal — it just ate vertical space above the game cards. It's now hidden on `game-view` and `reveal-view` (via a `body.is-ingame` toggle in `showView`, mirroring the existing `is-learning-screen` pattern); branding stays on the join / lobby / end screens.

## [4.1.0-rc1] - 2026-06-13

### Headline
- **"Spotlight Stage" player reveal redesign.** The every-round reveal screen on the player's phone is reskinned end to end: the song's album art, blurred, sits behind the top of the screen as a stage (with a synthetic-gradient fallback when the art URL is missing or expired), content floats on frosted-glass panels, and the year duel is now two facing tickets — your guess in pink, the truth in glowing cyan — bridged by a colour-coded delta pill. Points read in neon green per the design system, and the Title & Artist voting state inherits the same glass treatment. Built in `player.html` + a `#reveal-view`-scoped skin in `styles.css` so the shared `.card-section`/`.chip`/`.leaderboard-list` classes on other surfaces stay untouched; `player-reveal.js` feeds the real album art into the backdrop. Direction approved via `/design-shotgun`.

### Fixed
- **Asset cache-buster no longer depends on a hand-edited version (#1266).** Static assets were busted by a version string hardcoded in `admin/analytics/dashboard/player` HTML and `sw.js`, so a reused or forgotten bump left the marker identical and browsers / the service worker kept serving stale CSS/JS/i18n (the #824 class). The `?v=` params, the SW `CACHE_VERSION`, and the i18n-JSON fetch now derive from a fingerprint of the `www/css|js|i18n` files, so any asset change invalidates caches automatically. The displayed version stays the clean semantic version; the manifest remains the single source of truth.
- Regenerated a stale `admin.min.js` left by #1263 — the Amazon Music admin UI changes were in `admin.js` but missing from the served minified bundle.

## [4.0.0] - 2026-06-08

Stable promotion of the v4.0.0-rc1–rc3 line. See [release-notes-v4.0.0.md](release-notes-v4.0.0.md) for the user-facing summary.

### Headline
- **"Title & Artist" guessing mode (#1180, #1229, @jgossen01).** A whole new, standalone way to play: type the song title (+10) and artist (+5) as free text instead of guessing the year, with per-field fuzzy/near-miss scoring and length-scaled typo tolerance. Idea originally raised by @Hendrik0123.
- **Crowd Court reveal (#1180, #1243).** Close calls become a live 30-second community vote — glowing countdown ring, 👍/👎 tally, persistent voted state, host Accept/Reject override, and full TV standings with verdict chips.
- **Mode-specific end-of-game awards (#1180).** Title & Artist games hand out 💯 Perfect Pair, 🧠 Name Dropper, 🎤 Artist Whisperer, and 🤏 So Close — across all 5 locales.

### Added
- Wizard Step 4 redesign — pick the game mode up front with two mode cards; dependent options react live (#1180).
- Title & Artist runs alongside Movie Quiz and Intro Mode; their points stack (#1180).
- Player onboarding tour gains a "Name that tune" card; tour card count derived from the DOM (#1180).

### Fixed
- **Stale album art on the dashboard and in-game view (#1260, @Dtrieb).** `entity_picture` lags `media_content_id`/`media_title` on Spotify and Music Assistant; `wait_for_metadata_update` now uses a two-phase wait with a transient-flicker guard, with full unit coverage.
- Title & Artist vote countdown is now server-authoritative; flat-wrong guesses no longer trigger a vote; mode/difficulty/bonus preferences are preserved through the wizard (#1180).
- Admin button styles aligned to design-system tokens (#1254).
- CI pins ruff to a fixed version so a formatter update can't turn `main` red on its own.

### Data
- Release-year corrections for EMF, Jürgen Drews, Modern Talking, two *Anastasia* songs, and Höhner (#1237–#1241, #1255).
- Wrong YouTube Music URI repaired in motown-soul-classics (#1264).

## [4.0.0-rc3] - 2026-06-08

### Fixed
- **Dashboard and in-game view showed the previous song's album art.** `entity_picture` lags `media_content_id`/`media_title` on Spotify and Music Assistant, so the cover was read at the moment the track matched and the prior song's art was broadcast. `wait_for_metadata_update` now uses a two-phase wait — confirm the song started, then wait briefly for `entity_picture` to also change — with a guard that ignores a transient `None`/placeholder flicker during the transition. Added full unit coverage for the method (#1260).

## [4.0.0-rc2] - 2026-06-07

### Added
- **Title & Artist mode gets its own end-of-game awards.** Four superlatives that only the song-naming mode can earn: **💯 Perfect Pair** (most rounds with both title *and* artist right), **🧠 Name Dropper** (most exact title hits), **🎤 Artist Whisperer** (most artists named — finally rewards the player who's great at artists, since artist correctness doesn't drive the streak), and **🤏 So Close** (most debated near-misses). They take the slots the year-mode awards (Speed Demon, Risk Taker, Close Calls) structurally can't earn in this mode, so the awards screen finally fits the game being played. Across all 5 locales (#1180).

### Fixed
- **CI now pins ruff to a fixed version.** The lint workflow installed ruff unpinned, so a newer release reformatted previously-clean files and left `main` red on `ruff format --check`. Pinned `ruff==0.15.7` so local and CI agree (#1257).

## [4.0.0-rc1] - 2026-06-07

### Added
- **"Title & Artist" guessing mode — a whole new way to play.** A new game mode where players type the song title and artist as free text instead of guessing the year. Per-field exact / fuzzy / near-miss scoring with Levenshtein matching, 👍/👎 peer voting on near-misses, a host Accept/Reject override, a 30s reveal countdown, and full TV standings — across all 5 locales (#1180, #1229).
- **Wizard Step 4 redesign — pick the game mode up front.** The host wizard's "How do you want to play?" step now leads with two **mode cards** (📅 Year mode · ✍️ Title & Artist) instead of burying Title & Artist at the bottom of the bonus toggles. Dependent options react live: the year-distance **difficulty** picker shows only in Year mode and is replaced by a fixed "Title 10 · Artist 5 · Partial 5/3" scoring summary in Title & Artist mode, and the incompatible bonuses (Artist Challenge, Closest Wins) are hidden. The standalone admin settings panel gets the same behaviour, and the wizard's "Ready to play" summary now names the chosen mode (#1180).
- **Title & Artist now runs alongside Movie Quiz and Intro Mode.** These two bonuses are compatible with the mode — a soundtrack round can still ask for the movie, an intro round can still play a shortened clip — and their points stack with the title/artist score. Only the year-distance modes (Artist Challenge, Closest Wins) remain mutually exclusive with it (supersedes the earlier "all year-round bonuses hide" behaviour) (#1180).
- **Title & Artist: your reveal now has a verdict moment.** The player reveal leads with how you did — **"Nailed it!"** (both right, green glow), **"Got one!"** (half), or **"Not this time"** — instead of just two status pills. While the room is still voting on your close call it reads **"Awaiting the room's verdict…"** rather than prematurely calling it a miss (#1180).
- **Title & Artist: the whole room can watch the vote on the TV.** While a close call is being decided, the spectator screen now shows the live community vote — each near-miss guess with its running 👍/👎 tally and a countdown — instead of a static "Voting…" line. The TV is read-only (everyone votes on their phones); when the window closes it shows the verdict chips (#1180).
- **Title & Artist close calls now show their verdict.** When the near-miss vote closes, the reveal shows each close call as **accepted ✓ +points** or **rejected ✗** with its final 👍/👎 tally — on the player screen as outcome cards and on the TV as verdict chips the whole room can read. Previously accepted near-misses just vanished and the score ticked up silently (#1180).
- **Player onboarding tour: "Name that tune" card.** A fifth card in the first-join tour introduces Title & Artist mode — shows a mock title/artist input with "Bohemian Rhapsody / Queen" as the example and explains the community vote mechanic. The tour's card count is now derived from the DOM so future cards need no JS constant change (#1180).

### Fixed
- **Title & Artist mode chosen in the wizard wasn't applied at game start.** The wizard saved the mode to local storage, but the admin read its game settings only once at page load and refreshed game *status* (not *settings*) when the wizard closed — so start-game sent `title_artist_mode: false` and the round ran in normal (year) mode. The admin now re-reads its settings on wizard completion, so every wizard choice (mode, difficulty, bonuses, language, playlists) takes effect (#1180).
- **Enabling Title & Artist no longer wipes saved Artist-Challenge / Closest-Wins preferences.** The wizard's mode toggle was zeroing those flags in storage, so a host who had them on lost them after a Title & Artist round. The flags now stay the host's source of truth and are suppressed only when building the start-game payload, matching the admin-panel contract (#1180).
- **Title & Artist rounds no longer show year-only chrome.** The player view dropped the leftover "Normal" difficulty badge and the "No bonus this round — nail the year" filler, neither of which makes sense when there's no year to guess (#1180).
- **Title & Artist input boxes are properly styled.** The two free-text fields shipped with no CSS and rendered as ragged browser-default inputs; they now sit in a themed card (label above a full-width input, points pill, focus glow) consistent with the movie/artist bonus cards (#1180).
- **Title & Artist: the vote countdown is now server-authoritative.** The reveal ring counted down by comparing the player's device clock to the server's start time, so a skewed phone clock or a late join could show the wrong number. The server now publishes the exact seconds remaining and the client ticks from that, re-syncing on every update (#1180).
- **Title & Artist: a flat-wrong guess no longer triggers a community vote.** Only genuinely-close guesses (sharing a real word, or within half the truth's length in edits) are near-misses; everything else is marked **Wrong** (red), scores 0, and never reaches the vote (#1180).

### Changed
- **Title & Artist: typo tolerance scales with title length.** The fuzzy auto-accept budget grows with the title but stays proportional (never more than ~1 edit per 3 characters): a 5-char title forgives 1 typo, 6-8 chars 2, 9-11 chars 3, 12-19 chars 4, 20+ chars 5. So "Smels Like Ten Sprit" auto-counts for "Smells Like Teen Spirit", while a short title like "Queen" still needs near-exact spelling. Titles under 5 chars require an exact match (#1180).
- **Title & Artist reveal redesigned — "Crowd Court".** On the player screen the near-miss community vote is now the hero of the reveal: the correct answer and your own result collapse into a compact header, and the vote gets large cards with a glowing countdown ring, live 👍/👎 tally bars, and full-width vote buttons. The voting cards previously shipped with no styling at all (#1180).
- **Your near-miss vote now sticks.** After you vote, your choice stays lit with a ✓ and the other option dims, with a "tap to change" hint. The choice now survives the live state re-renders that previously wiped it. Re-voting is still allowed — last vote wins (#1180).
- **Near-miss vote window extended from 15s to 30s.** More time for the room to weigh in on close calls before the round scores (#1180).

## [3.5.0] - 2026-06-06

### Added
- **Reveal: per-player dot-axis.** After each round, the round-stats (ⓘ) sheet shows every player as a dot on a year timeline — who guessed what and the points they earned, with your own dot ringed and the top three medalled (#1178, PR #1184 / #1230).
- **Auto-advance countdown on every screen.** The seconds to the next round now show on the host's Next button, the TV/dashboard view, and the player's phone (#1048, #1185, PR #1231). TV countdown requested by @Dtrieb.
- **Localized TTS voice announcements.** Announcements follow the selected game language (German, Spanish, French, Dutch), forwarded to the engine only when it advertises support, with years/scores spoken as words via `num2words`. English output unchanged (#1225).
- **iconic-movie-songs — new playlist (72 tracks)** with a dedicated movie-quiz mode (#1215, PR #1217).
- **world-cup-anthems — new playlist (26 tracks).** Official FIFA World Cup songs 1962–2026 (#1190, PR #1191).
- **disney-classics grown +69 tracks** (requested by @maxlin1) and **disco-funk-classics +22** (#1165, #1171).
- **README "Play On A TV" section** documenting the dashboard TV display + Lovelace iframe card (#1181, PR #1182).

### Fixed
- **Party lights now fire on game start** for non-Hue / wizard-configured setups (e.g. Govee) — the config is read fresh and sent on start. Light Mode chips (Static / Dynamic / WLED) are selectable again, unreachable lights are hidden from the picker, and the setup copy no longer implies Philips Hue only (reworded in all 5 languages) (#1228).
- **#1122 — screen sleep disconnected players and the admin.** The wake lock is acquired inside the start-game gesture. Reported by @maxlin1 (PR #1207).
- **#1208 — passive iOS dashboard / TV displays fell asleep.** A muted, inline autoplay keep-awake video satisfies iOS's gesture requirement (PR #1216).
- **#1211 — timer and TTS announcements were out of sync.** `tts_pre_round_delay` offsets the round timer so the countdown starts when the music does. Reported by @nixbuongiorno (PR #1212).
- **`<html lang>` now syncs with the active locale**, so Android Chrome stops auto-translating the UI (#1177, PR #1179).
- **No stray next-song after force-ending a game.** `end_game()` cancels the REVEAL auto-advance task synchronously, closing a race on the API / force-reset path (#1012, PR #1233).
- **Catalog data:** broken or wrong provider URIs repaired and release years corrected across world-cup-anthems, disney-classics, anime-openings, 80er-hits, 90er-hits, pure-pop-punk, 2000s-pop-anthems, one-hit-wonders, hitster-100-en-espanol, ballermann-party-hits, harder-styles, trance-classics and edm-anthems.

### Chore
- **Removed dead round-analytics code** (retired renderers + hidden placeholder DOM) after the per-player dot-axis moved to the round-stats sheet (PR #1232).

## [3.4.4] - 2026-05-28

### Added
- **essential-alternative — new community playlist (100 tracks).** 90s/2000s alternative rock (1991–2011), plays on all five providers. Built via the in-app "request a playlist" funnel. Closes #1134 (PR #1145).
- **anime-openings grown 101 → 140 tracks.** 39 new opening/ending themes spanning two decades. Closes #1149 (PR #1156).

### Fixed
- **#1153 — Android Companion still showing "unauthorized" after v3.4.3.** One last login path missed in the v3.4.3 bypass rewrite; v3.4.4 routes it through the same path. Thanks to **@nelbs** for the screenshot the same day v3.4.3 landed (PR #1154).
- **#1159 — Y.M.C.A. by Village People in `greatest-hits-of-all-time`.** Apple Music ID pointed at a "YMCA (Live)" recording that has since 404'd; replaced with the 1978 studio original (`1872720856`), verified in 6 storefront regions (PR #1161).
- **#1162 — "Prelude and Rooftop" by Bernard Herrmann in `movies-100-greatest-themes`.** Apple Music IDs `600474544` + `599988249` returned 404 across all 7 regions; replaced with `1444008064` from the official *Vertigo (Original Motion Picture Soundtrack)* album (PR #1163). Caught by the weekly automated playlist-health-check.
- **#1135 — Axwell /\\ Ingrosso "Sun Is Shining" tagged 2017, should be 2015.** Reported in-game by Simon Herzog (PR #1146).
- **Jennifer Rush "The Power of Love" tagged 1985, should be 1984.** Single came out in West Germany December 1984; the UK 1985 release was the source of the old tag. Reported in-game by Ingo.

### Changed
- **Admin lobby: "N playlists ready · Tap to install" pill removed.** Useful info in the wrong place — playlist requests live in the setup view, not the lobby (PR #1158).

### Chore
- `ruff format` cleanup on `ws_handlers.py` to clear pre-existing main-Lint-Drift (PR #1164).

## [3.4.3-rc15] - 2026-05-25

### Fixed
- **#1131 — "Network error. Please try again." alert on admin → Start game.** `EndGameView` and `StartGameplayView` extended `BeatifyAdminView` and inherited `requires_auth = True`. HA's middleware blocked Companion-bypass requests with a 401 HTML page *before* `is_authorized_http()` could consult the UA+RFC1918 trust signature. `admin.js`'s `response.json()` parsed the HTML, threw, and the catch surfaced `alert('Network error. Please try again.')`. Confirmed by mholzi's rc14 screenshot: home-view with QR (LOBBY created) + the native alert overlay. rc15 sets `requires_auth = False` on both views and calls `is_authorized_http()` at the top of each handler — same pattern `StartGameView` / `ForceResetView` / `RematchView` already use.

### Patch test totals
- 53 / 53 Python `companion_auth` + `game_views` pass.
- No `.min.js` regeneration (Python-only change).

## [3.4.3-rc14] - 2026-05-25

### Fixed
- **Stale rc8 cache-busters caused legacy admin flash on rc11–rc13.** `admin.html`, `player.html`, `dashboard.html`, `analytics.html` all referenced minified JS / CSS with `?v=3.4.3-rc8` — never bumped alongside the manifest / sw cache version since rc8. mholzi's rc13 symptom ("tap join as host → briefly shows legacy flat admin → updates to home-view") was caused by HA Companion's WebView caching `admin.min.js?v=rc8` and serving the pre-#1138 build while the SW eventually activated rc13's cache and triggered a refresh. rc14 bumps all asset references to `?v=3.4.3-rc14` plus the `<meta name="beatify-version">` tags, invalidating every cache layer simultaneously.
- **Default `home-mode` class on `<body>` in admin.html.** Even with fresh JS the legacy `#media-players` / `#playlists` / `#game-settings` sections briefly flashed visible between page render and `BeatifyHome.enter()`. rc14 adds `home-mode` by default so CSS hides them from first paint; `BeatifyHome.enter().add('home-mode')` stays idempotent.

### Patch test totals
- 107 / 107 JS pass
- 40 / 40 Python `companion_auth` pass
- No `.min.js` regeneration (HTML / CSS only).

## [3.4.3-rc13] - 2026-05-25

### Fixed
- **#1131 — `connectAdminWebSocket()` never opened the admin WS on Android Companion.** rc12 fixed `ensureAuthenticated()` but `connectAdminWebSocket()` uses `getAccessToken()` directly with an early `return` on null. In Companion bypass mode no OAuth token exists, so the function `return`ed before `new WebSocket()` ever fired — no WS upgrade hit beatify, no `[WS-Debug] upgrade` log. Confirmed by mholzi's rc12 HA log download: 4× HTTP-bypass `[Companion-Debug] HTTP ... trusted=True` lines, zero `[WS-Debug]` lines. rc13 widens the early-return: only bail when there's no token AND `isCompanionBypassMode()` is false. In bypass mode the admin_connect message ships `ha_token: null`; server-side `_is_ha_authenticated` already treats falsy tokens as the trigger to consult `is_companion_trusted_meta(ws.beatify_request_meta)` for the UA+RFC1918 accept.

### Patch test totals
- 107 / 107 JS pass.
- `admin.min.js` regenerated via `make build` (81.4kb).

## [3.4.3-rc12] - 2026-05-25

### Fixed
- **#1131 — Android Companion "join as host" hung forever after rc10/rc11.** `ensureAuthenticated()` ran OAuth even in Companion bypass mode: `getAccessToken() → null → login() → window.location = /auth/authorize`, which Companion's WebView blocks ("Invalid redirect URI"). The returned promise never resolved and `admin.js:2562` hung before sending the WS join message. `[WS-Debug] join` never logged because the JS hung before the send — confirmed by mholzi's "no WS-Debug entries in the log" report on rc11. iPhone Companion path was unaffected because `isCompanionBypassMode()` returns false there. rc12 short-circuits `ensureAuthenticated()` to `Promise.resolve(null)` when bypass mode is active; callers send `ha_token: null` and server-side `_is_ha_authenticated` already treats falsy tokens as the trigger to consult `is_companion_trusted_meta(ws.beatify_request_meta)` for the UA+RFC1918 accept.

### Patch test totals
- 22 / 22 ha-auth tests pass — new test asserts both the null return AND that `window.location.replace` is NOT called (no OAuth navigation).
- No `.min.js` regeneration (ha-auth.js loaded directly).

## [3.4.3-rc11] - 2026-05-25

Two changes that ride together because they're both prerequisites for unblocking the Android Companion player-join flow on rc10.

### Fixed
- **#1138 — kill the legacy flat admin layout.** `showSetupView()` used to call `setupSections.forEach(removeClass('hidden'))`, leaving returning users (no `LS_WIZARD_STATE`, but `LS_SELECTED_PLAYER` set) staring at the pre-wizard flat layout — Media Players + Music Service chips + Playlists + Game Settings — instead of the polished home-view. `BeatifyWizard.shouldTrigger()` returns false for these users (wizard.js:65), and `BeatifyHome.enter()` only ran on init when there was no current game. Between those two it was very easy to land on the flat UI. rc11 strips the flat-section reveal from `showSetupView()` and routes all four call sites (loadStatus / end-game / unknown-phase / rematch-fallback) through `BeatifyHome.enter()` for the no-game UI. The flat sections stay in the DOM (referenced by event handlers in admin.js that have not been audited yet), but `body.home-mode` keeps them hidden via the existing CSS in `styles.css:9902-9911`.

### Diagnostics
- **`[WS-Debug]` logging across the WebSocket layer (#1131 follow-up).** rc10's HTTP-side OAuth-skip works (admin loads cleanly), but the player-join WebSocket on the same Companion App shows "Reconnecting to game server" forever. rc11 adds `[WS-Debug]` lines for the upgrade (`request.path`, `request.remote`, truncated UA, total connection count), every received message (`type` + `keys`), every disconnect (`ws.closed`, `ws.close_code`), and every `handle_join` (`name`, `is_admin`, `ha_token` presence, game phase, stashed meta, `add_player` result, and `_is_ha_authenticated` outcome on the is_admin path). No behaviour change — only log calls added.

### Patch test totals
- 111 / 111 Python pass (companion_auth + websocket — return values unchanged).
- 106 / 106 JS pass (the `setupSections.forEach` strip is a pure subtraction with no behaviour the existing tests exercised).
- `admin.min.js` regenerated via `make build` (81.4kb).

## [3.4.3-rc10] - 2026-05-25

Fixes the Android Companion bounce-to-launcher / "Invalid redirect URI" bug that rc8 and rc9 did not address (#1131, #1120).

### Fixed
- **Android Companion: 15s wait, then "Invalid redirect URI" (#1131, #1120).** rc8/rc9 only skipped OAuth when the externalApp/externalAppV2 bridge was *missing*. Field data on rc8/rc9 (Logan-80 on his own setup, reproduced locally on Redmi 25028RN03Y / Android 15 with Companion 2026.4.4-full / 21576) showed the bridge IS exposed on recent Companion builds — but its `postMessage` either never replies or replies with a token HA's `async_validate_access_token` rejects. ha-auth.js hit the 10-second bridge timeout, fell through to `login()` which redirected to `/auth/authorize`, and Companion's WebView blocked the redirect with "Invalid redirect URI". Symptom: admin renders for ~15s (bridge wait), then bounces to the IndieAuth error page. rc10: `isCompanionBypassMode()` now returns true unconditionally when the UA matches Android + HA Companion. The bridge is no longer probed for the auth-skip decision. Subsequent API calls reach beatify without a Bearer token; the server-side `companion_auth.py` UA+RFC1918 bypass introduced in rc8 (already merged, no server change needed for rc10) accepts them. Trade-off: Companion builds where the bridge *would* have worked no longer obtain a real Bearer token. Beatify's admin surface does not consume HA per-user identity, so dropping the per-user token has no functional consequence here.

### Patch test totals
- 106 / 106 JS pass (one `isCompanionBypassMode` test inverted to assert the new behaviour).
- 40 / 40 Python pass (server side untouched).
- No `.min.js` regeneration (ha-auth.js is loaded directly, no bundle).

## [3.4.3-rc9] - 2026-05-25

Diagnostic build, **not a fix**. Instruments `companion_auth.py` with INFO-level `[Companion-Debug]` logging at every HTTP and WebSocket trust check so #1131 / #1120 reports can be correlated with the actual User-Agent + remote-IP that reaches the server.

Triggered by Logan-80's 2026-05-25 report that rc8 still fails on his Android Companion. The server-side bypass *should* match Android-Companion UA + RFC1918 remote, but we have no data on what `request.headers["User-Agent"]` actually contains in his build, nor what `request.remote` resolves to — and HA Companion's Production WebView disables `chrome://inspect`, so client-side console logs cannot be retrieved. rc9 makes both visible from HA's standard log surface.

### Diagnostics
- **`is_companion_trusted_request` (HTTP path)** — logs `request.path`, truncated UA (200 chars), `request.remote`, `ua_match`, `ip_match`, `trusted` on every call.
- **`is_companion_trusted_meta` (WS path)** — same fields at WebSocket handshake time.
- **`is_authorized_http`** — logs Bearer-token presence + validity. Distinguishes "no token" / "bearer present but rejected" / "bearer valid" so we know whether requests hit the bypass because OAuth is dead (expected) or because token rotation broke mid-session.

### How to read the logs
Settings → System → Logs → search `[Companion-Debug]`:
- `ua_match=False` → Android Companion UA regex needs widening (see `_ANDROID_RE` / `_HA_APP_RE` in `companion_auth.py`).
- `ip_match=False` → request crosses a reverse proxy; `X-Forwarded-For` handling is missing.
- `trusted=True` but client still bounces → server bypass works, client-side `ha-auth.js` is failing OAuth before reaching the bypassed endpoints.

Each is fixable in rc10 with the data rc9 produces.

### Patch test totals
- 40 / 40 `tests/unit/test_companion_auth.py` pass (return values unchanged — only log calls added).
- No `.min.js` regeneration (Python-only change).

## [3.4.3-rc7] - 2026-05-24

Extends the rc4 iOS Wake-Lock fix (#1122) to the admin and dashboard surfaces. rc4 deliberately scoped the layered fallback to the player surface only (95% of the field-test coverage at the time) and noted "Dashboard and admin still rely on Layer 1; they get the same layered treatment in a follow-up." rc7 is that follow-up. Static code analysis (no iOS device required) confirmed the gap was real: both `admin.js` and `dashboard.js` short-circuit on `if (!('wakeLock' in navigator)) return;` — silent no-op on iOS Companion's WKWebView where `navigator.wakeLock` is undefined.

### Fixed
- **iOS HA Companion — admin and dashboard screens still sleep despite rc4 (#1122).** rc4 added the [NoSleep.js](https://github.com/richtr/NoSleep.js) Layer 2 fallback only to `player-utils.js` + `player.html`. Admin (tablet) and dashboard (always-on TV / monitor) kept the original Layer-1-only wake-lock implementation, which silently no-ops inside HA Companion's WKWebView. If @maxlin1's reported "screen still goes into sleep mode on iOS devices" was the admin or dashboard surface — statistically likely since the player surface was already fixed — rc4 didn't address it. rc7 mirrors the player surface's layered pattern: `navigator.wakeLock.request('screen')` first, NoSleep silent-video fallback when Layer 1 is missing or rejected. Both `admin.html` and `dashboard.html` now load `/beatify/static/js/vendor/no-sleep.min.js` before their main bundle so `window.NoSleep` is in scope.

### Patch test totals
- 101 JS pass (no test changes — wake-lock isn't exercised in unit tests; layered fallback parallels what player-utils.js already does).
- 540 Python pass (unchanged — server-side untouched).
- `admin.min.js` + `dashboard.min.js` regenerated; `grep -c "NoSleep"` confirms 8 / 5 occurrences in the bundles.

## [3.4.3-rc6] - 2026-05-24

Diagnostic + UX iteration after @nelbs reported on rc5 that the admin renders for ~20 s and then bounces (#1120). rc5's auth bridge demonstrably works — the admin rendered, which means the token was retrieved successfully — but the WebSocket `admin_connect` is rejected by HA's `async_validate_access_token`, the recovery cycle exhausts at `MAX_ADMIN_WS_AUTH_RECOVERIES = 2`, and `BeatifyAuth.login()` then navigates back to the launcher. rc6 doesn't blindly guess the root cause; it instruments every layer so rc7 has data.

### Diagnostics
- **Server (`ws_handlers.py:_is_ha_authenticated`)** — warning log on every rejected token with length, prefix (first 12 chars, deterministic JWT header — not secret), and exception class. Distinguishes "no token" / "token decode failed" / "no matching refresh_token" (the suspected case — token is well-formed but HA's auth manager doesn't recognise it).
- **Client (`admin.js:connectAdminWebSocket`)** — log on every `admin_connect` send with token length + prefix + current recovery attempt counter. If `force: true` is honoured by Companion, the prefix should change between successive recovery cycles; if it doesn't, the Companion is silently ignoring the force flag (the H1 hypothesis from the rc5 post-mortem).
- **Client (`ha-auth.js:_setSessionCookieFromCompanion`)** — log on every fresh bridge response with length, prefix, and `expires_in`. Cross-referenced with the WS log shows whether the bridge actually rotates the token.

### UX
- **Visible toast on `MAX_ADMIN_WS_AUTH_RECOVERIES` exhaustion**, before the silent `logout()` + `login()` navigation. Users see "Home Assistant rejected the access token. Re-authenticating…" instead of staring at a frozen admin page that suddenly reloads. Translations follow in rc7 once the underlying token-rejection bug is fixed.

### Patch test totals
- 101 JS pass (no test changes — the new console.log lines flow through existing fixtures).
- 71 Python WS-handler tests pass (added log statements don't alter return values).

## [3.4.3-rc5] - 2026-05-24

Fifth iteration of the v3.4.3 Android Companion fix series (rc1–rc4 all called the wrong native surface and were silently rejected by Companion 2026.4.4 on @Dtrieb's Pixel 7 Pro). rc5 calls the bridges the HA docs actually specify.

### Fixed
- **HA Companion App on Android — admin bounces back to launcher after rc3 (#1114, #1120, @Dtrieb @nelbs).** Three things were wrong at once: (a) rc3 routed auth through `window.externalApp.externalBus({command:"get_external_auth"})`, but `externalBus` is for HA-frontend ↔ native commands like NFC/Matter/navigation — it has no `get_external_auth` command, so native silently dropped the message and JS timed out after 10 s; (b) the legacy fallback used a randomised callback name (`__beatifyAuthCb_<rand>`), but the security fix [GHSA-7jp2-p2fw-mgvf](https://github.com/home-assistant/core/security/advisories/GHSA-7jp2-p2fw-mgvf) (shipped in Companion 2026.4.4) whitelisted the callback to the fixed string `"externalAuthSetToken"` and silently rejects all others; (c) the modern `externalAppV2` bridge (introduced 2026.4.2 alongside the security fix, the recommended path) wasn't checked at all.
- **Fix: ha-auth.js now calls the documented surfaces.** Primary path is `window.externalAppV2.postMessage({type:"getExternalAuth", payload:{callback:"externalAuthSetToken", force:true}})`; fallback for older Companion is `window.externalApp.getExternalAuth(...)` with the same fixed callback name. Both bridges respond by invoking the fixed global `window.externalAuthSetToken(success, payload)`, which rc5 installs as a multiplexed FIFO receiver. The misnamed `externalBus` path is removed entirely. Logs which bridge fired once per session at `[BeatifyAuth] Companion bridge: …` so future Companion-version regressions are diagnosable without DevTools round-trips.

### Patch test totals
- 101 JS pass (96 + 5 new Companion-bridge tests: V2 happy path, V1 happy path, V2→V1 fallback, UA-miss-but-bridge-present detection, no-bridge regression guard)
- 0 Python touched

## [3.4.2] - 2026-05-22

Hot-fix for an Android Companion App regression introduced by the v3.4.0-rc17 launcher rework. iOS Companion was unblocked at the cost of breaking Android Companion. Three reporters in two days confirmed it; v3.4.2 unblocks Android without touching the rest of v3.4.

### Fixed
- **HA Companion App on Android — launcher tap did nothing (#1114).** v3.4.0-rc17 replaced the script-driven `window.open()` with an `<a target="_blank" rel="noopener">` link so iOS WKWebView users could escape the Companion's OAuth interception. On iOS that routes the URL out to Safari and works cleanly; on Android the Companion WebView silently swallowed `target="_blank"` — the click handler fired (toast "Beatify in neuem Tab geöffnet!" appeared), but no tab was ever spawned. Fix: the launcher now detects the Companion Android UA on click and navigates the top frame directly (`window.top.location.href`) instead of relying on the new-tab route. Beatify loads inline in the same Companion view — trade-off: no separate tab, but it actually opens. iOS Companion, desktop iframe, and standalone-browser paths are unchanged.

### Patch test totals
- 538 Python pass (no Python changes since v3.4.1)
- 96 JS pass (no test changes; launcher fix exercised manually across iOS Companion, Android Companion, Brave, Chrome desktop)

## [3.4.1] - 2026-05-22

Re-cut of the v3.4.0 line after the original stable was pulled to fix two regressions found within hours of release. Contains everything in v3.4.0 plus the rc16–rc18 fix series.

### Fixed (since v3.4.0)
- **HA Companion App on iOS — "Invalid redirect URI" on Beatify open (#1096).** Companion App intercepts `/auth/authorize` navigations inside its WKWebView and runs its native auto-login flow with hardcoded values that don't match Beatify's client_id. Fix: launcher now opens Beatify via `<a target="_blank" rel="noopener">` so the URL opens outside the Companion webview (external Safari, Safari View Controller, or Custom Tabs depending on platform). OAuth flow then runs in a clean browser context with no Companion-side interception.
- **REST error responses now expose `data.code` (#1097).** `_json_error` was writing `{error: <code>, message: <text>}` but the frontend reads `data.code` (matching the WebSocket error shape). Mismatch silently killed both the `GAME_IN_LOBBY` seamless-start auto-recovery and the `errors.<CODE>` i18n lookup — non-English locales got the raw English `message` for every REST-side error. Fix emits both `code` and `error` (backwards-compat); added `errors.GAME_IN_LOBBY` translation to en/de/es/fr/nl.

### Patch test totals
- 538 Python pass (+5 for `_json_error` body shape, callback view tests adjusted for the rc18 architecture restore)
- 96 JS pass (+1 net after the rc16-bounce tests retired)

## [3.4.0-rc18] - 2026-05-22

### Fixed
- **Safari auth loop on rc17 — restored the rc15 OAuth architecture (#1096 follow-up).** rc17's `target="_blank"` launcher correctly opens Beatify outside the HA Companion App webview, but rc16's leftover JS-bounce hop (`/beatify/admin?code=...` → ha-auth.js navigates to `/beatify/auth/callback`) tripped Safari 18 in a different way and brought back the pre-rc15 auth loop in external Safari. The bounce was a workaround for HA Companion's interception of `/auth/authorize`; the rc17 launcher already eliminates that by opening externally, so the bounce was both unnecessary and disruptive.
- **Fix: ha-auth.js back to rc15's clean OAuth flow.** `redirect_uri` points directly at `/beatify/auth/callback`, the server-side callback runs the exchange, sets cookies, and 302s to `/beatify/admin?auth_state=…`. No JS-driven mid-flow navigation. The rc16/17 callback-view `redirect_uri` query-param handling reverted along with it. The rc17 launcher (`<a target="_blank">`) is preserved — that's the actual fix for HA Companion App, and it works without any OAuth-side adjustment.

### Net architecture (rc18)
- Launcher: `<a target="_blank">` opens Beatify in external Safari / Safari View Controller / Custom Tabs, outside any HA Companion webview.
- OAuth: `redirect_uri = /beatify/auth/callback` (server-side endpoint); HA login → callback view exchanges over loopback → sets cookies → 302 to admin. No frontend POSTs to auth endpoints (Safari 18 fix preserved). No extra JS bounce (Safari 18 second-order fix preserved).

## [3.4.0-rc17] - 2026-05-22

### Fixed
- **HA Companion App on iOS — "Invalid redirect URI" still appears on rc16 (#1096 follow-up).** rc16's fix (revert `redirect_uri` to the page URL) wasn't enough — the Companion App on iOS intercepts `/auth/authorize` navigations inside its own WKWebView and runs its native auto-login flow with hardcoded values that don't match Beatify's client_id. The fix has to happen one layer earlier: don't let the OAuth flow run inside the Companion App's webview at all.
- **Fix: launcher now uses `<a target="_blank" rel="noopener">` instead of a script-driven `window.open`.** From any webview (HA Companion on iOS / Android), `target="_blank"` opens the URL outside the webview — external Safari, Safari View Controller, or in-app Custom Tabs depending on platform and user settings. Each has its own cookie jar and runs the OAuth flow cleanly with no Companion-side interception. On desktop browsers iframed in the HA panel, the same `target="_blank"` opens a new top-level tab outside the iframe — same effect as the old `window.open` path. Trade-off: we lose the "click again to focus the existing tab" affordance the old launcher had, but the auth fix is the priority.

## [3.4.0-rc16] - 2026-05-22

Walks back v3.4.0 stable to fix two regressions reported within hours of the v3.4.0 release. The v3.4.0 GitHub release has been removed; rc16 ships as the new pre-release while these fixes bake before re-cutting stable.

### Fixed
- **HA Companion App on iOS — "Invalid redirect URI" on Beatify open (#1096, @ludgerbeckmann).** Since v3.4.0, opening Beatify via the HA Companion App on iOS surfaced HA's IndieAuth error page immediately, on both LAN and Nabu Casa. rc15 had changed the OAuth `redirect_uri` from the page URL to the new server-side callback path (`/beatify/auth/callback`), and the Companion App rejects redirect_uris pointing at paths it doesn't recognize as registered panel URLs. rc16 reverts the `redirect_uri` to the page URL (the value the Companion App accepted from rc1 through rc14) and threads the actual server-side exchange via a JS-level top-level navigation step: the page receives `?code=&state=`, ha-auth.js immediately navigates to `/beatify/auth/callback?code=…&state=…&redirect_uri=<page>`, and the callback view uses the threaded `redirect_uri` for the loopback `/auth/token` exchange (RFC 6749 §4.1.3 requires byte-identical redirect_uri values across `/auth/authorize` and `/auth/token`). The Safari 18 fix is preserved end-to-end — the browser still never POSTs to an auth endpoint.
- **REST error responses now expose `data.code` instead of just `data.error` (#1097, @ludgerbeckmann).** Two regressions collapsed into one root cause: `_json_error` in `server/base.py` wrote `{error: <code>, message: <text>}`, but the frontend admin.js reads `data.code` (matching the WebSocket error shape). The mismatch made (a) the `GAME_IN_LOBBY` auto-recovery silently dead — users saw a modal with the raw English message instead of seamless gameplay start — and (b) the `errors.<CODE>` i18n lookup never fire, so German, Spanish, French, and Dutch users got the raw English `message` for every REST-side error. rc16 emits both `code` and `error` (full backwards-compat) so existing code paths light up. New `errors.GAME_IN_LOBBY` translations added to all five locales.

### Tests
- 539 Python pass (+5 new for `_json_error` body shape, +2 for the `redirect_uri` query-param forwarding in `BeatifyAuthCallbackView`).
- 98 JS pass (+2 for the new `?code=` → callback-view bounce path and the rc16 `redirect_uri` shape).

## [3.4.0] - 2026-05-21

Stable promotion of the v3.4.0-rc15 line with one additional fix (#1080 reset-state-persistence, PR #1089). See [release-notes-v3.4.0.md](release-notes-v3.4.0.md) for the user-facing summary.

### Headline
- **Security Gate (#998, PR #1007).** `/beatify/admin` and every WebSocket command behind it now require an authenticated Home Assistant session. Anonymous external access is no longer possible.
- **LLM-Assisted Playlist Generator (#1052, #1057, #1060).** Describe a vibe, get a 40-track candidate list with provider URIs + release years, validated and sanitized. Save locally or submit upstream.
- **REVEAL Auto-Advance countdown (#1048).** v3.3.7's Auto-Advance now shows the countdown on the sticky "Next round" button.

### Added
- TTS-Entity-Dropdown im Setup-Wizard (#1073, PR #1079, @ludgerbeckmann)
- "Ausgewählte Playlists"-Sheet mit Bulk-Remove (#1074, PR #1083, @ludgerbeckmann)

### Fixed
- Reset-State-Persistence — wizard state now clears on Start New Game (#1080, PR #1089, @BK0101xx)
- Year-truncation on narrow phones (#1072, PR #1077, @laberning)
- Tighter game-view so artist tiles land above the fold on mobile (#1076, PR #1084, @laberning)
- Self-healing service worker — upgrades no longer require manual cache clearing (PR #1086)
- Safari 18 OAuth flow — entire token exchange now server-side, cookies for transport (rc12–rc15, PRs #1091–#1094)
- Nabu Casa SniTun token relay — FormData transport (rc8, PR #1078)
- Zombie token detection (rc8/rc9, commit 36f84e93)
- Merge-conflict-markers in admin assets (rc7, PR #1071)
- Playlist Generator modal copy tightened (PR #1065)
- Playlist Hub FAB icon visibility (#1054, PR #1058)

### Data
- Danube Incident release year 1968 → 1969 (PR #1063)
- Alcazar "Crying At the Discoteque" year 2012 → 2000 (PR #1070)

## [3.4.0-rc15] - 2026-05-21

### Fixed
- **Safari 18 login loop — OAuth flow rewritten server-side (#998 follow-up to rc11–rc14).** Four RCs of frontend transport workarounds (rc11 self-heal, rc12 urlencoded fetch, rc13 XHR, rc14 server-side proxy still POSTed from the browser) all failed because Safari 18 silently refuses certain same-origin POSTs from the OAuth-callback page state — fetch (FormData and urlencoded), XHR, /auth/token and /beatify/auth/exchange were all rejected with `TypeError: Load failed` or `access control checks` errors. Confirmed even in a fresh Safari window outside the HA panel iframe. Chrome and other engines unaffected.
- **Fix: the frontend no longer POSTs to any auth endpoint.** Two new server-side views handle the entire OAuth lifecycle:
  - `BeatifyAuthCallbackView` at `/beatify/auth/callback` is the new `redirect_uri`. The browser arrives here via `/auth/authorize`'s 302; the view exchanges the code with HA's `/auth/token` over loopback HTTP, sets two cookies (`beatify_access` JS-readable JSON with `{access_token, expires_at}`; `beatify_refresh` HttpOnly with the refresh_token, scoped Path=/beatify, SameSite=Lax, Secure when the page was loaded over HTTPS — Nabu Casa included), and 302s back to `/beatify/admin?auth_state=…` for the frontend to CSRF-validate.
  - `BeatifyAuthRefreshView` at `/beatify/auth/refresh` is a GET endpoint that reads the HttpOnly refresh cookie, performs the refresh-token grant over loopback, reissues the access cookie, and returns JSON for ha-auth.js to use immediately. The HttpOnly refresh cookie is never exposed to JS, even on the refresh path.
- **`ha-auth.js` rewritten for cookies.** All transport-fallback code from rc12/rc13 (FormData → urlencoded → XHR) is gone. One transport: read the access cookie at init; on miss, fetch GET the refresh endpoint. `login()` redirect_uri now points at the callback view. Legacy localStorage keys from rc11–rc14 are wiped on init for users upgrading mid-stream.
- **Tests: 532 Python + 96 JS pass.** 7 new tests for `BeatifyAuthCallbackView` (HTTP/HTTPS loopback URL, success path with cookie shape assertions including HttpOnly + Path=/beatify + Secure derived from `X-Forwarded-Proto`, missing-code redirect, HA-rejection redirect, loopback connection-failure redirect). 5 new tests for `BeatifyAuthRefreshView` (success returns JSON + reissues access cookie without touching the long-lived refresh cookie, HA-rejection wipes both cookies, missing-cookie 401, body shape). 11 JS tests covering the cookie reader, state-mismatch CSRF wipe, legacy-localStorage migration, refresh coalescing, and the rc15 `redirect_uri` shape.

After rc15, Safari 18 admin loads with one HTTP redirect (HA login → callback view → admin). No frontend POSTs to auth endpoints at any point; the entire transport class Safari was rejecting is no longer used.

## [3.4.0-rc14] - 2026-05-21

### Fixed
- **Safari 18 login loop — server-side OAuth exchange proxy (#998 follow-up to rc11–rc13).** Three previous attempts (rc11 self-healing SW, rc12 urlencoded fetch fallback, rc13 XHR fallback) all failed because the issue wasn't the browser transport — it was the response from HA's `/auth/token` as relayed through Nabu Casa SniTun. Safari 18 rejected the response itself with `XMLHttpRequest cannot load … due to access control checks`, even though the request is same-origin and HA's TokenView declares `cors_allowed = True`. Both fetch (FormData and urlencoded) and XHR were dead on Safari 18 + Nabu Casa.
- **Fix: route the OAuth code/refresh exchange through a Beatify-owned path.** New `BeatifyAuthExchangeView` at `/beatify/auth/exchange` forwards the body to HA's local `/auth/token` over loopback HTTP (or HTTPS if HA is configured with a cert). The exchange never crosses SniTun, so the response Safari sees comes from a path it has no reason to special-case — same-origin, plain JSON, explicit `Cache-Control: no-store`. `ha-auth.js` now uses a single transport (URLSearchParams body via fetch); the FormData/XHR fallback chain is gone.
- **Tests: 88 JS + 5 new Python tests cover the proxy view (loopback URL selection HTTP vs HTTPS, body forwarding, HA-rejection passthrough, connection-failure 502).** 88/88 JS + 525/525 Python pass.

After rc14, the Safari 18 console is silent on auth — no more `FormData /auth/token failed` warning, no CORS error, no loop. The proxy is on for all browsers; behavior change for non-Safari users is one extra hop server-side (~5ms over loopback).

## [3.4.0-rc13] - 2026-05-21

### Fixed
- **Safari 18 login loop — `/auth/token` fallback now uses XHR (#998 follow-up to rc12).** rc12's urlencoded-via-`fetch` fallback hit a different Safari 18 failure mode on both LAN and Nabu Casa: `Fetch API cannot load … due to access control checks` — Safari incorrectly applies a CORS check to the same-origin POST, rejecting the request before it leaves the browser. Same end symptom as rc11/rc12 (HA-login → flash of Beatify → bounce), one transport layer deeper. The full failure shape on Safari 18 is: FormData via `fetch` throws `TypeError: Load failed` (Safari rejects multipart synchronously); urlencoded via `fetch` is rejected for "access control checks" (same-origin POST treated as cross-origin); both transports through `fetch` are dead.
- **Fix:** the fallback now uses `XMLHttpRequest` with an urlencoded body. XHR predates the `fetch` spec quirks Safari 18 is hitting and uses a different network path internally — same-origin POST through XHR isn't subject to the buggy CORS check. `postToken` still tries FormData via `fetch` first (preserves rc8 Nabu Casa SniTun support for Chrome and pre-Safari-18) and falls back to XHR only on `TypeError`. HTTP rejections still propagate without retry. New test case in `ha-auth.test.js` covers the XHR HTTP-error path; 89/89 JS tests pass.

After rc13, Safari 18 users will see a one-time console warning when the fallback fires:
```
[BeatifyAuth] FormData /auth/token failed (Load failed); retrying via XHR
```
That's the fix doing its job — the XHR request then succeeds and admin loads normally.

## [3.4.0-rc12] - 2026-05-21

### Fixed
- **Safari 18 login loop on macOS Sequoia / iOS 18 (#998 follow-up).** Markus reported the rc11 admin still flickered to HA-login on Safari 18 — both on LAN and via Nabu Casa, in private windows, with the SW unregistered. Chrome worked fine. Console showed `TypeError: Load failed` at `ha-auth.js:228` (the `exchangeCode` catch); the Network tab had no `/auth/token` entry — Safari rejected the FormData fetch before the request left the browser. `exchangeCode` resolved false silently, `init()` saw `!isAuthenticated`, called `login()` and bounced the user back to the HA approve screen. Same loop shape as the original `c03b4ae5` redirect_uri bug, different transport-layer failure. The rc8 FormData fix is still needed (it survives the Nabu Casa SniTun relay that drops urlencoded POSTs); Safari 18 broke the other side of that trade.
- **Fix: `postToken` now tries FormData first (keeps Nabu Casa working) and falls back to urlencoded on `TypeError` only — fetch-level failures where the request never reached HA. HTTP rejections (4xx/5xx) propagate without retry, since retrying a server-side `invalid_grant` would just produce the same response. Both transports are needed now: FormData survives SniTun, urlencoded survives Safari 18.** New `__tests__/ha-auth.test.js` covers all three paths (TypeError → retry, HTTP 4xx → no retry, happy path → no retry). 88/88 JS tests pass.

## [3.4.0-rc11] - 2026-05-21

### Fixed
- **Login loop after HACS update — users no longer need to clear browser cache (#998 follow-up).** The service worker from a previous Beatify version was sticky: it precached `/beatify/static/js/ha-auth.js` (no query string) and Safari/WebKit would serve the stale entry for the cache-busted `?v=...` URL too, leaving users in an unrecoverable login loop on any auth-code change. Two structural fixes ensure no future upgrade requires a manual "Quit Safari + Clear Storage" dance:
  1. `sw.js` — `ha-auth.js` is now in a `NEVER_CACHE` list and the fetch handler bypasses the cache for it. The browser fetches it directly from HA on every load, where `_NO_CACHE_HEADERS` keeps ETag revalidation cheap (~30 bytes of overhead). Stale `ha-auth.js` is no longer reachable from the SW path.
  2. `admin.html` and `player.html` — inline bootstrap script at the very top of `<head>` compares the page's `beatify-version` meta tag against `localStorage.beatify_sw_version`. On mismatch with an active SW, it unregisters all SWs and reloads before any other script runs. First load after upgrade self-heals; steady-state cost is one localStorage read. Users stuck on rc10 with a stale SW auto-recover on their next admin/player page load.

The rc8/rc9 auth fixes (FormData transport, zombie-token probe, ha_token in admin join) are unchanged — those addressed the symptoms; rc11 closes the upgrade-pathology that masked them.

## [3.4.0-rc10] - 2026-05-21

### Added
- **TTS-Entity-Dropdown im Setup-Wizard (#1073, ludgerbeckmann).** Statt freier Texteingabe listet die TTS-Konfiguration jetzt alle in HA registrierten `tts.*`-Entities zur Auswahl. Reduziert Tippfehler und macht die TTS-Konfiguration einsehbar (bisheriges Behavior: User musste die Entity-ID exakt eintippen, mit hoher Fehlerrate). Locales: en/de/es/fr/nl. PR #1079.
- **"Ausgewählte Playlists"-Sheet mit Bulk-Remove (#1074, ludgerbeckmann).** Die Bottom-Nav-Counter-Pill ("N Playlists gewählt") öffnet jetzt ein Sheet mit allen aktuell gewählten Playlists, jede mit Remove-Button — Markus-Schmerzpunkt: bisher musste man jede Playlist im Hub einzeln finden um sie zu entfernen. Locales en+de. PR #1083.

### Fixed
- **Year truncation auf Reveal-Screen schmaler Telefone (#1072, laberning).** Auf Android Chrome mit Default-Zoom waren bei manchen Bildschirmgrößen nur 2-3 Stellen der Jahreszahl sichtbar. CSS-Fix zwingt die Year-Anzeige auf overflow-visible mit responsivem `min-width`. PR #1077.
- **Tighter Game-View-Layout — Artist-Tiles über dem Fold (#1076, laberning).** Beim Player-Screen lagen die Artist-Selection-Buttons im unteren Bildschirmdrittel — alle Spieler mussten jede Runde scrollen um zu voten. Padding/Margin der oberen Sektionen reduziert + Artist-Grid kompakter; die Vote-Buttons sind jetzt direkt unter dem Song-Indicator sichtbar. CSS-Only. PR #1084.

## [3.4.0-rc9] - 2026-05-21

### Fixed
- **Admin "join as player" rejected with "Home Assistant login required to host" even after a fresh OAuth login (#998 follow-up).** rc8 chased the wrong cause (zombie tokens) — that's a real bug but not what users were hitting. Actual root cause: the home-mode join flow in `admin.js` sends `{type:'join', name, is_admin:true}` to the WebSocket but never includes `ha_token`. Server's `handle_join` calls `_is_ha_authenticated(data)` which checks `data.get("ha_token")`, finds nothing, returns `ERR_UNAUTHORIZED`. The host's name never appears in the player list, even with a fully valid OAuth session (verified by browser test: fresh incognito + completed login still triggered the loop). `admin_connect` was sending `ha_token` correctly all along, but its auth doesn't carry over to subsequent messages on the same socket — every authed message needs its own token. Fix mirrors the working pattern at `player-core.js:459`: `await BeatifyAuth.ensureAuthenticated()` before sending, and include the token in the join payload. The rc8 zombie-token probe stays — it's still a valid defense against server-revoked refresh tokens.

## [3.4.0-rc8] - 2026-05-21

### Fixed
- **Home Assistant login over Nabu Casa cloud failed with "TypeError: Load failed" (#998 follow-up).** When the admin or player page completed the HA OAuth redirect on a `*.ui.nabu.casa` URL, the `POST /auth/token` exchange rejected with Safari's generic transport error and bounced the user back to HA login in a loop. Root cause: the SniTun relay drops `application/x-www-form-urlencoded` POSTs to `/auth/token` on this path; the bytes never reach HA. `ha-auth.js` `postToken` now uses `FormData` (multipart) with explicit `credentials: 'same-origin'` and no manual `Content-Type` — matching the transport Home Assistant's own frontend (`home-assistant-js-websocket`) uses on the same cloud URLs. Same wire intent; HA's `/auth/token` accepts both content types. LAN/direct-HA users were never affected.
- **Admin "join as player" silently failed when HA tokens were server-revoked.** After an HA restart (or manual refresh-token revoke), the locally-stored access token still passed Beatify's `accessFresh()` check because that only inspects the local expiry timestamp. Admin would load, but every authed action — adding yourself as a player, hosting a game — silently 401'd, leaving the host's name absent from the player list while regular players (no HA auth required) joined fine. `BeatifyAuth.init({ requireAuth: true })` now probes `GET /api/` once to confirm the token is valid server-side; the existing `authedFetch` 401-refresh-login chain handles recovery automatically. Player path (`requireAuth: false`) skips the probe so it defers HA calls until the user actually claims the host role.

## [3.4.0-rc7] - 2026-05-21

### Fixed
- **Unresolved Git merge conflict markers in admin assets (#1071).** The PR #1007 (security gate #998) merge accidentally committed unresolved `<<<<<<< HEAD … >>>>>>> 984697bd` markers in `admin.html`, `admin.min.js` (3 places), and `party-lights.min.js`. Symptom on rc6: the literal marker block leaked into the admin page footer, and because `admin.min.js` started with `<<<<<<<` on line 1, the whole admin UI failed with a JS SyntaxError and only skeleton loaders rendered. The sources (`admin.js`, `party-lights.js`) were already correctly merged — only the minified outputs were broken; this release regenerates them via `make build`. Also re-includes `playlist-generator.min.js` (deleted by `make clean` because it was missing from Makefile `JS_FILES`).
- **Stale unit test for `admin_connect` (post-#998).** `test_admin_command_from_admin_ws` still sent the retired `admin_token` field; the handler now expects `ha_token`. The test is updated to mirror the pattern of the passing tests; full `test_websocket.py` suite (71 tests) green.

## [3.4.0-rc6] - 2026-05-20

### Security
- **Admin console gated behind Home Assistant login (#998).** `/beatify/admin` and every host-control endpoint (`start-game`, `start-gameplay`, `end-game`, `rematch-game`, `force-reset`, `preview-lights`, `tts-test`, `lights`, `capabilities`) used to be reachable by anyone who could reach Home Assistant; the admin page even embedded the active admin token into the HTML. Hosting now requires a logged-in HA user — the admin page is served as a static, secret-free shell that runs an OAuth flow against HA's own auth (`ha-auth.js`), every authed REST call carries the resulting bearer token, and the admin WebSocket validates an HA access token on `admin_connect`. Players joining `/beatify/play` remain unauthenticated.
- **OAuth flicker-and-bounce loop fixed.** Initial testing showed a redirect loop: after HA login the admin briefly rendered, then bounced back to the login screen. Root cause: the token-exchange POST omitted `redirect_uri`, which RFC 6749 §4.1.3 (and HA's IndieAuth impl) requires when it was sent on `/auth/authorize`. The exchange now sends the same `redirect_uri` as `login()`, the code grant succeeds, and the admin sticks.

## [3.4.0-rc5] - 2026-05-20

### Changed
- **Playlist generator validation result is now a flat error list, not a per-row ✓/✗ table (#1052).** The 16-column checkmark grid was ambitious-looking but information-poor: on a clean validation it added a wall of green ticks the user already inferred from the verdict line, and on narrow mobile viewports the cells stacked vertically because the table was wider than the viewport. The new render shows only songs that have actual issues, grouped under a `Songs with issues (N)` heading, with `field: message` lines per problem. On a clean validation, the user sees the green verdict + the "Copy result for LLM" button and nothing else.

## [3.4.0-rc4] - 2026-05-20

### Added
- **Sanitizer now also strips Markdown wrappers around the JSON (#1052).** Two more paste-corruption patterns surfaced during testing: (a) LLMs ignoring "no markdown fences" and returning their output inside ` ```json … ``` `, and (b) users accidentally pasting the "Copy result for LLM" brief — which starts with `# Beatify playlist JSON — validation feedback` — back into the textarea. Both made the JSON parser bail with "Unrecognized token '#'" or similar. The Validate button now runs a pre-parse cleanup that (1) extracts content between the first/last triple-backtick fences and (2) trims anything before the first `{` and after the last `}`. The cleaned text is written back to the textarea, and a localised hint tells the user what was stripped. Combined with rc3's per-URI angle-bracket sanitizer, a single Validate click now handles both layers in one pass. 5 new vitest cases (80 passing total).

### Added
- **Paste-corruption auto-cleaner in the playlist generator (#1052).** Some chat renderers (Telegram and friends) wrap bare URLs inside code blocks with Markdown autolink syntax `<URL>`. When users copy-pasted JSON from chat into Beatify's textarea, every URI field arrived corrupted and validation rejected the playlist with no clear way to recover. The Validate button now strips those wrappers from all five URI fields (Spotify / Apple Music / per-region Apple Music / YouTube Music / Tidal / Deezer) before running shape checks, rewrites the textarea so the user sees exactly what changed, and shows a localised "Auto-cleaned N URL wrapper(s)" hint. Non-URI fields (e.g. a `fun_fact` that mentions "<Sandstorm>") are left untouched. 6 new vitest cases cover the sanitizer (75 passing total).

## [3.4.0-rc2] - 2026-05-20

### Added
- **"Copy result for LLM" button in the playlist generator (#1052).** Once you Validate, a button next to the verdict copies a structured Markdown brief — error and warning lists with `songs[N].field` paths, each song's artist/title for human reference, the actual value that was returned, and the full original JSON embedded as a fenced block — so you can paste it straight back into the same LLM session and ask for a corrected JSON. The brief explicitly lists which entries validated cleanly and must not be touched.
- **i18n for the entire generator UI.** All user-visible strings in the generator modal and the new Mine-tab tiles now route through `window.BeatifyI18n`. Added a top-level `playlistGenerator` block + `playlistHub.mine.generator` entries to all five locales (en/de/es/fr/nl). The LLM-bound payloads — the prompt itself and the validation refinement brief — stay English by design, since both are prompt-engineering payloads where English yields the strongest instruction-following.
- **Per-row error messages now echo the bad value.** When a URI fails shape validation, the error message includes `Got: "<actual value>"` so paste-corruption (smart quotes, non-breaking spaces in URLs, etc.) is one glance to diagnose instead of looking like a regex mystery. Validator helper count is now 34 vitest cases (69 passing total).

## [3.4.0-rc1] - 2026-05-20

### Added
- **LLM-assisted playlist generator (#1052).** A new "Generate via LLM" tile in the Playlist Hub's Mine tab opens a modal that bridges a Spotify playlist URL → templated prompt → user pastes JSON from their own LLM (ChatGPT, Claude.ai, local model — no API calls leave Beatify) → client-side validator with per-row ✓/✗ table → submit as GitHub issue. The validator checks JSON shape, every required top-level field + type, all 15 per-song fields, and URI shape per provider; it also warns on the two common LLM hallucination tells — identical Apple Music IDs across all 7 regions, and duplicate ISRCs across songs. **Pre-release scope:** the "Save locally" and "Submit as PR" buttons are deferred to a v3.4.0 follow-up (need a new backend write endpoint and a real fork/commit flow respectively); the modal surfaces both omissions inline.

## [3.3.7] - 2026-05-20

### Added
- **Movie Quiz Bonus toggle in game setup (#1009).** The engine supported `movie_quiz_enabled` but no UI ever exposed it, so the bonus was effectively always on. A toggle now sits next to Artist Challenge in the game-settings panel and the first-run wizard.
- **Searchable light-entity list in the wizard (#1039).** When configuring Party Lights in the setup wizard, the entity list could be long on real HA installs. A search field above the list filters by friendly name as you type, preserving checkbox state. Translated across all five locales.
- **Playlist acceptance criteria in the request modal (#986).** The request form carried only a one-line note; it now lists the six concrete criteria a playlist must meet — themed, not a duplicate, a fixed selection, curated in size, recognisable to a party crowd, no explicit content — so users can self-filter before submitting. Translated across all five locales.

### Changed
- **Auto-advance is now visible on the home screen (#1028).** The Auto-Advance chips existed in admin.html but were hidden twice — Game Settings collapsed by default, and the Home meta line ignored Auto-Advance entirely. Game Settings now opens expanded, and the Home meta row shows `⏭️ 30s` (or `Off`) next to difficulty/duration/language so the current setting is always one glance away.
- **Auto-Advance chips also in the setup wizard (#1028 follow-up).** Step 4 of the wizard now exposes the same Off / 30s / 60s / 90s chips, hydrated from and persisted to the same `beatify_game_settings.revealAutoAdvance` key — so the admin panel and the wizard are two views on one state. Translated across all five locales.
- **Artist Challenge cards always equal height.** When one artist name wrapped to two lines (e.g. "Sonic Dream Collective"), its row grew taller than the other, making the 2×2 grid look uneven. `grid-auto-rows: 1fr` and a larger min-height ensure all four cards now share the same size regardless of name length.
- **REVEAL auto-advance — the game runs unattended (#1012).** The game no longer stalls in REVEAL waiting for the host to click "Next round". A new **Auto-advance** setting (Off / 30 / 60 / 90s, default **Off**) starts the next round on its own when set to a duration; **Off** advances when the round's song finishes playing. The manual "Next round" button stays as an early-skip override.
- **Auto-advance halts on an idle round (#1012 follow-up).** If a whole round passes with zero guesses, the party is idle — rather than burning through the playlist unattended, the game lets the round's song play out, stops the speaker, and holds on REVEAL without starting a new round. The host's manual "Next round" still resumes. Always on, independent of the Auto-advance timer setting.
- **Betting is now Triple or Nothing (#1004).** The double-or-nothing bet had no real downside — a lost bet scored 0, which is what a missed round scores anyway. A bet now wins only on the **exact** year (×3 points); any non-exact guess forfeits the round score. Renamed and re-copied across all five locales.

### Fixed
- **Playlist-request status never updated (#970).** A delivered playlist request stayed stuck on "submitted" in the Playlist Hub's "Meine" tab forever. The request `status` field was write-once and nothing reconciled it afterward — the old browser poller (removed in #939) had only ever advanced a request carrying both a `playlist-ready` label and a `vX.Y.Z` version label, so requests the maintainer closed with `approved` never matched. `PlaylistRequestsView.get()` now reconciles pending requests against GitHub issue **state** (a closed issue means delivered, independent of label), server-side and throttled to once an hour.
- **Declined playlist requests showed as "ready" (#970 follow-up).** A request the maintainer closed as "not planned" without a decline label was still synced to "✅ Ready", telling the user their playlist had shipped when it had been turned down. The status sync now also honours GitHub's `not_planned` close reason, and existing mis-marked requests were corrected.
- **Playlist detail sheet's CTA button clipped (#1013).** On a short viewport the "Add to round" button was cut off by the sheet's `overflow:hidden`; the fixed header/stats/footer sections no longer compress, so the button always renders fully.
- **In-game "Invite players" button did nothing (#1009).** The reveal-screen "Invite players" button no-opped for a client that never saw the lobby — an admin who joined as a player mid-game — because the join URL was only captured in the LOBBY-phase handler. It is now captured from every state update, so the QR invite popup always opens. The original #1009 commit also never bumped the player-bundle `?v=` cache-buster or the service-worker cache version, so the fix would not have reached browsers; both are now bumped.
- **`{years}` placeholder leaked onto the admin reveal.** The average-accuracy line rendered a literal `Ø 20 {years} years off` — the `reveal.yearsOff` i18n string was fetched without its interpolation argument. It now interpolates the count correctly.
- **Round froze on the PLAYING screen when nobody guessed.** The server's round timer is a single asyncio task; if it is cancelled on a pause and never restarted, or lost to a resume/desync edge, the round never advanced to REVEAL. The client watchdog meant to catch this fired only once, so a single nudge that raced the server clock or dropped on a reconnecting socket was never retried. The watchdog now keeps nudging the server every few seconds past the deadline until the round actually ends.
- **"Open TV Dashboard" link never appeared on the host screen.** The link existed in the home-screen markup but only un-hid when the server sent a `dashboard_url` field — which it never does. The host screen now derives the dashboard URL from the join URL, so the link shows whenever a game exists.
- **Idle-halted REVEAL looked generically stuck (#1012 follow-up).** When the rc6 idle-halt holds the game on REVEAL after a zero-guess round, the screen gave no signal that this was intentional — reloading landed users on REVEAL with no banner, no next-step. The REVEAL screen (admin + player) now shows a clear "Game idle — no one played this round. Tap Next round to keep going." banner whenever the idle-halt is active. Translated across all five locales.
- **Round froze on PLAYING — root cause fix (#1029).** Complementing the rc7 client watchdog, the real upstream defect: when the round timer expired, the timer task awaited `end_round`, which called `cancel_timer()` — cancelling the task it was running inside. The resulting `CancelledError` interrupted the REVEAL broadcast (and historically the phase transition itself), with no log because the done-callback treated cancellations as expected. `end_round` now releases the `_timer_task` handle before cancelling, so the running task no longer cancels itself. Regression test added.
- **Game ran silent — TTS settings not picked up at game start (#1010).** The wizard wrote `beatify_tts` to localStorage *after* `tts-settings.js` had initialised, so `_ttsConfig()` returned the page-load defaults (`enabled: false`). The backend skipped `configure_tts` and the game played no announcements. `_ttsConfig()` now re-reads localStorage at game start so wizard-written values take effect.
- **Party Lights never reacted in-game when set up via the wizard (#1011).** When the user toggled Party Lights on in the wizard, only `lights/intensity/light_mode` were persisted — no `enabled` key. `party-lights.js` loaded `enabled = saved.enabled || false`, so the start-game request carried `party_lights.enabled = false` and the backend skipped `configure_party_lights`. The wizard now persists `enabled` alongside the rest, mirroring the TTS branch.
- **Party Lights legacy-payload recovery (#1011 follow-up).** Two further gaps left existing users stuck off: the wizard's hydrate didn't set `chosenLevelUps.lights = true` for already-configured lights, so re-running the wizard skipped the persist branch; and `party-lights.js` treated a payload with `lights:[…]` but no `enabled` key as off. Both are now fixed — re-entering the wizard repairs the payload, and existing legacy state recovers automatically (no manual re-toggle needed). Symmetric recovery added for TTS.
- **Auto-Advance broadcast missing the new PLAYING state (#1012 follow-up).** When auto-advance fired, the server moved to PLAYING and started the next song, but only sync state-callbacks ran — the async WebSocket broadcast (`_on_round_end` = `ws_handler.broadcast_state`) was never awaited. Music started, admin + player screens stayed on REVEAL. `_reveal_auto_advance` now awaits the broadcast after `start_round`, mirroring the manual `admin_next_round` path. Default also changed from 30s to Off so the feature is opt-in.

### Data
- **New playlist: 40s & 50s Classics (#922).** 152 rock'n'roll, doo-wop and early-pop classics spanning 1939–1962.
- **New playlist: Trance Classics (#988).** 120 trance, hands-up and Loveparade-era dance classics spanning 1991–2009.
- **Greatest Metal Songs enriched (#981).** Nine canonical anthems added — Painkiller, Breaking the Law, Angel of Death, Cemetery Gates, Hangar 18, Stargazer, Nothing Else Matters, I Want Out, B.Y.O.B. — taking the playlist from 52 to 61 songs.
- **Deutschpop Klassiker — Die Orsons "Schwung in die Kiste" added (#1022).** Diff against Spotify Editorial 37i9dQZF1DX2cNqJ4LgCMf shows 99/100 tracks already covered; the missing one is now in, enriched with ISRC, Apple Music per-region track IDs, Deezer, YouTube Music, alt_artists, and fun facts across all five locales.

### Docs
- TV Dashboard link renamed **Open TV Dashboard** so the feature is findable (#1009). README corrected: YouTube Music works on a free account (#912), Artist Challenge is first-correct-wins (#947); the version badge is now dynamic.

## [3.3.6] - 2026-05-18

See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.6) for the user-facing summary.

### Added
- **TTS announcements — Betting & Game State (Phase 3 of 4, #841).** Seven new voice announcements: bet won, bet lost, player join, player reconnect, last round, podium, and rematch. Player-reconnect defaults off (phones re-establish the WebSocket constantly).
- **TTS announcements — Special Modes (Phase 4 of 4, #842).** Three new announcements: intro round, steal unlocked, steal used. Completes the #471 TTS roadmap.
- **Admin TTS toggle UI for all three phases.** Phase 1/2 shipped toggle plumbing but no checkboxes; all 23 event toggles are now rendered in the TTS Announcements section, grouped into Game Flow / Player Achievements / Betting & Game State / Special Modes. 39 i18n keys across all 5 locales.
- **TTS verbosity presets.** A Minimal / Standard / Full selector bulk-sets the 23 toggles; editing one by hand flips it to Custom.

### Changed
- **Combined REVEAL announcement.** The per-round REVEAL events (correct answer, accuracy, streaks, bet outcomes, steal unlocks, standings) are collected into one narrated utterance instead of up to ~7 separate TTS clips. Each fragment is still gated by its own toggle.
- **Setup wizard TTS step uses verbosity presets.** Step 5 previously exposed only two announce checkboxes (game start, round winner) and silently dropped the other 21 toggles on save. It now offers the same Minimal / Standard / Full presets as the admin panel; a hand-tuned (Custom) config is preserved, not clobbered.

### Fixed
- **40 broken URIs in `harder-styles` (#916).** An automated health-check found 40 URIs (32 YouTube Music, 5 Apple Music, 3 Deezer) pointing to the wrong track. 32 re-resolved automatically; 5 obscure festival anthems pointed at the official label/organiser channel uploads; 3 left as best-available.
- **Round stuck on "Waiting for others" (#928).** Early reveal counted every `connected` player, including a stale ghost whose WebSocket had already dropped — that ghost never submits, so the round never advanced and a restart hit the same wall. All-submitted detection now ignores players with a closed WebSocket, and a mid-round disconnect re-checks for early reveal.
- **Album art broken for remote players (#933).** With a Music Assistant speaker, album art was served straight from the MA server's LAN address — so any guest who joined via the QR code / remote URL had it blocked by the browser. Art is now proxied through Beatify, same-origin, so remote players see it.
- **Player kicked back to the join screen mid-round (#934).** A year/artist guess submitted in the instant a round flipped to reveal was rejected, and the player UI fell all the way back to the name-entry screen — wiping their session. Late guesses are now handled gracefully; the player simply lands on the reveal.
- **"Start game" did nothing in the lobby (#935).** After a page reload the admin's Start button could call the create-game endpoint instead of begin-rounds and dead-end on a "409 — end current game first", for a game already sitting in the lobby. It now reconciles with the server before acting, and recovers automatically if it raced.
- **Playlist requests never saved (#937).** Every save to the playlist-request store failed with a 400 — the handler passed an aiohttp parameter that newer versions removed, so the call crashed before reading the body. Saves work again.
- **Host couldn't start the game after a reload (#951).** The admin token that authorises Start, End and the game controls was only stored when *this browser* created the game. Reload the admin page — or open it fresh on another device — and the token was gone, so "Start game" failed with a 403 and there was no way to recover. The token is now embedded in the admin page itself, so the host can always control the game.
- **Service worker no longer logs a failed-cache error (#948).** The offline precache list still pointed at the old single-file player script after it became a bundle; corrected to the real filename.
- **No feedback when Music Assistant can't play (#949).** When the speaker stayed silent (idle, or the streaming provider unauthenticated), the game retried for ~2 minutes behind a frozen "Starting…" button before saying anything. It now pauses within seconds and shows the recovery banner — which names the provider to re-authenticate and offers Resume — straight away.
- **"Join as player" button vanished after the first game (#956).** Once the host had joined any game as a player, a stale browser-session marker hid the button for every later game in that tab — even a brand-new lobby. The button now reflects only the current game's state.
- **Admin "Start game" button could freeze on "Starting…" (#949).** When playback couldn't begin, the server reported the failure but the admin page didn't act on it — the button stayed frozen with no message. It now resets, surfaces the reason, and drops the host straight onto the recovery banner.
- **Missing Intro Mode translations (#938).** The intro-round splash referenced four translation keys that didn't exist, logging console warnings on load; added across all five languages.
- **Admin page no longer calls the GitHub API from the browser (#939).** The playlist-request list polled GitHub directly from the browser — unauthenticated, rate-limited, and spamming the console with 403s. The browser-side poll was removed; the list still loads from Beatify's own backend.
- **"1 players in lobby" pluralization (#940).** A one-player lobby now reads "1 player".
- **Round froze on the playing screen when a player didn't submit (#964).** The server's round timer is a single async task — if it died, the round stayed on PLAYING forever with no way out. Each player's browser now nudges the server when its own countdown hits zero; the server force-ends the round only if it really is past its deadline. A self-healing watchdog independent of the trigger.
- **Dashboard overflowed or cropped on shorter TVs (#963).** As more players joined, the playing screen's leaderboard and album/timer hero could run off-screen. Rows now flex to share the section height and scale by player count, and the hero column scales with viewport height — 1080p output is unchanged.
- **Player frozen on the playing screen while the game advanced (#967).** A half-open WebSocket — dead after a network blip, unnoticed by either side — meant the server broadcast REVEAL into a void and the player's screen never moved on. A client-side heartbeat now pings every 15s; if no message arrives back for 40s the socket is treated as dead and force-closed, triggering a reconnect that pulls fresh state.

### Data
- **3 wrong URIs fixed in 2010s & 2020s Hits (#954).** Three tracks in the community playlist pointed at the wrong song; re-resolved.
- **New community playlist — EDM Anthems (#955).** 126 mainstream / festival EDM tracks (Avicii, Calvin Harris, David Guetta, Martin Garrix, The Chainsmokers, Swedish House Mafia, Marshmello, Alan Walker, Zedd, Kygo, Tiësto), year range 2009–2024, curated from a 140-track request. Fills the mainstream-EDM gap between eurodance-90s and harder-styles.
- **Harder Styles — 150 → 190 songs (#899).** 40 modern hardstyle tracks (festival anthems + hardstyle remixes of chart hits) folded in from playlist request #899, with per-region Apple Music URIs.
- **90er Ohrwürmer request routed (#906).** 90s Hits 58 → 94 songs (international, no German-language tracks — EAV removed); Deutschpop Klassiker 100 → 106 songs (scope widened to the 90s/NDW canon). Years resolved via MusicBrainz first-release dates.
- **New community playlist — Divorced Dad Rock (#910).** 107 post-grunge / nu-metal / 2000s radio-rock tracks (Nickelback, Creed, 3 Doors Down, Linkin Park, Audioslave, …), curated from a 130-track request — cover-band re-recordings and obscure filler dropped.
- **Playlist-wide year audit — 274 release years corrected (#911).** All 3,400+ songs were checked against MusicBrainz first-release dates; 274 stored years that were re-release / compilation / cover dates were corrected and independently verified. 78 songs revealed to be in the wrong decade playlist were re-bucketed; 22 with no decade playlist were tracked as new playlist ideas (#921 70s, #922 50s, #923 Christmas).
- **TTS announcement test coverage.** 14 unit tests for the combined REVEAL announcement.

### Docs
- README now states that Beatify needs a premium streaming subscription — free/ad-supported tiers (e.g. Spotify Free) can't do on-demand single-track playback.

## [3.3.5] - 2026-05-15

Stable promotion of the 3.3.5-rc1 line. See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.5) for the user-facing summary.

### Added
- **TTS Player Achievements — Phase 2 of 4 (#840).** Six new voice announcements driven from player results rather than round lifecycle: exact-year guess, Closest-Wins winner, streak milestone, streak broken, new leader, and a tie at the top. Each is an independent toggle in `configure_tts`. Orchestrated by a new `_announce_player_achievements()` in `game/state.py` with six `_tts_announce_*` flags plus `_tts_previous_leader` for leader-change detection. Phase 1 (round lifecycle) shipped in 3.3.4; phases 3-4 (betting/state, special modes) remain in #841 / #842.
- **Five new community playlists.** Anime Openings (101 songs), Ballermann Party Hits (189), Harder Styles (150), Best of Giraffenaffen (26), and 2010s & 2020s Hits (128) — the last closing the decade gap between the 2000s playlist and today. Four came from in-app playlist requests (#878, #887, #889, #883).

### Fixed
- **Admin Stop button no longer silently dead (#880).** On a WebSocket reconnect race the player-view Stop button could no-op without feedback. `handleStopSong()` now surfaces a connection-lost label when the socket is down, and `debounceAdminAction()` was rewritten to a timestamp-based guard (`lastAdminActionAt`) so it can no longer wedge every admin button after a missed action.
- **Fun-fact spoiler leak on participant admin dashboard closed (#882).** A reconnect race could briefly render the song's fun fact on a playing admin's dashboard before REVEAL. The fair-play guard now uses a durable `sessionStorage['beatify_admin_name']` signal that survives reconnects.
- **Repo landing-page link works again (#881).** The GitHub project link redirected to a parked blank page — the `beatify.life` custom domain on the `gh-pages` branch pointed at a Strato parking page. The dead `CNAME` was removed and SEO URLs updated so the link serves directly.

### Data
- 98 songs backfilled into the existing decade and greatest-hits playlists (`top-songs-der-60er`, `greatest-hits-of-all-time`, `80er-hits`, `90er-hits`, `2000s-pop-anthems`) from the Hitster Deutschland request (#892) — only 29% overlap with existing coverage, the rest bucketed by decade. Beatify now ships 30 playlists / 3,273 songs. All new and backfilled songs carry full Spotify / Apple Music (incl. per-region) / YouTube Music / Deezer URIs, years and fun facts in 5 languages.

## [3.3.4] - 2026-05-14

Stable promotion of the 3.3.4-rc line (rc1 → rc5). See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.4) for the user-facing summary.

### Added
- **Round-show audio — TTS Phase 1 (#471).** Five new round-lifecycle voice announcements wired into the game flow: round start, optional 3-2-1 countdown (off by default — intrusive every round), time's up (fires only when the timer runs to zero, not on early-reveal), correct-answer reveal, and "nobody got it this round" (fires alongside correct-answer when no player landed years_off=0). Each is an independent toggle in `configure_tts`. Works with any HA TTS engine. Phases 2-4 (player achievements, betting/state, special modes) remain tracked in #840 / #841 / #842.
- **Year ±5 buttons flanking the existing ±1 buttons.** Quick decade-jumps without holding for long-press repeat. ±1 and ±5 share the same single-pointerdown contract from #851.
- **Album cover blur during PLAYING, crisp at REVEAL (#850).** A permanent 12px CSS blur (+15% scale to keep the orb fully filled) on `.arc-pulse-orb-img` during the round, preserving colour/vibe but hiding readable text (titles, years, artist names) that could leak the year answer. The larger `#reveal-album-cover` is a separate element and remains crisp at REVEAL. Closes discussion #847.

### Fixed
- **Year ±1/±5 buttons step exactly 1 per tap on iOS (#866).** `.slider-btn-year` was missing `touch-action: manipulation`, so iOS Safari emitted a synthesized mouse `pointerdown` after the touch one — each tap fired the handler twice (±1 stepped 2, ±5 stepped 10). Other interactive surfaces in the codebase already declared the property; this was the missed selector.
- **Year ±N step grew with the round number on touch devices (#854, rc2).** `initYearSelector()` was being called from `player-core.js:570` on every PLAYING-phase state update. Without a guard, every round stacked another `pointerdown` listener on each ±1/±5 button — round 2 → +2 per tap, round 3 → +3, etc. Module-level `yearSelectorInitialized` flag now ensures listener setup runs at most once per page load.
- **Points breakdown rows reconcile to total (#867).** The Speed bonus row was computed as `round_score - base_score`, which silently absorbed the ×2 Double-or-Nothing multiplier into the +addon. A bet-won round showed `Base 5 / Speed +9 / ×2 / Total +14` — math nonsense (5+9=14 already). Now derives the speed addon from `Math.floor(base × speed_multiplier) - base`, matching the Python `int()` truncation on the backend. Same round now reads `Base 5 / Speed +2 / ×2 / Total +14` and reconciles.
- **Reveal cover falls back to no-artwork.svg on HTTP failure (#869).** The reveal song-strip cover's JS `||` coalesce only catches falsy `song.album_art`, not a populated-but-404'ing URL (e.g. an expired media-player-proxy token). Without an HTTP-error handler the broken img let the `.song-strip-cover` gradient background bleed through, looking like the cover was intentionally a pink/purple block. Added an `onerror` handler that swaps to the precached `/beatify/static/img/no-artwork.svg`, mirroring the pattern at `player-game.js:241` for the in-round `#album-cover`.
- **Playlist detail-sheet button no longer clipped on iOS (#855).** `.plh-sheet-foot` had no `env(safe-area-inset-bottom)` padding, so the Add/Remove button at the bottom of the playlist detail sheet was clipped underneath the iPhone home-indicator gesture area. Now respects safe-area. First report by @ludgerbeckmann.
- **Admin lobby no longer drags freely on iOS (#865).** Body had no `overscroll-behavior` — iOS Safari's default bounce/overscroll let the user pan the page freely when no inner element claimed the touch. The home-view's `min-height: calc(100vh - 120px)` is shorter than the viewport, so the touch fell through to body. `overscroll-behavior: none` on body fixes it everywhere without disabling legitimate inner scrolling.
- **German launcher, lobby and error toasts fully translated (#864).** Three root causes plugged: `launcher.html`'s `data-i18n="launcher.clickToLaunch"` referenced a key that was never added to any locale file; `wizard.js`'s `_renderDoneSummary` hard-coded label names in the template (`<span>Speaker</span>` etc.) without going through `_t()`; and `admin.js`'s `startGame` error handler displayed the backend's English message verbatim instead of mapping `data.code` → `errors.<CODE>` via `BeatifyI18n.t()`. 7 new keys × 5 locales (en/de/es/fr/nl); ES/FR/NL received identical treatment.

### Data
- **73 broken YouTube Music URIs in `community/yacht-rock` (#852, PR #860).** 16 dead videos + 57 cyclically scrambled. All 73 resolved via `ytmusicapi` search with artist+title scoring; 2 low-confidence batch hits manually overridden after re-search (REO Speedwagon "Live Every Moment", Ray Parker Jr. "You Can't Change That"). All HTTP-200 verified before commit. Apple Music (96) + Spotify (21) for the same playlist already shipped via #853 in rc2.
- **52 broken/scrambled URIs in `pure-pop-punk` (#848, PR #849, rc2).** YouTube + Apple columns cyclically scrambled across the second half of the playlist. 4 dead Apple IDs replaced + 3 wrong Spotify URIs corrected.
- **2 broken URIs in `one-hit-wonders` (#843, PR #844, rc2).** Modern English "I Melt With You" (2012-Re-Record → 1982-Original) + Peter Schilling "Major Tom (Coming Home)" (deutsche Version → englische "Coming Home").
- **2 broken YouTube Music URIs in `greatest-metal-songs` (#845, PR #846, rc2).**
- **1 dead YouTube Music URI in `top-songs-der-60er` (#862, PR #863).**

### Documentation
- **`docs/release-notes-v3.3.4.md`** — User-facing marketing-style release notes in the v3.3.3 voice.

### For contributors
- Bumped `manifest.json` + `sw.js CACHE_VERSION` → `3.3.4`. Bumped `?v=` cache-busters on `admin.html` + `player.html` (3.3.3 → 3.3.4) and `<meta name="beatify-version">` on admin/player/dashboard.html.
- pytest 443 / vitest 35 — green.
- 5 release candidates (rc1 → rc5) condensed into this stable promotion — most of the rc3/rc4/rc5 cycle was driven by @ludgerbeckmann's live screenshot testing on the rc-line.

## [3.3.3] - 2026-05-04

Stable promotion of the 3.3.3-rc line. See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.3) for the user-facing summary.

### Added
- **New community playlist: Deutschpop Klassiker (#839).** 100 tracks of modern German pop (2002–2019) joining the Community library — sourced from the Spotify Editorial of the same name (475k saves) via Beatify's playlist-request flow. Coverage: Spotify / YouTube Music / Deezer 100/100; Apple Music + 7 regional URIs (US/DE/GB/FR/ES/NL/IT) 99/100; alt_artists 100/100; fun_facts in en/de/es/fr/nl 100/100; chart_info 69/100; certifications 47/100. Tidal 1/100 (search-by-ISRC requires OAuth — pending follow-up).

### Fixed
- **Helpful error hints when a playlist request fails (#835 follow-up).** The Cloudflare worker behind the playlist-request flow had always returned a structured `error.code` field, but `playlist-requests.js` silently dropped it and forwarded only the raw message. Now the code rides through to `admin.js`, which maps `errors.<UPPER_CODE>` via `BeatifyI18n.t()` and falls back to the original message when no key matches. Four new keys — `INVALID_FORMAT`, `PLAYLIST_NOT_FOUND`, `GITHUB_ERROR`, `RATE_LIMITED` — localized in en/de/es/fr/nl.
- **Worker `GITHUB_TOKEN` rotated (#835 root cause, infra).** Closes the symptom @Helloitsme reported in discussion #834 — playlist submissions had been failing with `error: github_error` until the Fine-grained PAT was refreshed.
- **State-read resilience during MA playback confirmation.** A transient `RuntimeError` from `hass.states.get()` mid-playback used to abort the whole song play. New `_safe_state()` + `_safe_state_with_retry()` helpers in `MediaPlayerService` downgrade transient exceptions to "speaker state unknown", letting the title-advance check still succeed. Closes the lone xfailed test from v3.3.2.
- **Playlist Hub "Request a playlist" FAB icon now reliably visible.** The cyan envelope FAB had an invisible icon for some users — Webkit doesn't always propagate CSS-variable `currentColor` into SVG strokes. Pinned the dark stroke directly via `.plh-cta-fab svg { stroke: var(--color-bg-primary); fill: none; }`.

### Data
- **1 dead YouTube Music URI in `greatest-hits-of-all-time` (PR #833).**
- **1 dead Apple Music URI in `eurovision-winners` (#830, PR #831).**
- **10 broken URIs in `top100-allertijden-nederlandstalig` (#828, PR #829).**

### Documentation
- **README "Built With AI Assistance" section.** Frames AI-assisted development as a strength: cites test coverage (19 Python test files + 35 Vitest tests + WS integration), in-code architecture comments, 800+ closed issues with traceable root causes, and real-user metrics.
- **Repo cleanup: untrack internal-only docs.** `CLAUDE.md`, `DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/release-3.3.0.md` removed from the public repo (gitignored — files remain on disk locally for the maintainer). Public surface trimmed to the strict HACS-essential set.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.3`. Bumped `admin.html` + `player.html` cache-busters and `<meta name="beatify-version">` on admin/player/dashboard.html → `3.3.3`.
- pytest 443 passed (was 442 + 1 xfailed in v3.3.2). 35 vitest tests pass.
- 3 release candidates (rc1 → rc2 → rc3) condensed into this stable promotion.

## [3.3.3-rc3] - 2026-05-04

### Fixed
- **Playlist Hub "Request a playlist" FAB icon now reliably visible.** The cyan envelope FAB at the bottom of the Playlist Hub had an invisible icon for some users (reported by @mholzi). The SVG used `stroke="currentColor"` and inherited the icon color via a CSS variable on the button — but some Safari/Webkit versions don't reliably propagate that inheritance to the SVG stroke. Added a defensive `.plh-cta-fab svg { stroke: var(--color-bg-primary); fill: none; }` rule to pin the dark stroke against the cyan FAB regardless of inheritance behaviour.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.3-rc3`. Bumped HTML cache-busters + `<meta name="beatify-version">` to `3.3.3-rc3`.
- CSS-only fix; `make build` regenerates `styles.min.css`.

## [3.3.3-rc2] - 2026-05-04

Adds the new "Deutschpop Klassiker" community playlist (100 tracks of modern German pop, 2002–2019), plus a small playback-resilience hardening.

### Added
- **New community playlist: Deutschpop Klassiker (#839).** 100 tracks of modern German pop sourced from the Spotify Editorial playlist of the same name (475k saves). Bridges Beatify's German content gap between traditional Schlager and contemporary mainstream — Wir sind Helden, Peter Fox, AnnenMayKantereit, Helene Fischer, Andreas Bourani, Mark Forster, Tim Bendzko, Juli, Sarah Connor, Silbermond, Wincent Weiss, Clueso, Herbert Grönemeyer et al. Year range 2002–2019. Coverage: Spotify / YouTube Music / Deezer 100/100; Apple Music + 7 regional URIs (US/DE/GB/FR/ES/NL/IT) 99/100; alt_artists 100/100; fun_facts in en/de/es/fr/nl 100/100; chart_info 69/100; certifications 47/100; Tidal 1/100 (search via OAuth not available in maintainer's free APIs — leftover slots will fill in a follow-up).

### Fixed
- **State-read resilience during MA playback confirmation (formerly xfailed test).** A transient `RuntimeError` from `hass.states.get()` mid-playback (rare, but possible during HA restarts / state-machine reloads) used to abort the whole song play. Now wrapped via two new helpers in `MediaPlayerService` — `_safe_state()` for the pre/in-wait read sites and `_safe_state_with_retry()` for the post-timeout assessment. Closes the lone xfailed test from v3.3.2 (`TestMAPollingResilience::test_state_read_exception_does_not_skip_song`); pytest goes from 442 passed / 1 xfailed → 443 passed / 0 xfailed.

### Documentation
- **README "Built With AI Assistance" section.** Frames AI-assisted development as a strength: cites the test coverage (19 Python test files + 35 Vitest tests + WS integration), in-code architecture comments, 800+ closed issues with traceable root causes, and real-user metrics. Closes the loop on the same talking points the public outreach pitches use.
- **Repo cleanup: untrack internal-only docs.** `CLAUDE.md`, `DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/release-3.3.0.md` removed from the public repo (gitignored — files remain on disk locally for the maintainer). Public surface trimmed to the strict HACS-essential set (README, CHANGELOG, LICENSE, hacs.json, custom_components/beatify/, plus test infra for CI). Three corresponding README links cleaned up.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.3-rc2`. Bumped `admin.html` + `player.html` cache-busters and `<meta name="beatify-version">` on admin/player/dashboard.html → `3.3.3-rc2`.
- 35 vitest tests pass. pytest: 443 passed (was 442 in rc1), 0 xfailed (was 1).
- No JS source changes since rc1, but `make build` regenerates `admin.min.js` + `playlist-requests.min.js` against the bumped headers.

## [3.3.3-rc1] - 2026-05-04

First rc of the 3.3.3 patch line. Surfaces structured worker error codes in the playlist-request UI and rolls in three small URI-maintenance commits that landed since v3.3.2.

### Fixed
- **Helpful error hints when a playlist request fails (#835 follow-up).** `playlist-requests.js:submitRequest` now attaches the worker's `data.error` code as `err.code` on the thrown Error; `admin.js` looks up `errors.<UPPER_CODE>` via `BeatifyI18n.t()` and prefers that hint over the raw `error.message` when a translation exists. Falls back to the original message if no key matches. Worker error-code shape verified by curl probe against the live worker.
- **Playlist requests reaching the backend again (#835 root cause, infra).** Cloudflare worker `beatify-api.mholzi.workers.dev` had its `GITHUB_TOKEN` rotated after the previous Fine-grained PAT expired and started returning HTTP 500 / `error: github_error` for every submission (editorial and user-owned alike). Resolves the symptom @Helloitsme reported in discussion #834.

### Data
- **1 dead YouTube Music URI in `greatest-hits-of-all-time` (PR #833).**
- **1 dead Apple Music URI in `eurovision-winners` (#830, PR #831).**
- **10 broken URIs in `top100-allertijden-nederlandstalig` (#828, PR #829).**

### Added (i18n keys)

Per locale (en/de/es/fr/nl) under `errors.*`:
- `INVALID_FORMAT`, `PLAYLIST_NOT_FOUND`, `GITHUB_ERROR`, `RATE_LIMITED`

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.3-rc1`. Bumped `admin.html` + `player.html` cache-busters (`styles.min.css`, `wizard.js`, `admin.min.js`, `playlist-requests.min.js`, `player.bundle.min.js`) → `3.3.3-rc1`. Bumped `<meta name="beatify-version">` on admin.html / player.html / dashboard.html → `3.3.3-rc1` so the rc19 (#824) i18n cache-bust pattern carries the new error keys.
- `make build` regenerated `admin.min.js` + `playlist-requests.min.js`.
- 35 vitest tests pass (no new tests; #835 follow-up is a JS-only fix outside the existing playlist-requests test surface).

## [3.3.2] - 2026-04-28

Stable promotion of the 3.3.2-rc line. See [release notes](https://github.com/mholzi/beatify/releases/tag/v3.3.2) for the user-facing summary.

### Fixed
- **Storefront-aware Apple Music URIs (#808 + family).** Per-region `uri_apple_music_by_region` map for 2,204 ISRC-resolved songs across all 22 playlists; runtime resolver picks the right track ID based on `hass.config.country`; songs explicitly unavailable in the user's region get filtered at playlist load. DE coverage 97.5%.
- **Apple Music wizard selection honored end-to-end (#808 root cause).** `PROVIDER_APPLE_MUSIC` was missing from `valid_providers` in `StartGameView`; selections were silently coerced to Spotify before reaching `create_game()`.
- **Playback recovery banner with Resume button (#805 + #801 + #795).** Speaker no longer keeps playing prior track while UI advances rounds; speaker `media_stop`'d on stale-title detect; PAUSED phase is recoverable instead of force-ending; recovery banner names the provider and points at the re-auth flow.
- **Round always ends cleanly (#816, #813, #803).** Per-player try/except around scoring isolates failures; title-match fast-path returns within ~1s instead of 15s timeout; cold-MA-start `media_position=0` no longer prevents Round 1 confirmation. Worst-case round-advance lag dropped from ~20s to ~3s.
- **TTS announcements actually play (#793).** `tts.speak` now receives both `entity_id` and `media_player_entity_id`. Affected every modern TTS entity (Gemini, Cloud, etc.).
- **Deezer via Music Assistant (#797).** Pass through native `deezer://track/<id>` URI instead of routing through MA's generic builtin branch.
- **Admin role survives WS reconnect from any phase (#790).** Same-name reclaim during PLAYING/REVEAL/PAUSED is recognized as the existing admin returning.
- **End game works from PAUSED phase.** `admin_end_game` was rejecting it; the End button in the control bar silently failed during recovery.
- **WS reconnect tolerance after server restart (#814).** Bumped 5s → 20s, replaced jarring `alert()` with inline modal error, added "Connecting…" button state.
- **MA URI cascade respects user's provider choice (#805).** `_PROVIDER_URI_FIELDS` keys the cascade by selected provider; no more 4×15s timeouts on Spotify/YT/Tidal URIs that an Apple-Music-only setup couldn't resolve.
- **Region-locked songs skip silently (rc11 + #816 follow-up).** Strict-detect failures classified as `last_failure_reason="unavailable"`, don't count toward `MAX_SONG_RETRIES`.
- **i18n keys cache-busted on upgrade (#824).** New `<meta name="beatify-version">` on every HTML page; `i18n.js` reads it to append `?v=` to JSON fetch URLs. Self-correcting going forward.

### Added
- **Floating mini-timer (#817).** Pinned top-right of the player view, shown via IntersectionObserver only when the main neon timer scrolls offscreen.
- **Resume-from-paused recovery UI (#805 follow-up).** Banner with Resume + End game buttons when `pause_reason` is `media_player_error` or `no_songs_available`.
- **Per-region Apple Music URI map** on every playlist song.
- **Tooling: `playlist-health-check` skill enriched with a Mode 2** to refresh per-region Apple Music URIs on demand using the Apple Music API + ISRC.
- **`pauseRecovery` i18n keys** in en/de/es/fr/nl.

### Changed
- **Wizard "Game language" defaults to browser language (#815, #822).** Uses `BeatifyI18n.detectBrowserLanguage()` directly — no session-state race with `loadSavedSettings()`.
- **Playlist Hub layout (#821).** Cards 17% larger (`136px → 160px`); header chrome compressed.
- **3 untranslated home-view strings** ("Waiting for guests…", playlist-requests pill text) now in en/de/es/fr/nl.
- **Round-flow defensive coding.** Every timer-task now has an `add_done_callback` so silent crashes leave a stack trace.

### For contributors
- 442 unit tests pass.
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2`. Bumped all HTML cache-busters to `3.3.2`. New `<meta name="beatify-version">` on admin.html, player.html, dashboard.html.
- Final test count: 442 passed, 1 xfailed.
- 19 release candidates over 4 days condensed into this stable promotion.

## [3.3.2-rc19] - 2026-04-28

### Fixed
- **i18n keys no longer render as raw strings after upgrade (#824).** @mholzi reported the admin home view showing literal strings like `admin.home.waitingForGuests` and `admin.home.playlistRequestsTitle` instead of their translations. Root cause: the service worker's cache-first strategy was serving a stale `en.json` cached from a prior rc, but the new `admin.min.js` was referencing keys (`waitingForGuests`, `playlistRequestsTitle`, etc.) that didn't exist in that stale JSON. The i18n fetch URL had no cache-buster — every release ships a new admin.min.js that may reference new i18n keys, but the JSON URL stayed identical (`/beatify/static/i18n/en.json`), so the SW kept serving the old cached version. Now: HTML pages declare a `<meta name="beatify-version" content="3.3.2-rc19">` tag, and `i18n.js` reads it to append `?v=3.3.2-rc19` to the JSON fetch URL. Each rc bump invalidates the cache for i18n files just like other static assets.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc19`. Bumped `admin.html` + `player.html` cache-busters (`styles.min.css`, `admin.min.js`, `wizard.js`, `player.bundle.min.js`) → rc19.
- Added `<meta name="beatify-version">` to admin.html, player.html, dashboard.html. The version content gets bumped each rc alongside manifest/sw versions. New helper `getVersionForCacheBust()` in `i18n.js` reads it.
- 442 tests pass.

## [3.3.2-rc18] - 2026-04-28

### Fixed
- **Wizard "Game language" default actually works now (#822 part 2).** The rc17 fix used `BeatifyI18n.getLanguage()` to read the current UI language, but `admin.js:loadSavedSettings()` runs on every page load and calls `BeatifyI18n.setLanguage(settings.language)` to apply the saved language preference. For a user with `navigator.language='de-DE'` and a stale `settings.language='en'` (from any pre-rc15 wizard run), the auto-detection's `'de'` got silently overridden to `'en'` BEFORE the wizard opened — so `getLanguage()` returned `'en'` and the rc17 fix selected the English chip. Now using `BeatifyI18n.detectBrowserLanguage()` instead — a pure read of `navigator.language`, no session state, no race. The user's browser language wins as the wizard default; explicit chip-tap during the wizard still overrides and persists.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc18`. Bumped `wizard.js` cache-buster in `admin.html` to `3.3.2-rc18`. No CSS or other JS changes.
- 442 tests pass, 1 xfailed.

## [3.3.2-rc17] - 2026-04-28

### Fixed
- **Wizard's "Game language" pill now defaults to current UI language even with stale saved value (#822).** @mholzi reported that on a German UI install, the wizard preselected English in the *Ansagesprache* pill group. The rc15 #815 fix only kicked in when no saved language existed; users who'd been through the wizard before still saw the stale 'en' from a prior session. Now the wizard always prefers the current `BeatifyI18n.getLanguage()` value as the game-language default. Saved value only takes effect when the UI language can't be determined. Power users who want game-language ≠ UI-language can tap the chip during the wizard; that explicit tap resaves and the next entry will see UI=game both times.

### Changed
- **Playlist Hub layout tighter — cards are the visual centerpiece (#821).** @mholzi reported the playlist cards felt small relative to all the chrome above them (header, search, stats tabs, genre chips, action bar). Three small CSS adjustments shift focus to the cards:
  - `.plh-card` width: **136px → 160px** (~17% larger area; still under 50% viewport on the smallest phones so two cards fit side-by-side)
  - `.plh-header` vertical padding: **12px/10px → 8px/6px** (saves ~8px above the fold)
  - `.plh-wordmark` font-size: **24px → 20px**, and titlebar bottom margin **10px → 6px**

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc17`. Bumped `admin.html` + `player.html` cache-busters (`styles.min.css`, `wizard.js`) to `3.3.2-rc17`. Minified rebuilt.
- 442 tests pass, 1 xfailed (no new tests; both fixes are JS/CSS-only outside the unit-test surface).

## [3.3.2-rc16] - 2026-04-28

### Fixed
- **Timer is now always visible during a round (#817).** @mholzi reported that scrolling down to reach the Submit Guess button on the player view caused the countdown timer to scroll off the top of the screen — leaving no idea how many seconds were left. The existing `.arc-header` was `position: sticky` already, but iOS Safari has known sticky-positioning quirks in flex/grid containers and it wasn't reliably pinning. Added a small floating mini-timer (`#timer-float`) that's `position: fixed` in the top-right corner, syncs its number from the main countdown, and is shown via IntersectionObserver only when the main neon timer is offscreen. Same warn-state pulse animation at ≤10 seconds. Hidden between rounds.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc16`. Bumped `admin.html` + `player.html` cache-busters (`styles.min.css`, `player.bundle.min.js`) to `3.3.2-rc16`. Minified rebuilt.
- 442 tests pass, 1 xfailed (unchanged from rc15 — #817 is a JS-only fix outside the unit-test surface).

## [3.3.2-rc15] - 2026-04-28

Combines the rc14 round-end resilience fix (#816) with two new bug fixes for #814 and #815. The rc14 GitHub release was held back to bundle these together so HACS only sees one new pre-release.

### Fixed
- **Admin "Join as player" no longer trips a false "Reconnecting…" alert after server restart (#814).** When the admin clicked *Als Spieler beitreten* shortly after a fresh HA start, the WS poll gave up after 5s and showed a blocking native-`alert()` modal saying *"Verbindung zum Spielserver wird wiederhergestellt – bitte erneut versuchen."* The 5s budget wasn't enough — fresh HA restarts can take ~10s to expose the WS endpoint. Bumped to 20s and replaced the jarring alert with an inline error message inside the join modal so the user keeps their typed name and just clicks Join again. Also added a *"Connecting…"* button state during the wait so it's visible the system is working.
- **Untranslated strings on the admin home view (#815):**
  - *"Waiting for guests…"* — was hard-coded English in `BeatifyHome.renderPlayers`. Now reads `admin.home.waitingForGuests` from i18n.
  - *"X playlist requests"* / *"N pending · tap to review"* / *"Tap to install"* / *"Tap to review"* — same hard-coded English. Now reads from i18n keys (`admin.home.playlistRequests*`, `admin.home.tapToReview`, `admin.home.tapToInstall`).
  - **Game language badge (the "EN" at the end of the meta line)** — wizard defaulted `chosenLanguage = 'en'` regardless of the UI language. A user viewing the wizard in German but never tapping the language chip ended up with `language: 'en'` in their saved game settings and saw "EN" on the home badge. Now: if no saved language exists and `BeatifyI18n.getLanguage()` is available, default to the current UI language.
- **(Already on main, was tagged as rc14)** Round no longer freezes on PLAYING when scoring throws (#816). See the rc14 entry below.

### Added (i18n keys)

Per locale (en/de/es/fr/nl):
- `admin.connecting` — button label while WS poll is in flight ("Connecting…" / "Verbinde…" / "Conectando…" / "Connexion…" / "Verbinden…")
- `admin.home.waitingForGuests` ("Waiting for guests…" / "Warte auf Gäste…" / etc.)
- `admin.home.playlistRequestsTitle` ("{count} playlist requests")
- `admin.home.playlistRequestsReady` ("{count} playlists ready")
- `admin.home.playlistRequestsPending` ("{count} pending • tap to review")
- `admin.home.tapToReview`, `admin.home.tapToInstall`

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc15`. Bumped `admin.min.js` + `wizard.js` + `styles.min.css` cache-busters in `admin.html` to `3.3.2-rc15`. `admin.min.js` regenerated via `make build`.
- 442 unit tests pass, 1 xfailed (carries forward from rc14 — no new tests for #814/#815, both are JS-only fixes outside the unit-test surface).

## [3.3.2-rc14] - 2026-04-28

### Fixed
- **Round no longer freezes on PLAYING when scoring throws (#816).** @mholzi reported the timer hitting 0 but the UI staying frozen on the playing screen — no transition to REVEAL, no broadcast. Root cause: the scoring loop in `_end_round_unlocked` (`ScoringService.score_player_round` × every player, plus `apply_closest_wins`, plus the `round_results` append loop) was NOT wrapped in try/except. By round 9 of a long playlist, accumulated state edge cases (a player with an unusual challenge field, a corrupted timer, etc.) could throw mid-loop, propagating up and aborting `_end_round_unlocked` BEFORE the phase-transition line. Phase stayed `PLAYING`, no broadcast fired, the UI was stuck. Now: each scoring step is per-player isolated and wrapped — one failed player loses their score for the round (logged loudly) but the round still ends and the broadcast fires.
- **Silent timer-task crashes are now logged.** Companion fix to #816: every timer task created in `RoundManager.initialize_round`, `confirm_intro_splash`, and `GameState.resume_game` now has an `add_done_callback` that surfaces any unretrieved exception with a stack trace. Previously, an unhandled exception in the timer coroutine would leave the asyncio Task in `done with exception` state but nobody called `task.result()`, so the round stayed frozen with no diagnostic in the logs. Future occurrences of this class of bug will leave a clear trail.

### For contributors
- 2 new tests in `TestEndRoundResilience` (`test_state.py`) covering the scoring-throws path and the closest-wins-throws path. 442 passed, 1 xfailed.
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc14`. No frontend asset changes.

## [3.3.2-rc13] - 2026-04-28

### Fixed
- **UI no longer lags ~15s after pressing "Next song" when MA reports a title that doesn't substring-match the playlist (#808 follow-up).** @Levtos's playthrough on rc12 had the music start immediately on round-advance, but the game screen took several seconds to appear. The cause: `_check_state` fast-path required `expected_title.lower()` to be a substring of the speaker's reported `media_title`. When the playlist had "Das Modell" but Apple Music returned "The Model", or "Hallelujah" became "Hallelujah - Live", the substring check failed and the wait timed out via the 15s slow-buffer tolerance fallback. Relaxed the fast-path to also accept *"title moved to anything different from before the call"* — the same signal the slow-buffer fallback was using, just promoted into the fast-path. UI now returns within ~1s of MA actually starting playback. The #795 stale-title invariant is preserved: if the title hasn't changed from before the call, the fast-path still rejects (covered by the existing test).
- **Reduced metadata-fetch timeout 5s → 2s.** When the playback fast-path fired (which it now does in ~1s), the game's pre-round metadata refresh would still wait up to 5 more seconds for fresh artwork from MA. That was the secondary contributor to the post-fix UI lag. New 2s budget; on timeout we fall back to the playlist's existing `album_art` field. Briefly stale art at the top of a round in worst case, but the speaker corrects on its own state callback.

### For contributors
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc13`. No frontend asset changes.
- 1 new test in `test_media_player.py` covering the German/English title-mismatch fast-path. 440 passed, 1 xfailed.

## [3.3.2-rc12] - 2026-04-28

### Added
- **Storefront-aware Apple Music URIs (#808 follow-up — the real fix).** Beatify's playlists now carry per-region Apple Music track IDs, resolved at game start based on HA's configured country. Track IDs that are confirmed unavailable in the user's storefront get filtered out of the playable pool *before* any MA call is made — no 15s timeout, no strict-detect fallback, no recovery banner. The `rc11` skip-on-unavailable behavior is preserved as a safety net for region-locks we haven't measured yet, but the common case (US-only IDs on a DE storefront) now never reaches MA.

  Concrete numbers across all 22 playlists (main + community) / 2204 ISRC-resolved songs:

  | Region | Available | Region-locked | % Coverage |
  |---|---|---|---|
  | US | 2194 | 10 | 99.5% |
  | DE | 2149 | 55 | 97.5% ← @Levtos |
  | GB | 2138 | 66 | 97.0% |
  | FR | 2147 | 57 | 97.4% |
  | ES | 2150 | 54 | 97.6% |
  | NL | 2151 | 53 | 97.6% |
  | IT | 2148 | 56 | 97.5% |

  For DE users: 55 region-locked tracks are now silently *skipped* before any MA call, instead of silently *failing* through 15s timeouts and possibly tripping the 3-failure pause limit. Same pattern across all non-US regions.

### For contributors
- New `scripts/fetch_apple_music_regions.py` — uses Apple Music API + ISRC to resolve per-region track IDs across configurable storefronts. Idempotent, batched (25 ISRCs per call), runs in ~3 minutes for the full 2481-song catalog (22 playlists: 11 main + 11 community). Credentials read from `.env` (`APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_TEAM_ID`, `APPLE_MUSIC_PRIVATE_KEY_PATH`). Re-run when adding new playlists or new storefronts.
- New song fields: `isrc` (universal recording identifier, populated for 2204/2481 songs) and `uri_apple_music_by_region` (per-region track ID, `null` for confirmed-unavailable). 277 songs without `uri_apple_music` still need ISRC backfill via Spotify API — filed as a future enhancement.
- `get_song_uri(song, provider, storefront=None)` — backwards-compatible signature; storefront only affects Apple Music. `PlaylistManager(songs, provider, storefront=None)` filters out region-locked songs at construction time.
- `GameState._detect_storefront()` reads `hass.config.country` (lower-cased). Future enhancement: query Music Assistant's WebSocket API for the actual Apple Music provider's storefront, which may differ from HA's country.
- 10 new tests in `tests/unit/test_playlist.py` covering storefront resolution + filtering. 439 passed, 1 xfailed.
- All 22 playlist files (11 main + 11 community) regenerated with the new fields (commit includes the data updates).

### Out of scope (filed for later)
- Spotify-API ISRC backfill for the 92 songs that have only `uri_spotify` (no `uri_apple_music` to look up against). Adds Spotify auth flow but unblocks per-region resolution for those songs.
- Music Assistant WebSocket API for storefront detection — would catch cases where the user's Apple Music account is on a different storefront from HA's configured country. Requires MA WS auth handling.

## [3.3.2-rc11] - 2026-04-28

### Fixed
- **Region/storefront-locked songs no longer count toward the pause-the-game retry limit (#808 follow-up).** @Levtos's playthrough on rc10 had `apple_music://track/302229811` ("All Together Now") fail with the strict-detect signature ("speaker still on prior track") — and iTunes Lookup confirmed the track is in the **US** Apple Music catalog but **NOT in DE**. Beatify's playlists store predominantly US-storefront Apple Music IDs; for users on other regional storefronts, some subset of songs will be unresolvable through their MA Apple Music provider. These individual track failures shouldn't pause the game — the user can't fix per-track availability. Now: when `_try_ma_play` detects the strict-detect failure mode, the song is classified as `last_failure_reason = "unavailable"` and `start_round` skips it silently without incrementing `_retry_count`. The game keeps playing whatever subset IS in the user's catalog. Systemic failures (offline speaker, broken provider auth) still classify as `"error"`, count toward `MAX_SONG_RETRIES`, and trigger the recovery banner.

### Changed
- **Clearer log messages on playback failure modes.** The strict-detect path now explicitly explains *"Track is likely not available in your provider's catalog/storefront, OR your provider needs re-authentication in MA. Skipping this song silently — game will try the next one."* The speaker-idle path mentions both possibilities ("speaker offline / MA unauthenticated / track unavailable") so users know which to check. This is the same diagnostic chain @mholzi walked through to find the rc8/rc9 root cause; surfacing it in the logs short-circuits the GitHub-issue-and-back-and-forth cycle.

### For contributors
- New `MediaPlayerService.last_failure_reason` field (None / "unavailable" / "error"). Cleared at the start of each `_play_via_music_assistant` call; set in the failure paths of `_try_ma_play`. Read by `start_round` in `game/state.py` to decide retry-counter behavior.
- Bumped manifest + `sw.js CACHE_VERSION` → `3.3.2-rc11`. No frontend asset changes — HTML cache-busters unchanged.
- 2 new tests in `TestStartRoundFailureClassification`: one verifies "unavailable" doesn't pause across many failures, one verifies "error" still pauses at MAX_SONG_RETRIES. Existing `test_ma_returns_false_when_title_unchanged_but_position_advances` extended to assert classification. 429 passed, 1 xfailed.

### Out of scope (filed as future enhancement)
- Storefront-aware playlist generation: re-fetch all Apple Music URIs against US/DE/GB/FR/ES storefronts during playlist build; pick the right URI based on the user's MA provider config. Would eliminate the "skip this track" frequency entirely, but requires a meaningful playlist-pipeline change and per-storefront URI storage. Filing separately.

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
