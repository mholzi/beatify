## 4.8.5-rc2 — Hold the Intro

The intro round waits quietly now, the lobby says how long the music really plays, and one setting is safe behind a reverse proxy.

### 🎤 Intro rounds

- When the host picks an intro round, the last song no longer keeps playing under the waiting card.
- The countdown on the admin page holds until the round starts, like the one on the TV.
- The intro song stops after 15 seconds instead of running the whole round. The reveal plays it again.

Thanks to **@aenkieh** for the report.

### 🎉 Around the table

- With a short song length set, the lobby now says both numbers: "you hear 15 seconds of each song and get 30 to answer".
- A won bet reads "All-in bonus" in the points breakdown, at ×2, ×3 and ×5 alike.
- If the speaker you pick in the lobby can't play your music service, the admin goes back to the old speaker and says so above "Start game". Your other changes, like TTS or party lights, are kept.
- The same goes for a speaker switch in the middle of a game: a banner above the control bar says so and stays until you close it.
- Amazon Music on the wrong speaker now tells you to pick an Amazon Echo, not a Music Assistant speaker.

### 🔒 Companion login behind a proxy

If you turned on the Android Companion login bypass and reach Home Assistant through a reverse proxy (nginx, Traefik, Caddy), requests from the internet could pass as local. The bypass now refuses any proxied request. It stays off by default.

### 🎵 Playlist repairs

Broken links are fixed in Eurovision Winners, Sommerklassiker, Funk Carioca, American Classics, Movie & TV Soundtracks, One-Hit Wonders and Greatest Hits of All Time. Tidal players get Queen back in Greatest Hits, and YMCA plays the 1978 original.

---

**70 playlists · 8,724 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
