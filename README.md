# Beatify

<div align="center">

<img src="docs/images/beatify-logo.png" alt="Beatify" width="400">

### **Turn Your Living Room Into a Music Game Show**

The multiplayer music year-guessing party game that runs on your Home Assistant.
No apps. No downloads. Just scan, play, and party.

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/Version-0.11.2-ff00ff?style=for-the-badge)](https://github.com/mholzi/beatify/releases)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

**[Get Started](#-quick-start)** | **[See It In Action](#-how-it-works)** | **[Install Now](#-installation)**

---

</div>

## The Party Game Your Smart Home Was Made For

Remember the last time everyone at your party was actually *present*? Not scrolling, not distracted—just laughing, competing, and having fun together?

**Beatify makes that happen.**

A song plays through your speakers. Everyone grabs their phone. The race is on to guess the release year. Points fly. Bets are placed. Champions are crowned. And somewhere between "I *know* this song!" and "No way that's from the 80s!", something magical happens:

**People connect.**

---

## Why Beatify?

<table>
<tr>
<td width="50%">

### Zero Friction
- **Scan a QR code. That's it.** No app downloads, no accounts, no waiting.
- Works on any phone, tablet, or browser
- Guests playing in under 10 seconds

</td>
<td width="50%">

### Instant Fun
- **Music plays. Tension builds.** Everyone's racing against the clock.
- Real-time scoring keeps competition fierce
- Dramatic reveals that get everyone cheering (or groaning)

</td>
</tr>
<tr>
<td width="50%">

### Your Music, Your Speakers
- **Plays through your existing setup.** Sonos, HomePod, Chromecast, anything.
- Use any Spotify, Apple Music, or local media files
- Create playlists that match your crowd

</td>
<td width="50%">

### Built for Home Assistant
- **Native integration.** Not a hack, not a workaround.
- Leverages your smart home infrastructure
- Runs locally—fast, private, reliable

</td>
</tr>
</table>

---

## How It Works

```
1. HOST opens Beatify on Home Assistant
2. HOST picks speakers + playlists, hits "Start Game"
3. QR CODE appears—guests scan with their phones
4. SONG PLAYS through your speakers
5. EVERYONE GUESSES the release year (before time runs out!)
6. SCORES REVEALED—watch the leaderboard shuffle
7. REPEAT until a champion emerges
8. CELEBRATE (responsibly)
```

**That's the whole thing.** No complicated setup. No technical knowledge required for guests. Just pure, competitive fun.

---

## Features That Make The Difference

### The Game

| Feature | What It Does |
|---------|--------------|
| **Smart Scoring** | Closer guesses = more points. Exact year? Maximum glory. |
| **Speed Bonus** | Quick answers earn extra points. No more stalling! |
| **Streak Multiplier** | Stay hot, stack bonuses. Miss one? Start over. |
| **Betting System** | Feeling confident? Double down and risk it all. |
| **Late Join** | Latecomers jump in mid-game with fair scoring. |

### The Experience

| Feature | What It Does |
|---------|--------------|
| **Live Leaderboard** | Real-time rankings that update after every round |
| **Animated Reveals** | Dramatic score announcements with smooth animations |
| **Neon Party Theme** | Gorgeous dark mode aesthetic that looks stunning |
| **Multi-Language** | English and German—more languages coming |
| **Mobile-First Design** | Buttery smooth on any device |

### The Control

| Feature | What It Does |
|---------|--------------|
| **Admin Controls** | Skip songs, adjust volume, pause anytime |
| **Spectator Dashboard** | Big-screen display for TV viewing |
| **Session Persistence** | Reconnect if you drop—your progress is saved |
| **Flexible Playlists** | JSON-based, easy to create and share |

---

## Quick Start

### 1. Install via HACS (2 minutes)

```
HACS → Menu (⋮) → Custom Repositories
→ Add: https://github.com/mholzi/beatify
→ Category: Integration
→ Install "Beatify"
→ Restart Home Assistant
```

### 2. Set Up (1 minute)

```
Settings → Devices & Services → Add Integration → "Beatify"
```

### 3. Play (immediately)

```
Open Beatify → Pick speakers → Pick playlist → Start Game → Share QR → GO!
```

**Total time from zero to party: under 5 minutes.**

---

## Installation

### Requirements

- **Home Assistant** 2024.1 or newer
- **Any media player** entity (Sonos, Chromecast, HomePod, etc.)
- **HACS** (recommended) or manual install

### Option A: HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click **⋮** menu → **Custom repositories**
3. Add URL: `https://github.com/mholzi/beatify`
4. Select category: **Integration**
5. Search "Beatify" and click **Install**
6. **Restart Home Assistant**
7. Add the integration via Settings → Devices & Services

### Option B: Manual

```bash
cd /config/custom_components
git clone https://github.com/mholzi/beatify.git beatify
# Restart Home Assistant
```

---

## Creating Playlists

Beatify uses simple JSON playlists. A sample is included to get you started.

**Location:** `config/beatify/playlists/`

**Format:**
```json
{
  "name": "80s Hits",
  "songs": [
    {
      "year": 1983,
      "uri": "spotify:track:4cOdK2wGLETKBW3PvgPWqT",
      "fun_fact": "This song spent 8 weeks at #1"
    }
  ]
}
```

**Tips for great playlists:**
- Mix different decades for variety
- Include recognizable songs (obscure = frustrating)
- Add fun facts for reveal screens
- 10-20 songs per playlist is ideal

---

## Scoring System

| Accuracy | Points | Vibe |
|----------|--------|------|
| Exact year | 20 | **LEGENDARY** |
| 1 year off | 18 | So close! |
| 2 years off | 16 | Nice! |
| 3 years off | 14 | Not bad |
| 4+ years off | 12→0 | Keep trying |
| No answer | 0 | Wake up! |

**Bonuses:**
- **Speed Bonus:** +3 pts for answering in the first 25% of time
- **Streak Bonus:** +5 pts per round when you're on a 3+ correct streak
- **Bet Won:** 2x your round score (bet lost = 0 pts)

---

## Perfect For

- **House Parties** — Get people off their phones and into the game
- **Birthday Parties** — Who knows their birth year's hits?
- **Game Nights** — Add music trivia to your rotation
- **Family Gatherings** — Bridge generations through music
- **Corporate Events** — Team building that's actually fun
- **Holiday Parties** — Create memories, not awkward silences

---

## FAQ

<details>
<summary><strong>How many players can join?</strong></summary>

No hard limit. We've tested 20+ players without issues. Your WiFi is the constraint.
</details>

<details>
<summary><strong>Can someone join mid-game?</strong></summary>

Yes! Late joiners get fair average scores for missed rounds so they can compete.
</details>

<details>
<summary><strong>What if the host disconnects?</strong></summary>

Game pauses automatically. Reconnect and pick up where you left off.
</details>

<details>
<summary><strong>What music services work?</strong></summary>

Anything your Home Assistant media player supports: Spotify, Apple Music, YouTube Music, local files, etc.
</details>

<details>
<summary><strong>Is an internet connection required?</strong></summary>

Only for streaming music. The game itself runs entirely on your local network.
</details>

<details>
<summary><strong>Can I customize the look?</strong></summary>

The Neon Party theme is built-in and looks amazing. Custom theming is on the roadmap.
</details>

---

## What's New in v0.11

### Multi-Language Support
- **English and German** fully supported
- Language selector on admin setup
- All UI text translated

### Quality of Life
- **Spectator Dashboard** — Big-screen display for TV/iPad
- **Session Persistence** — Reconnect without losing progress
- **Bundled Playlists** — Sample playlists included out of the box

---

## Troubleshooting

**Players can't connect?**
- Check HA is accessible on your network
- Try IP address instead of hostname
- Ensure port 8123 is open

**Music not playing?**
- Verify media player is online
- Check playlist URIs are valid
- Look at HA logs for errors

**QR code won't scan?**
- Improve lighting on display
- Zoom in on the code
- Use a QR scanner app

---

## Contributing

We welcome contributions!

1. Fork the repo
2. Create feature branch (`git checkout -b feature/cool-thing`)
3. Commit changes (`git commit -m 'Add cool thing'`)
4. Push (`git push origin feature/cool-thing`)
5. Open a Pull Request

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

### Ready to transform your next gathering?

**[Install Beatify Now](#-installation)**

---

**Built for Home Assistant. Built for fun.**

[Report Bug](https://github.com/mholzi/beatify/issues) · [Request Feature](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions)

</div>
