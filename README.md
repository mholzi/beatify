# 🎵 Beatify

<div align="center">

![Beatify Logo](https://img.shields.io/badge/Beat-ify-ff00ff?style=for-the-badge&labelColor=00f5ff&logo=music&logoColor=white)

**The Ultimate Music Year-Guessing Party Game for Home Assistant**

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11+-41BDF5?style=flat-square&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=flat-square)](https://hacs.xyz/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.9.1-blue?style=flat-square)](https://github.com/mholzi/beatify/releases)

*Turn any gathering into an epic music trivia showdown!*

[Features](#-features) • [Installation](#-installation) • [How to Play](#-how-to-play) • [Screenshots](#-screenshots) • [FAQ](#-faq)

</div>

---

## 🎉 What is Beatify?

Beatify transforms your Home Assistant setup into a **multiplayer music party game** where players compete to guess the release year of songs. It's like having a professional game show host in your living room!

> 🎧 A song plays... 🤔 Players guess the year... 🏆 Points are awarded... 🎊 Champions are crowned!

Perfect for:
- 🏠 **House parties** - Get everyone off their phones and into the game!
- 🎂 **Birthday celebrations** - Who knows their era best?
- 🍻 **Game nights** - Add music trivia to your rotation
- 👨‍👩‍👧‍👦 **Family gatherings** - Bridge generations through music
- 🎄 **Holiday events** - Create lasting memories

---

## ✨ Features

### 🎮 Core Gameplay
- **Instant Join via QR Code** - Guests scan and play in seconds, no app downloads!
- **Real-time Multiplayer** - Everyone plays simultaneously on their own devices
- **Smart Scoring System** - Accuracy matters! Closer guesses = more points
- **Speed Bonuses** - Quick thinkers get rewarded
- **Streak Multipliers** - Stay hot and watch your score soar!

### 🎲 Betting System
- **High-Risk, High-Reward** - Feeling confident? Double down!
- **Dice Indicators** - See who's betting in real-time
- **Dramatic Reveals** - Watch bets pay off (or backfire spectacularly!)

### 🏆 Competition Features
- **Live Leaderboard** - Real-time rankings keep the tension high
- **Animated Standings** - Watch players rise and fall after each round
- **Final Podium** - Celebrate the top 3 in style
- **Personal Stats** - Track your accuracy across rounds

### 🎨 Neon Party Mode Theme
- **Stunning Dark Mode** - Gorgeous neon aesthetics that pop
- **Celebration Animations** - Confetti, glows, and party vibes
- **Responsive Design** - Looks amazing on any screen size
- **Accessibility First** - Reduced motion options available

### 🛠️ Host Controls
- **Admin Control Bar** - Skip songs, adjust volume, manage the game
- **Pause & Resume** - Life happens, the game waits
- **Flexible Playlists** - Use any Music Assistant playlist
- **Late Join Support** - Latecomers can jump in mid-game

---

## 📦 Installation

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Home Assistant | 2025.11+ | Core platform |
| Music Assistant | 2.4+ | For music playback |
| HACS | Latest | Recommended for easy install |

### Option 1: HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click the **⋮** menu → **Custom repositories**
3. Add: `https://github.com/mholzi/beatify`
4. Select category: **Integration**
5. Find "Beatify" and click **Install**
6. **Restart Home Assistant**

### Option 2: Manual Installation

```bash
# Navigate to your config directory
cd /config/custom_components

# Clone the repository
git clone https://github.com/mholzi/beatify.git beatify

# Restart Home Assistant
```

### Setup

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for **"Beatify"**
4. Follow the setup wizard
5. Access the admin panel from the sidebar!

---

## 🎮 How to Play

### For the Host

1. **Open Beatify** from the Home Assistant sidebar
2. **Select a media player** (your speakers/TV)
3. **Choose playlists** to pull songs from
4. **Click "Start Game"** to create a lobby
5. **Share the QR code** with your guests
6. **Press "Start Game"** when everyone's ready!

### For Players

1. **Scan the QR code** with your phone camera
2. **Enter your name** to join the lobby
3. **Wait for the host** to start the game
4. When a song plays:
   - **Listen carefully** 🎧
   - **Slide to select a year** 📅
   - **Hit Submit** before time runs out! ⏱️
   - **Optional: Place a bet** to double your points! 🎲
5. **Watch the reveal** and see how you scored!
6. **Repeat** until a champion emerges! 🏆

### Scoring

| Result | Base Points | Notes |
|--------|-------------|-------|
| Exact year | 20 pts | 🎯 Perfect! |
| 1 year off | 18 pts | So close! |
| 2 years off | 16 pts | Great guess! |
| 3 years off | 14 pts | Not bad! |
| 4+ years off | Decreasing | Keep trying! |
| No submission | 0 pts | 😴 Wake up! |

**Bonuses:**
- ⚡ **Speed Bonus**: Submit in first 25% of time = +3 pts
- 🔥 **Streak Bonus**: 3+ correct in a row = +5 pts per round
- 🎲 **Bet Won**: Double your round score!

---

## 📸 Screenshots

<div align="center">

| Player View | Reveal Screen | Leaderboard |
|:-----------:|:-------------:|:-----------:|
| Guess the year! | See the results! | Who's winning? |

*Screenshots coming soon - the game looks even better in person!*

</div>

---

## 🔧 Configuration

### Admin Settings

Access advanced settings through the integration configuration:

| Setting | Default | Description |
|---------|---------|-------------|
| Round Timer | 30s | Time to submit guesses |
| Rounds per Game | 10 | Songs per game session |
| Year Range | 1960-2024 | Selectable year range |

### Playlist Tips

- 🎵 **Mix eras** for maximum challenge
- 🌍 **Include variety** - rock, pop, disco, hip-hop
- 🎤 **Famous songs work best** - recognizable but not too obvious
- ⏱️ **30-60 second clips** are ideal

---

## ❓ FAQ

<details>
<summary><b>Can players join mid-game?</b></summary>

Yes! Late joiners receive average points for missed rounds, so they're not too far behind.
</details>

<details>
<summary><b>What happens if the host disconnects?</b></summary>

The game pauses automatically and resumes when the host reconnects. Player progress is preserved!
</details>

<details>
<summary><b>How many players can join?</b></summary>

There's no hard limit! We've tested with 20+ players. Your WiFi is the only constraint.
</details>

<details>
<summary><b>Does it work without Music Assistant?</b></summary>

Currently, Music Assistant is required for playlist management and playback. We may add more sources in the future!
</details>

<details>
<summary><b>Can I customize the theme?</b></summary>

The Neon Party Mode theme is built-in. Custom theming may come in future updates!
</details>

---

## 🛠️ Troubleshooting

### Common Issues

**"Music Assistant not found"**
- Ensure Music Assistant is installed and showing as "Loaded"
- Restart Home Assistant after installing MA

**Players can't connect**
- Check that your HA instance is accessible on your network
- Try the direct IP URL instead of hostname
- Ensure port 8123 (or your custom port) is accessible

**Songs not playing**
- Verify your media player is online and working
- Check Music Assistant can play to that device directly
- Look for errors in Home Assistant logs

**QR code not scanning**
- Ensure good lighting on the screen
- Try zooming in on the QR code
- Use a QR scanner app if camera doesn't work

---

## 🚀 What's New in v0.9.0

### 🎨 Epic 9: UX Design Overhaul Complete!

This release brings the **Neon Party Mode** theme to life:

- ✅ **Dark mode everywhere** - Admin page now matches the party vibe
- ✅ **Polished animations** - Smoother, more satisfying interactions
- ✅ **Better betting UX** - Clear indicators for who's feeling lucky
- ✅ **Player result cards** - See everyone's guesses on reveal
- ✅ **Improved layouts** - Everything in the right place
- ✅ **Accessibility improvements** - Reduced motion support

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Clone the repo
git clone https://github.com/mholzi/beatify.git
cd beatify

# Run tests
pytest tests/

# Lint code
ruff check custom_components/beatify/
```

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built for [Home Assistant](https://www.home-assistant.io/) - the best smart home platform
- Powered by [Music Assistant](https://music-assistant.io/) - for seamless music playback
- Inspired by countless game nights and the joy of music trivia

---

<div align="center">

**Made with 🎵 and ❤️ for music lovers everywhere**

[Report Bug](https://github.com/mholzi/beatify/issues) • [Request Feature](https://github.com/mholzi/beatify/issues) • [Discussions](https://github.com/mholzi/beatify/discussions)

</div>
