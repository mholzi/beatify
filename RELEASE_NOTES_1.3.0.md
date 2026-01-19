# Beatify v1.3.0 — Steal the Show 🥷

**Release Date:** January 2026

Get ready to outplay, outsmart, and outsteal your friends! This release introduces game-changing power-ups, end-game awards that celebrate every play style, and rock-solid reliability improvements that keep the party going all night long.

---

## 🥷 Steal Power-Up — Trust No One

The most requested feature is here! Build a streak and steal your way to victory:

**How it works:**
1. Get **3 correct guesses in a row** (within scoring range)
2. A glowing "Steal Available" indicator appears
3. Click the steal button to see who has already submitted
4. Choose your target and copy their answer instantly!

| Scenario | Result |
|----------|--------|
| You steal a perfect guess | You get the same points they would |
| You steal a wrong answer | You share their fate! |
| Someone steals from you | Your answer still counts normally |

**Strategic depth:**
- Use it early when answers cluster, or save it for when you're stumped
- The steal target list shows who submitted (but not their answers!)
- Both stealer and victim see the relationship revealed at the end

Translations included for English and German. The mind games begin! 🎭

---

## 🏆 End-Game Superlatives — Everyone's a Winner

Because first place isn't the only way to shine! After the final round, special awards celebrate unique achievements:

| Award | What It Takes | Badge |
|-------|---------------|-------|
| ⚡ **Speed Demon** | Fastest average submission time | "X.Xs avg" |
| 🔥 **Hot Streak** | Longest scoring streak (min 3) | "X in a row" |
| 🎲 **Risk Taker** | Most bets placed (min 3) | "X bets" |
| 💪 **Clutch Player** | Highest score in final 3 rounds | "X pts in final 3" |
| 🎯 **Close Calls** | Most guesses within 1 year | "X close guesses" |

Awards appear with staggered animations on both player devices and the TV dashboard. Even the slowest guesser might be the ultimate Risk Taker!

---

## ⭐ Song Difficulty Rating — Know What You're Up Against

See how hard each song really is based on how everyone has played it:

| Stars | Accuracy | Meaning |
|-------|----------|---------|
| ⭐⭐⭐⭐ | 75%+ | Easy — Most players nail it |
| ⭐⭐⭐ | 50-75% | Medium — Solid challenge |
| ⭐⭐ | 25-50% | Hard — Only experts score |
| ⭐ | <25% | Extreme — Nearly impossible! |

- Displayed during the REVEAL phase after each round
- Ratings improve as more games are played
- "Not enough data yet" shown for new songs

Finally know if that obscure 1967 B-side was actually guessable!

---

## 🔧 Reliability Improvements — The Party Never Stops

Major under-the-hood improvements to keep your game running smoothly:

### Media Player Resilience
- **Pre-flight check** — Speakers are tested before each round to catch sleepy Sonos devices
- **Smart retry logic** — If a song fails to play, the game tries up to 3 times with delays
- **Graceful pause** — Instead of crashing, the game pauses and waits for the host when media fails
- **Metadata sync** — Waits for Spotify/Sonos to update before showing song info (no more mismatched reveals!)

### WebSocket Stability
- **Keepalive pings** — Prevents connection timeouts during long reveal phases
- **Non-blocking I/O** — Fixed potential freezes during network operations

### Playlist Management
- **Auto-update** — Bundled playlists automatically refresh when a new version has better data
- **Version tracking** — Each playlist now has a version number for smarter updates

---

## 🎨 Visual Polish

### Unified Badge Design
All song information badges (charts, certifications, awards) now share a consistent design:
- Centered layout in a single row
- Pill-shaped badges with subtle borders
- Distinct colors: blue for charts, amber for certifications, purple for awards
- Icons for quick recognition (📈 🏆 🎵)

### Dark Mode Fixes
- Fixed button text color in card sections (no more dark text on blue buttons!)
- Safari desktop click handling for bet toggle now works properly

### Button Spacing
- Removed redundant margins causing double-spacing on icon buttons

---

## 🐛 Bug Fixes

- **Runaway song loop** — Fixed infinite retry loop that could exhaust entire playlist in seconds
- **Timer self-cancel** — Fixed race condition where timer task could cancel itself
- **Safari desktop** — Fixed bet toggle not responding to clicks when playing as admin
- **Metadata mismatch** — Fixed wrong song info showing during reveal (e.g., "We Are The World" metadata for "Twist and Shout")

---

## 📋 Technical Notes

### Breaking Changes
None — full backward compatibility with v1.2.x game saves and statistics.

### New Dependencies
None added.

### Minimum Requirements
- Home Assistant 2024.1.0 or later
- A Spotify-connected media player (Sonos, Chromecast, etc.)

---

## 🙏 Thank You

Special thanks to everyone who reported bugs, suggested features, and helped test the beta releases. Your feedback made this release possible!

**Full Changelog:** https://github.com/mholzi/beatify/compare/v1.2.0...v1.3.0

---

*Ready to steal some answers? Update now and let the games begin!* 🎮
