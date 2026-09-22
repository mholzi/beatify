## 4.7.4-rc1 — Unisono

Two fixes where Beatify was doing the same thing twice and doing it differently, plus the cleanup that uncovered one of them.

### 🎚️ Sudden Death now applies whichever button started the game

A game can be started from the admin page or over the API, and only one of the two turned Sudden Death off when too few players had joined. The rule now lives in one place, so it holds either way. The same move fixed the reverse gap: a game started over the API left the TV and every phone on the lobby view for the ten to fifteen seconds the speaker needs, because only the other path announced the start.

### 💾 Saving a library mix as a playlist works again

The button in the Library panel raised a server error on every press, so "generate a mix from my own music and keep it" was unusable. It also quietly ignored the popularity and genre filters; both now reach the generator.

### 🧹 Underneath

Two modules that could not import each other have been untangled, which is how the crash above came to light. 193 translation keys that nothing referenced are gone from all six languages.
