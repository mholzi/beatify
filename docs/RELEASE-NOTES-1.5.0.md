# Beatify v1.5.0 — Data & Speed 📊⚡

**Release Date:** January 2026

Beatify gets smarter and faster! This release introduces a comprehensive analytics dashboard for game hosts, major mobile performance improvements, and enhanced Music Assistant support. Track your party stats, enjoy smoother gameplay, and let the good times roll!

---

## 📊 Admin Analytics Dashboard — Know Your Party

A brand new analytics page gives game hosts deep insights into gameplay patterns:

**Key Features:**
- Game statistics with trends (total games, avg duration, player counts)
- Date range filtering (7 days, 30 days, 90 days, all time)
- Top 5 playlist rankings by popularity
- Games over time chart with smart granularity
- Error monitoring with health status indicators
- Per-song statistics (guess rates, difficulty scores)

| Metric | What You See |
|--------|--------------|
| Games Played | Total count with trend vs previous period |
| Avg Duration | How long your parties typically last |
| Top Playlists | Which music gets picked most often |
| Error Rate | System health at a glance |
| Song Stats | Which songs stump players |

Access it from the admin panel — finally see which songs are the crowd favorites!

---

## ⚡ Mobile Performance — Smooth Like Butter

Major optimizations make Beatify fly on mobile devices:

**What's New:**
- Lazy loading for the leaderboard (loads when you scroll to it)
- Virtual scrolling for games with 15+ players
- Smart animation quality based on your device capabilities
- 53% smaller JavaScript bundles
- Service worker caching for instant repeat visits

| Device Tier | Animation Level |
|-------------|-----------------|
| High (flagship) | Full effects, all animations |
| Medium | Reduced particles, standard transitions |
| Low (older phones) | Minimal effects, tap to skip |

The party runs smoother than ever — even on grandma's old tablet!

---

## 🎵 Music Assistant — Better Together

Improved integration for Music Assistant media players:

| Feature | Detail |
|---------|--------|
| Native Playback | Uses `music_assistant.play_media` service for reliability |
| Visual Badge | "Music Assistant" badge on compatible players |
| Smart Detection | Detected by integration, not entity naming |

If you're using Music Assistant, playback is now more reliable than ever.

---

## 🎨 UI Polish

Small touches that make a big difference:

**Styled Confirmation Dialogs:**
- No more ugly browser `confirm()` popups
- Consistent dark-themed modals across all platforms
- Works for: End Game, New Game, Leave Game, Steal Target

**Game Settings Display:**
- Player lobby shows current settings (e.g., "10 rounds • Normal")
- No more guessing what the admin configured

**Admin Flow:**
- Automatic redirect to setup page when game ends
- Better error messages when game fails to start

---

## 🔧 Under the Hood

**Cache Busting:**
- Static assets now include version query strings
- No more "clear your cache" troubleshooting after updates

**Internationalization:**
- All new features fully translated (EN, DE, ES)
- Confirmation modal text properly localized

---

## 📋 Technical Notes

### Upgrade Path
1. Restart Home Assistant to load new backend code
2. Clear browser cache once to get new service worker
3. No breaking changes — existing games and playlists preserved

### Analytics Data
- Stored locally in JSON format
- 90-day detailed retention, monthly summaries after
- Rate limited API (30 req/min)

### Service Worker
- Caches critical assets with Cache-First strategy
- Excludes WebSocket and API calls
- Auto-updates when new version deployed

---

## 📊 By the Numbers

| Metric | Value |
|--------|-------|
| Epics Completed | 2 (Analytics, Performance) |
| Bundle Size Reduction | 53% |
| New Dashboard Charts | 3 |
| Languages Supported | 3 (EN, DE, ES) |
| Alpha Releases | 28 |

---

**Full Changelog:** https://github.com/mholzi/beatify/compare/v1.4.0...v1.5.0

---

*Ready to see your party stats? Update now and start tracking!* 🎮
