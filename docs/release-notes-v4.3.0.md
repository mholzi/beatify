## Beatify v4.3.0 — "Your Records, Your Language, Your Length"

Play from the music you already own, run the whole game in Italian, and decide for yourself how long the night lasts. The catalogue grew by a fifth while that was being built.

> **Numbered 4.3.0, not 4.2.1.** The work shipped as three release candidates called `v4.2.1-rc1`…`rc3`, but a patch number promises bug fixes. This carries three new features, four new playlists and 1,162 more songs. The release candidates keep their names in the history; the release does not inherit theirs.

### 🎚️ Play from your own record crate

Beatify can now build a game out of the music in your own Music Assistant library — Plex, Jellyfin, local files — instead of a streaming provider. Pick the library as your source in the setup wizard and the game runs on your own collection.

Playback was never the hard part; Music Assistant already plays a library track. The hard part was *metadata good enough to guess against*. Local tags carry the year of the pressing, so a shelf full of greatest-hits rips makes every era look like the nineties. A difficulty setting means nothing if "famous" means famous inside one collection. And Music Assistant's list views return no genres at all. So the mode builds an enriched, cached pool of your library, checked against MusicBrainz, rather than reading the tags and hoping.

Contributed by **@DrMagicWolf** — the largest external contribution the project has had. Six provider-neutral fixes travelled with it and help every user, whether or not they ever switch the mode on.

### ⏱️ The host decides how long a night runs

A game used to play every song of every playlist you picked, so a hundred-song playlist meant a two-hour evening nobody asked for. Step 4 of the setup wizard now offers 10, 20, 30, everything, or a number you type, with a live estimate of how long that takes. A rematch replays at the same length.

Requested by **@Vanman777** on 15 June and open for 57 days — the only external feature request in the tracker.

### 🇮🇹 Si gioca in italiano

Pick Italian in the setup wizard and everyone gets it: the lobby, the player screens, the scoreboard, the spoken announcements, the song trivia and the award names. Home Assistant's own setup dialog is translated too, so it starts in Italian before the game does.

The gap this closes was visible from outside the project — the catalogue had carried Italian music for weeks while the language picker offered five languages, none of them Italian.

### 📺 The television shows all of it

The reveal standings used to cut names off with no scrollbar and no hint that there was more, and the lower band grew without limit in exactly the rounds where the standings matter most. The card scrolls now and the band is capped.

A scrollbar is not operable on a television with no pointer, though, so the rows also share the card's height and the type scales with the row — the standings fit at any player count and any screen height rather than merely being scrollable by someone who cannot scroll.

Reported by **@FurtiveD**.

### 🔊 Speakers, and getting your own music back

- **Your listening survives the game.** Every round is played with `enqueue: "replace"`, which wipes whatever Music Assistant had queued. Nothing was ever remembered, so a game ended with the speaker parked on Beatify's last track. The current track, playback position, shuffle flag and repeat mode are captured once per game and handed back at the end; the track returns paused, at the position it was at.
- **Switching speakers mid-game keeps its promises.** The switch used to discard the outgoing speaker's pre-game volume and leave it at party level forever. Each speaker is now restored to its own captured level.
- **A speaker that cannot play is no longer a dead end.** The message used to be a toast that faded on its own, leaving the host in front of an unchanged screen with no hint left. It is a persistent banner above the start button now, and it carries a button that opens the speaker list and jumps to it.
- **Removing the integration really removes it.** Beatify had no `async_remove_entry` at all, so the saved setup and two Home Assistant storage keys survived a delete and handed a fresh install the speaker entity ids of the old one. Reported by **@proffalken**.

### ☠️ Sudden Death names the ending it actually had

When the rounds run out with two or more players still alive, nobody is the last one standing. The end screen had no words for that and, worse, announced "Last One Standing" while the leaderboard directly below showed several survivors. It now shows **Best of the Survivors** with the count that explains it, and a genuine one-against-one finish keeps the trophy.

This became reachable the moment the round count was selectable: elimination removes one player per round, so a cap of ten rounds leaves eleven players with two survivors.

### 🎧 The catalogue grew by a fifth

**54 playlists and 5,980 songs became 58 and 7,142.**

- **Tomorrowland Top 1000 — 825 songs.** The festival's own ranking, from Faithless in 1995 to this year's mainstage. 170 of the 1,002 entries were already curated elsewhere and are not duplicated here.
- **Musica Italiana — 114 songs**, 1960s to 2000s, and **Sanremo: I Vincitori — 68 songs**, every festival winner since 1951. The Sanremo years come from the official *Albo d'oro* rather than from streaming metadata, which dates reissues instead of songs.
- **Wiesn Party Hits — 100 songs**, in time for the season.
- **EDM Anthems 190 → 246**, with the 56 Tomorrowland tracks that were not already somewhere in the catalogue.

### 🔧 And it was audited while it grew

- **291 malformed provider links across five playlists.** Bare numeric ids and web URLs where the player expects a provider URI. Nineteen songs had a broken link with nothing behind it in seven storefronts, because a song carrying a region map drops its plain link entirely. The build now checks the shape of every provider link, so the next one fails the pull request instead of reaching a player.
- **Seven Apple ids in Swiss Hits pointed at other songs** — six of them at breathing exercises and a Lewis Capaldi track, one at an Ultimo song.
- **The Beach Boys are playable again.** *Surfin' U.S.A.* carried the same dead Apple Music id in all seven storefronts, with a healthy id sitting unused beside it.
- **Five wrong years, and a rule that did not exist before.** Two Patent Ochsner songs and one by Varius Manx were dated to a later unplugged or acoustic recording rather than to the song. A fourth was simply five years early. The fifth exposed a gap: for a *cover by a different artist* the convention said nothing, and the catalogue was quietly answering it two opposite ways. It now takes the year of the linked recording — the room hears the cover, so the answer should match the speaker.
