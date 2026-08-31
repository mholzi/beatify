## Beatify v4.4.0-rc2 — "Keep What You Catch"

Songs you guess close enough now stay with you. Four things that could spoil an evening are fixed.

> **Numbered 4.4.0, not 4.3.1.** The work began as `v4.3.1-rc1` and `rc2`, but a patch number promises bug fixes and this adds a game mechanic.

### 🎴 Keep what you catch

Guess a year close enough and the song pins to a row you keep for the rest of the game. It goes into the final standings and onto the share card.

### 📺 What is fixed

The end screen fits. The winner's name stays inside the podium card, the award values stay inside their cards, and a two-player game shows two stands instead of three. Reported by **@boardnick0815** with a screencast.

Ten rounds means ten rounds. The cap used to do nothing once you picked more than one playlist: two playlists with a cap of ten played all 300 songs in them.

The final round announces itself again, including in games where a track turned out to be unavailable.

A reload no longer drops you out. The submit button no longer sticks when a reply is slow. Tidal plays without a stored link, resolved by name instead.

### ⚖️ Two unfair edges

The status endpoint no longer hands out the running round's answer, and the round deadline now applies to power-ups.

### 🎧 The catalogue

**55 playlists and 6,079 songs became 59 and 7,671.**

- **Salsa y Merengue, 534 songs.** Second largest in the catalogue. Latin America had fifty songs before this.
- **The decade playlists contain only their decade.** Nineteen songs sat in the wrong one.
- **Seventy-seven fun facts** stopped naming a year that contradicted the answer.
- **Eighteen more provider links** across Apple, YouTube Music and Deezer.
