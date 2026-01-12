<div align="center">

# Beatify

<img src="images/beatify-logo.png" alt="Beatify Logo" width="400">

### **The Party Game Your Smart Home Was Made For**

Turn any gathering into an unforgettable music trivia experience.
Guests scan, songs play, everyone competes. It's that simple.

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Version](https://img.shields.io/badge/Version-1.0.0-ff00ff?style=for-the-badge)](https://github.com/mholzi/beatify/releases)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

[**Get Started**](#-5-minute-setup) • [**See It In Action**](#-the-experience) • [**Install Now**](#-installation)

---

</div>

<br>

## What Is Beatify?

**Beatify is a multiplayer music year-guessing game that runs entirely on your Home Assistant.**

A song plays through your speakers. Everyone races to guess the release year. Points fly. Streaks build. Champions emerge.

No apps to download. No accounts to create. Just scan a QR code and play.

---

<br>

## Why Hosts Love Beatify

<table>
<tr>
<td width="50%" valign="top">

### Zero Friction Entry
Guests scan a QR code. That's literally it.

No "download this app" delays. No "create an account" friction. No "what's the WiFi password" chaos.

**10 seconds from scan to playing.**

</td>
<td width="50%" valign="top">

### Your Existing Setup
Works with whatever you already have:
- Sonos
- HomePod
- Chromecast
- Any Home Assistant media player

**No new hardware required.**

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Any Music Source
Spotify, Apple Music, YouTube Music, local files—if your Home Assistant can play it, Beatify can use it.

**Your playlists. Your vibe.**

</td>
<td width="50%" valign="top">

### Runs Locally
No cloud dependency. No subscription. No data leaving your network.

**Fast, private, reliable.**

</td>
</tr>
</table>

---

<br>

## The Experience

<div align="center">

### For Players

<!-- SCREENSHOT: Player's phone showing the year slider and album art -->
<img src="images/player-gameplay.png" alt="Player guessing screen" width="350">

*Slide to guess. Tap to submit. Pray you're right.*

</div>

**The Rush**
A song starts playing. The clock is ticking. You *know* this song... but was it '85 or '87?

**The Strategy**
Answer fast for bonus points. Hit a streak for multipliers. Feeling confident? Bet double-or-nothing.

**The Reveal**
The year drops. The room erupts. Someone nailed it. Someone was *way* off. Everyone's laughing.

<br>

<div align="center">

### For Hosts

<!-- SCREENSHOT: Admin setup screen with media player and playlist selection -->
<img src="images/admin-setup.png" alt="Admin setup screen" width="700">

*Select speakers. Pick playlists. Start the party.*

</div>

**Full Control**
Skip tracks. Adjust volume. Pause the game. End early if needed. All from your phone.

**Print the QR**
Physical QR code printout for the coffee table. Guests join themselves.

**Play Along**
Join as a player with admin controls. Compete and manage simultaneously.

---

<br>

## Game Features

<div align="center">

<!-- SCREENSHOT: Reveal screen showing correct year, fun fact, and scores -->
<img src="images/reveal-screen.png" alt="Round reveal with scores" width="600">

*The moment of truth. Every single round.*

</div>

### Scoring That Creates Drama

| Performance | Points | The Vibe |
|-------------|--------|----------|
| Exact year | 10 × speed bonus | **LEGENDARY** |
| Within 3 years | 5 × speed bonus | Solid! |
| Within 5 years | 1 × speed bonus | At least you tried |
| More than 5 off | 0 | Better luck next round |

### Speed Bonus
Submit instantly: **2x multiplier**
Submit at deadline: **1x multiplier**
Linear scale in between. Hesitation costs points.

### Streak Milestones
- **3 in a row:** +20 bonus points
- **5 in a row:** +50 bonus points
- **10 in a row:** +100 bonus points

Miss one? Streak resets. The pressure is real.

### Double or Nothing
Feeling confident? Toggle the bet before submitting.
Score points: **Double them.**
Score zero: **Lose it all.**

---

<br>

## The Finale

<div align="center">

<!-- SCREENSHOT: End game podium showing top 3 players with medals -->
<img src="images/podium-screen.png" alt="Winner podium" width="500">

*Glory. Bragging rights. Maybe a rematch.*

</div>

Full podium with medals. Personal stats. Best streaks. Bets won.
Everything you need to demand a rematch.

---

<br>

## 5-Minute Setup

### Step 1: Install (2 minutes)

**Via HACS (Recommended)**
```
HACS → ⋮ Menu → Custom Repositories
→ URL: https://github.com/mholzi/beatify
→ Category: Integration
→ Install "Beatify"
→ Restart Home Assistant
```

**Manual**
```bash
cd /config/custom_components
git clone https://github.com/mholzi/beatify.git beatify
# Restart Home Assistant
```

### Step 2: Configure (1 minute)

```
Settings → Devices & Services → Add Integration → "Beatify"
```

### Step 3: Play (instantly)

```
Open Beatify → Pick speakers → Pick playlist → Start → Share QR → Go!
```

<div align="center">

<!-- SCREENSHOT: QR code display with join URL -->
<img src="images/qr-lobby.png" alt="QR code lobby screen" width="400">

*Print it. Display it. Share it.*

</div>

---

<br>

## Creating Playlists

Beatify uses simple JSON playlists stored in `config/beatify/playlists/`.

```json
{
  "name": "80s Classics",
  "songs": [
    {
      "year": 1983,
      "uri": "spotify:track:4cOdK2wGLETKBW3PvgPWqT",
      "fun_fact": "Spent 8 weeks at #1"
    },
    {
      "year": 1985,
      "uri": "spotify:track:2374M0fQpWi3dLnB54qaLX",
      "fun_fact": "Written in just 10 minutes"
    }
  ]
}
```

**Playlist Tips:**
- Mix decades for variety
- Include recognizable songs (obscure = frustrating)
- Add fun facts for the reveal screen
- 10-20 songs per playlist works great

Sample playlists are included to get you started immediately.

---

<br>

## Multi-Language Support

Beatify speaks your guests' language.

- **English** — Full support
- **Deutsch** — Vollständige Unterstützung

Select during game setup. All players see the chosen language.

---

<br>

## Perfect For

| Event | Why It Works |
|-------|--------------|
| **House Parties** | Gets people off phones and into the moment |
| **Birthday Parties** | "Guess songs from your birth year" challenge |
| **Game Nights** | Adds music trivia to the rotation |
| **Family Gatherings** | Bridges generations through shared songs |
| **Team Building** | Competition that's actually fun |
| **Holiday Parties** | Creates memories, not awkward silences |

---

<br>

## Technical Details

### Requirements
- **Home Assistant** 2024.1+
- **Any media player entity** (Sonos, Chromecast, HomePod, etc.)
- **HACS** (recommended) or manual installation

### How It Works
- Native Home Assistant integration
- WebSocket-based real-time sync
- Local processing—no cloud required
- Session persistence for reconnection
- Up to 20+ concurrent players

### Architecture
```
Home Assistant
    └── Beatify Integration
            ├── Game State Manager
            ├── WebSocket Handler
            ├── Media Player Service
            └── Web UI (Admin + Player)
```

---

<br>

## FAQ

<details>
<summary><strong>How many players can join?</strong></summary>
<br>
Tested with 20+ players. Your WiFi is the only real constraint.
</details>

<details>
<summary><strong>Can someone join mid-game?</strong></summary>
<br>
Yes! Late joiners inherit the average score so they can compete fairly.
</details>

<details>
<summary><strong>What if the host disconnects?</strong></summary>
<br>
Game pauses automatically. Reconnect and continue exactly where you left off.
</details>

<details>
<summary><strong>What music services work?</strong></summary>
<br>
Anything your Home Assistant media player supports: Spotify, Apple Music, YouTube Music, local files, etc.
</details>

<details>
<summary><strong>Do players need to be on the same network?</strong></summary>
<br>
Yes, players need to access your Home Assistant instance. Works great on home WiFi.
</details>

<details>
<summary><strong>Can I customize the theme?</strong></summary>
<br>
The neon dark theme is built-in and looks stunning. Custom theming is on the roadmap.
</details>

---

<br>

## What's New

### v0.11 Highlights
- **Multi-language support** — English and German
- **Spectator dashboard** — Big-screen display for TV viewing
- **Session persistence** — Reconnect without losing progress
- **Sample playlists** — Start playing immediately

[View full changelog →](https://github.com/mholzi/beatify/releases)

---

<br>

## Troubleshooting

**Players can't connect?**
- Verify Home Assistant is accessible on your network
- Try IP address instead of hostname
- Ensure port 8123 is reachable

**Music won't play?**
- Check media player is online in Home Assistant
- Verify playlist URIs are valid
- Check Home Assistant logs for errors

**QR code won't scan?**
- Improve lighting on the display
- Try the "Print QR" feature for a physical copy
- Use a dedicated QR scanner app

---

<br>

## Contributing

Contributions welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-thing`)
3. Commit your changes (`git commit -m 'Add amazing thing'`)
4. Push to the branch (`git push origin feature/amazing-thing`)
5. Open a Pull Request

---

<br>

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<br>

<div align="center">

## Ready to Host?

The next great party moment is one QR scan away.

[**Install Beatify Now**](#5-minute-setup)

---

**Built for Home Assistant. Built for fun.**

[Report Bug](https://github.com/mholzi/beatify/issues) · [Request Feature](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions)

<br>

<sub>Made with ❤️ for the Home Assistant community</sub>

</div>
