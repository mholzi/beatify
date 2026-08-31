## Beatify v4.4.0-rc4 — "Keep What You Catch"

Songs you guess close enough now stay with you, and there is finally a way to play without paying for a music subscription. Four things that could spoil an evening are fixed.

> **Numbered 4.4.0, not 4.3.1.** The work began as `v4.3.1-rc1` and `rc2`, but a patch number promises bug fixes and this adds a game mechanic.

### 🎴 Keep what you catch

Guess a year close enough and the song pins to a row you keep for the rest of the game. It goes into the final standings and onto the share card.

### 🆓 A music service that costs nothing

Beatify can now play through `ytmusic_free`, a third-party Music Assistant provider that streams YouTube Music without a Premium account. Every service before this needed a paid plan.

Nothing had to be added to the catalogue for it. That provider keys tracks by the YouTube video id, and the id was already sitting in the YouTube Music link every song carries, so **6,935 of 7,786 songs are playable on it** the day it ships.

The provider is not part of Music Assistant and has to be installed there first. The wizard says so under the option.

Asked for by **@ipalomo**.

### 🏰 Disney in Spanish, twice

Two new playlists, because one would have been wrong. **Clásicos Disney (Castellano)** holds 64 songs in the Spanish of Spain; **Disney Latino** holds 54 in Latin American Spanish. The same film is often a different recording, a different singer and a different lyric in the two regions, and a party in Madrid and a party in Bogotá do not want the same one.

Both came in through the request button in the app.

### 🇮🇹 Italian trivia

Play in Italian and the song trivia now speaks Italian too. **1,289 songs** carry an Italian fun fact, and eight playlists are complete — among them Sanremo, Eurovision and Salsa y Merengue.

### 📺 What is fixed

The end screen fits. The winner's name stays inside the podium card, the award values stay inside their cards, and a two-player game shows two stands instead of three. Reported by **@boardnick0815** with a screencast.

Ten rounds means ten rounds. The cap used to do nothing once you picked more than one playlist: two playlists with a cap of ten played all 300 songs in them.

The final round announces itself again, including in games where a track turned out to be unavailable.

A reload no longer drops you out. The submit button no longer sticks when a reply is slow. Tidal plays without a stored link, resolved by name instead.

### ⚖️ Two unfair edges

The status endpoint no longer hands out the running round's answer, and the round deadline now applies to power-ups.

### 🎧 The catalogue

**55 playlists and 6,079 songs became 61 and 7,786.**

- **Salsa y Merengue, 531 songs.** Second largest in the catalogue. Latin America had fifty songs before this.
- **Two Spanish Disney playlists**, 118 songs between them.
- **The decade playlists contain only their decade.** Nineteen songs sat in the wrong one.

### 🙏 Thank you

To **@ipalomo** for asking for a way to play without a subscription, to **@boardnick0815** for the screencast that showed exactly what the end screen was doing, and to everyone who tapped the request button for a playlist. Keep them coming.
