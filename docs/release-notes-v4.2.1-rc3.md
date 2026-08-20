## 4.2.1-rc3 — Si Gioca in Italiano

Beatify speaks Italian now, from the setup dialog to the voice that announces the winner. And the catalogue has something to say in it: two Italian playlists arrive together, one of them every Sanremo winner since the festival began.

### 🇮🇹 The whole game in Italian

Pick Italian in the setup wizard and everyone gets it — the lobby, the player screens, the scoreboard, the spoken announcements. Home Assistant's own setup dialog is translated too, so it starts in Italian before the game does. Song trivia and award names come through in Italian as well, which is what makes a round feel like it was written for the room rather than translated at it.

### 🔌 Removing the integration really removes it

If you deleted Beatify from Home Assistant and added it back, it used to remember the speakers you had picked the first time. That was fine until those speakers no longer existed: the game refused to start and there was no obvious way to tell it to forget. A fresh install now really is fresh. Thanks to **@proffalken** for reporting it, and for describing it precisely enough to find in one go.

### 🎉 Two Italian playlists

**Musica Italiana** brings 114 songs from the 1960s to the 2000s — the cantautori, the summer hits, the ones every Italian party sings along to. **Sanremo: I Vincitori** holds every winning song of the festival from 1951 to 2026, with the years taken from the official Albo d'oro rather than from streaming metadata, which likes to date a reissue instead of the song.

### 🙏 Thank you

To **@proffalken** for a bug report that arrived with everything needed to fix it. And to everyone who asked for Italian in one way or another — the catalogue had Italian music long before the interface could say a word of it.

---

**57 playlists · 6,261 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
