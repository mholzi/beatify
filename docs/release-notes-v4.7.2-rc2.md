## 4.7.2-rc2 — Hold That Thought

Three fixes for the moments when the host steps away from the game for a second.

### ⏸️ A pause stays a pause

If the host paused the game because the pizza arrived and then locked their phone, the game used to carry on by itself as soon as the phone woke up, with nobody at the table. It now waits until the host taps resume. The round clock stops too: after a long break the round picks up with the time it had left, instead of ending on the spot and costing everyone the round.

### 🎬 A late tap on the intro card no longer ends the round

If the host was a moment slow to confirm an intro round, the round could end before a single note had played and everyone scored nothing. The song now starts first, and the timer runs from there.

### 🔒 A safer setup summary

The summary at the end of setup now shows speaker and playlist names strictly as plain text, whatever a device on the network calls itself.

---

**66 playlists · 8,468 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
