# Changelog

All notable changes to Beatify are documented here. For detailed release notes, see the individual files in `docs/` or the [Releases page](https://github.com/mholzi/beatify/releases).

## [Unreleased]

### Security / hardening
- Rate limiting on Spotify credential, import, and search endpoints (#712)
- Input length limits on credential, import, search, and edit endpoints (#703)
- Credential-scrubbed error responses — no base64 `Authorization` echoes (#690)
- Removed server-side filesystem path from import response (#704)

### Fixed
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

### Performance
- Spotify client-credentials tokens are cached for their lifetime (#691)

### UX
- Playlist import now shows in-flight progress updates (#714)

### Notes
- #688 reported a critical ImportError from deleted `URI_PATTERN_*` constants; verified not reproducible — the constants still exist in `const.py` and the referenced PR #687 is not in `git log`. No code change needed.
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
