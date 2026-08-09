## Beatify v4.2.0 — "Mix & Match"

The biggest release since the New Look. Build a playlist on the spot from whatever tags you feel like playing, switch on an elimination round that keeps last place honest, and run a party night that starts faster and falls over less.

### 🎛️ Build your own set in the picker

The playlist picker has a new **Mix** tab. Pick any combination of decade, style, region and special tags, choose 30, 50 or 100 songs, and Beatify assembles a de-duplicated set on the spot. Save it as a community playlist in one tap, or just start playing. The mix flows straight on into the setup wizard.

The setup screen also offers a suggestion of the season — Carnival, Eurovision, World Cup, Summer — as a dismissible chip that adds the matching playlist in a single tap.

### ☠️ Sudden Death

An opt-in elimination format. From round two on, the surviving player with the lowest round score is out, and the last one standing wins. A tie for last goes to whoever answered slowest. It needs at least three players, arms either in the setup wizard or live from the reveal screen, and the TV shows an "OUT" takeover for whoever just went.

### 🎮 Six switches that change how a night plays

All optional, all off by default. Turn on the ones that suit your group.

- **Finale ×2** doubles the accuracy score in the final round, so a late gap is still winnable, and a tie for first goes to a one-round playoff instead of a shared trophy.
- **Comeback token** hands the bottom third of players a Steal after the halfway round — the power-up finally lands where it changes something.
- **Ramp-up ordering** sorts the songs into a difficulty arc, easy at the start and hard at the finish, using the per-song stats Beatify already keeps.
- **Difficulty-scaled betting** pays ×2 on an easy song, ×3 on normal and ×5 on hard, instead of a flat ×3 that made betting on a hard track strictly bad play.
- **Sabotage** lets a player cut or freeze somebody else's timer.
- **Streak-Shield** absorbs one wrong answer without breaking the streak, including a wrong answer caused by a Sabotage. It saves the run, not the points — the absorbed round still pays no streak bonus, and the reveal names the streak it rescued.

Crowd-Court now also resolves the moment everybody has voted, instead of sitting out the full window while five people stare at a screen.

### ⚖️ Scoring that matches how people actually play

The speed multiplier holds its full value through an opening grace window before it starts to decay, so taking a second to actually recognise the song no longer costs you the bonus.

The movie quiz became winner-takes-all like the artist challenge — only the fastest correct guess earns the +5. The old second- and third-place tiers let one fast phone sweep every round in a big group.

### 🔊 Speakers and playback

- **The speaker picker no longer offers the native twin of a Music Assistant speaker.** Picking the twin broke playback with a UPnP Error 800 and paused the game. The twin is hidden now, a previously saved pick is remapped to its Music Assistant counterpart, and the healing runs again at game start.
- **A playback timeout no longer ends the game.** When Music Assistant took longer than expected to hand over a track, the whole session used to stop. It recovers instead.
- **A round no longer starts when Music Assistant never actually took the speaker**, and a round no longer depends on its own timer task, or on an open browser, to end. Both were ways a night could stall without anyone seeing why.
- **The first round starts faster** — the media player service is pre-warmed during the lobby.
- **Busy rooms stay smooth.** Game start no longer re-parses the playlist on the event loop, in-round broadcasts are debounced, and the leaderboard payload is slimmer.

### 📱 Your setup follows you between devices

- **You stay logged in.** A refresh cookie that was never renewed logged everyone out thirty days after their first sign-in.
- **The speaker picked on one device is the speaker the other one uses.** A phone that chose the dining room and a laptop that still remembered the kitchen used to disagree, and the laptop won. The server's copy settles it now.
- **The setup wizard stops opening on a device that is already configured.**
- **The home screen names the speaker** it is about to play through, instead of leaving you to guess.

### ↺ Reset means reset

Reset used to look broken from both ends. It cleared the phone, but the copy of your setup on Home Assistant survived and was read straight back, so you landed on the same ready-to-host screen. Once that was fixed, the page still would not reload by itself if the browser stalled on the way out. Both are closed: Reset drops the setup on the server too, and reloads regardless of what any cleanup step is doing.

Worth knowing before you press it — Reset clears the setup for the whole household, not just the device in your hand.

### 🧹 Under the hood

- **Debug logging no longer cripples the integration.** Turning on debug for `custom_components.beatify` used to make it unusable, which is a cruel joke for anyone trying to report a bug.
- **Home Assistant stopped warning about Beatify on every served page.** The asset-fingerprint lookup was doing its file scan on the event loop precisely when the instance was already busy. Thanks to **@pwhh20**, who spotted it while reporting something else entirely.
- **The admin can no longer boot into an empty page**, and it no longer renders blank while a game sits in the lobby.
- **Stale playlist copies** left behind at a former path are cleaned up.
- **The lobby shows the round duration the server is really counting**, not the one the client hoped for.
- Roughly forty smaller review findings, plus bigger tap targets, trapped keyboard focus in every dialog, a styled "Start anyway?" gate for the Android WebView contexts that silently swallowed the native one, and a friendly offline page instead of the browser's error screen.

### 🎵 Eight new playlists, and a lot more Tidal

New this cycle: Best Canadian Hits, 100 Greatest Rock Songs, Québécois 1990–2020, Deutschrock Best-Of, Funk Carioca, Polish All-Time Hits, Polish Rock and Polskie hity lat 90' 00'. The catalogue went from 46 playlists and 5,161 songs to **54 playlists and 5,980 songs**.

Tidal is the bigger story. It began this cycle with a direct link for 2,463 songs, a little under half the catalogue, and ends it at **5,171 songs, or 86 %**. Far fewer songs get skipped on a Tidal night than in June. Alongside that, the daily health check kept repairing dead links and wrong release years, and the Apple Music matcher learned to tell an alternate mix from the real recording rather than accepting it as a perfect match.

### 🙏 Thank you

To **@pwhh20** for two reports in one, including a warning nobody else had looked at closely. To everyone who flagged a wrong year or a dead song from inside a live game — the speaker-twin bug, the Mix-tab dead end and the Sudden Death gating all came from a real party where something did not work. And to everyone who installs each release candidate and keeps playing anyway: this release took more than twenty of them, and you found the things the tests could not.

---

**54 playlists · 5,980 songs · 6 music platforms · 5 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
