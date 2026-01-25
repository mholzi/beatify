# Beatify v2.1.0 — Smart Speaker Routing

**Release Date:** January 2026

Intelligent media player routing with platform-aware playback. Beatify now automatically detects your speaker type and configures the optimal playback method.

---

## 🔊 Multi-Platform Speaker Support

Beatify now works seamlessly with three major Home Assistant integrations:

| Platform | Spotify | Apple Music | Playback Method |
|----------|---------|-------------|-----------------|
| **Music Assistant** | ✅ | ✅ | Direct URI playback |
| **Sonos** | ✅ | ❌ | Native Sonos integration |
| **Alexa Media Player** | ✅ | ✅ | Voice search ("Play X on Spotify") |

Each platform uses its optimal playback method automatically — no configuration needed!

---

## 🎵 Dynamic Music Service Selector

The admin screen now shows a **Music Service** section that adapts to your speaker:

| Feature | Detail |
|---------|--------|
| Platform Detection | Automatically identifies Music Assistant, Sonos, or Alexa |
| Service Options | Shows only compatible music services for selected speaker |
| Visual Badges | Platform badges on each media player for clarity |
| Smart Warnings | Helpful hints when a service isn't available |

Select Sonos? Apple Music option is hidden. Select Music Assistant? Both services available.

---

## 🚫 Cast Device Handling

Chromecast, Nest Audio, Nest Hub, and Google TV devices are not directly supported — but Beatify helps users find the solution:

| Behavior | Detail |
|----------|--------|
| Hidden Players | Cast devices don't appear in the player list |
| Helpful Hint | "Use Music Assistant for Chromecast/Nest devices" shown below players |
| Documentation | README updated with comprehensive speaker compatibility guide |

Users with Cast devices are guided to install [Music Assistant](https://music-assistant.io/) which enables full Beatify support.

---

## 📖 Improved Documentation

README completely reorganized for clarity:

| Section | Change |
|---------|--------|
| Structure | What Is → Why Better → Setup → Admin → Gameplay |
| Supported Speakers | New dedicated section with full compatibility table |
| Setup Guide | Combined installation and admin launch instructions |
| Troubleshooting | New "No speakers appearing?" section |
| FAQ | Added Chromecast/Nest FAQ |

---

## 🐛 Bug Fixes

| Fix | Detail |
|-----|--------|
| Language Selector | Fixed chips not updating page translations when clicked |
| Music Service in Lobby | Section now properly hidden during gameplay |

---

## 📊 Issues Closed

- #38 — Nest Audio not playing music
- #39 — Google TV Streamer playback issues

---

**Full Changelog:** [v2.0.2...v2.1.0](https://github.com/mholzi/beatify/compare/v2.0.2...v2.1.0)

*Your speakers, your music service, your party — Beatify handles the rest!* 🎮

---
---

# Beatify v2.0.2 — Polish & Performance

**Release Date:** January 2026

Bug fixes and polish improvements from community feedback.

---

## 🐛 Bug Fixes

| Fix | Detail |
|-----|--------|
| Artist Bonus Display | Fixed `{points}` placeholder showing instead of actual bonus points (#51) |
| Streak Badges | Added numeric labels to analytics badges (🔥3+, 🔥🔥5+, 🔥🔥🔥7+) (#52) |
| Gold Badge | Fixed dark mode making badge text unreadable |
| HA Mobile App | Fixed popup blocked issue — sidebar now links directly to /beatify/admin (#40) |
| README | Fixed broken "See It In Action" anchor link (#43) |

---

## ⚡ Performance

| Improvement | Detail |
|-------------|--------|
| Round Transitions | Async metadata fetch reduces wait from ~2-3s to ~500ms (#42) |
| Player Joining | Parallel WebSocket broadcasts with debouncing for faster lobby updates (#41) |

---

## 🎨 UI Improvements

| Change | Detail |
|--------|--------|
| Reveal Screen | Reordered sections: Fun Facts → Artist → Your Result → All Guesses |
| Alle Tips Grid | Cards now span full container width |
| Onboarding | Added "Opening Beatify" and "Viewing Playlists" sections to README (#49) |

---

**Full Changelog:** [v2.0.1...v2.0.2](https://github.com/mholzi/beatify/compare/v2.0.1...v2.0.2)

---
---

# Beatify v2.0.1 — Bug Fix Release

**Release Date:** January 2026

Bug fixes for the v2.0.0 React & Reveal release.

---

## 🐛 Bug Fixes

| Fix | Detail |
|-----|--------|
| Early Reveal | Fixed phase transition when playing solo - analytics errors no longer block reveal |
| JavaScript | Fixed `ReferenceError: i18n` in early reveal toast |
| UI | Styled round-analytics section to match leaderboard pattern |

---

**Full Changelog:** [v2.0.0...v2.0.1](https://github.com/mholzi/beatify/compare/v2.0.0...v2.0.1)

---
---

# Beatify v2.0.0 — React & Reveal 🎭✨

**Release Date:** January 2026

The biggest Beatify update yet! Live emoji reactions, artist guessing challenge, smart early reveals, complete UI overhaul, and two new playlists with 389 songs.

---

## 🎭 Live Emoji Reactions — Feel the Vibe

Players can now react in real-time during the reveal phase with floating emoji reactions!

| Feature | Detail |
|---------|--------|
| Emojis | 😂 🔥 😮 👏 💀 |
| Animation | Float upward with fade-out |
| Visibility | All players see all reactions |
| Rate Limit | Prevents spam flooding |

Tap to react — watch the room's energy when that obscure 80s track stumps everyone! 🔥

---

## 🎤 Artist Challenge — Double the Fun

A new optional game mode that rewards knowing your artists:

| Setting | Detail |
|---------|--------|
| Mode | Off (default) / On in game setup |
| Bonus | +5 points per correct artist |
| Alt Names | Automatically accepted (e.g., "Prince" or "The Artist") |
| Lock-in | Artist selection locks after first guess |

Turn it on for music buffs who know their Bowie from their Bolan!

---

## ⚡ Early Reveal — No More Waiting

When all players have submitted their guesses, the round ends immediately:

| Scenario | Behavior |
|----------|----------|
| All guessed | Instant transition to reveal |
| Someone thinking | Timer continues normally |
| Player disconnects | Excluded from check |
| Artist mode on | Waits for both guesses |

Players see an "All guesses in!" toast — no more awkward waiting when everyone's locked in!

---

## 🎨 Complete UI Redesign

Every screen refreshed with a unified, mobile-first aesthetic:

| Screen | Key Changes |
|--------|-------------|
| Admin | Collapsible sections, compact controls, analytics icon in header |
| Lobbies | Unified layout, real-time player list, sticky Leave Game footer |
| Game | Card-section pattern, mobile-optimized, styled toggle buttons |
| Reveal | Compact layout, floating reactions centered, top-aligned views |

---

## 🎵 New Playlists — 389 Fresh Tracks

| Playlist | Songs | Theme |
|----------|-------|-------|
| One-Hit Wonders | 98 | "Take On Me", "Come On Eileen", "Tainted Love" and more one-time chart-toppers |
| Kölner Karneval | 291 | German Carnival classics — perfect for Carnival season! 🎉 |

---

## 📊 By the Numbers

| Metric | Value |
|--------|-------|
| Major Features | 4 |
| New Playlists | 2 (389 songs) |
| UI Screens Redesigned | 4 |
| Release Candidates | 14 |

---

**Full Changelog:** [v1.5.0...v2.0.0](https://github.com/mholzi/beatify/compare/v1.5.0...v2.0.0)

*Ready for the biggest party upgrade yet? Update now and feel the vibes!* 🎮
