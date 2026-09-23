## 4.7.4 — Unisono

Two fixes for the moment the party gets going: the rules hold no matter how the game was started, and the host can keep the mix they just built.

### 🎚️ Sudden Death holds, whichever button started the game

Only one of the two ways to start a game switched Sudden Death off when too few players had joined, and the admin page used the other one. The rule now lives in one place. A game started over the API also announces itself, so the TV and every phone leave the lobby while the speaker gets ready.

### 💾 Saving a library mix as a playlist works again

The button in the Library panel failed on every press and quietly ignored the popularity and genre filters. Both work now.

### 🧹 Underneath

Two tangled modules were pulled apart. 193 unused translation keys are gone from all six languages, and eight Harder Styles tracks that pointed at the wrong recording or a dead link now play the right song.

---

**67 playlists · 8,555 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
