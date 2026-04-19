<!--
Draft release notes for v3.3.0 — the eventual final release of the v3.3 milestone.
Format matches the v3.2.0 GitHub release body. Copy this into `gh release create`
body when cutting the final release. Pre-release notes for rc1/rc2/rc3 live in
CHANGELOG.md and the corresponding GitHub release pages.
-->

## v3.3.0 — The Playlist Hub

The wizard step-3 playlist picker went from a flat list of 20 entries to a proper three-tab browser with shelves, search, local-usage stats, and a detail bottom-sheet. The `community/` subfolder is now a first-class destination instead of a hidden checkpoint — reorganized by country, with rich per-playlist metadata, and every playlist one tap away from a full-story preview.

### ✨ What's New

**Playlist Hub**
Mobile-first 390px browser that replaces the flat `wiz-row` list from v3.2.0. Three tabs swap the entire body — **Bundled (11)** · **Community (13)** · **Mine**. Horizontal-scroll shelves inside each tab. Search matches playlist name, tags, description, language, and author in a single query. Genre chips narrow the active tab. Every card is tappable: opens a bottom-sheet with song count, year range, language, author attribution, tags, streaming-provider coverage, and a single **Add to round** / **Remove from round** CTA that syncs with the wizard's selection set. The hub owns its own sticky CTA bar at the bottom — mail-icon request FAB, Back button, selection-count pill, and a pink→coral Continue that fires the wizard's advance path.

**Community Library — first-class browse surface**
The community/ folder existed in v3.2.0 with 4 user-contributed playlists, but they were buried in the flat list indistinguishable from bundled content. v3.3.0 promotes the Community tab to a curated destination with its own editorial logic: **✨ Editor's Picks** (featured cards with gradient borders, sorted by song count), **🌍 By Country** section grouping per-language shelves (deterministic order DE > EN > ES > FR > NL > IT > PT > JA > KO > other), **Recently added** (derived from each playlist's added_date, with month-year badges on the cards), and **Regional & Specialty** for anything tagged regional / folk / carnival. Each community card shows its author and song count. No global install counts, no "trending" — all provenance metadata comes from the playlist file itself.

**Your most-played + Recently played**
Two local-stats shelves ride the top of Bundled when you've played at least one round. Neon-green **LOCAL** pill in each shelf title signals data provenance at a glance. Your top 5 playlists sorted by play count, your 12 most-recent sorted by last-played timestamp with player count + duration on each card. Derived from the existing `GameRecord` history — the same log that powers the analytics dashboard — so no new telemetry, no schema migration, and the data never leaves your Home Assistant. First-time users see neither shelf; they kick in the moment you've played a single round.

**Curation pass — Bundled trimmed to the broad-appeal staples**
The default 20 playlists shipped in v3.2.0 mixed party staples with heavy specialties — Cologne Karneval (290 songs of regional German carnival content) sat next to Greatest Hits of All Time with no visual distinction. v3.3.0 moves 9 specialties into community/ where they can be found under their respective country or genre banner. **Bundled (11)** is now: 2000s Pop Anthems · 80s Hits · 90s Hits · Greatest Hits of All Time · Motown & Soul Classics · Disco & Funk Classics · Top 100 Power Ballads · 100 Summer Anthems · Eurovision Winners · 100 Greatest Movie Themes · One-Hit Wonders. **Community (13)** includes the 9 moves (Cologne Carnival, Schlager Classics, Fiesta Latina 90s, British Invasion & Britpop, Yacht Rock, Pure Pop Punk, Eurodance 90s, 90s & 2000s Hip Hop Bangers, Gen Z Anthems) plus the existing 4 (Greatest Metal Songs, 100% en Español, 60s Classics, Top 100 Dutch Classics). Every community playlist gained `language` + `author` + `description` + `added_date` + `version` — the hub reads all of it to render proper detail sheets and country grouping.

**Request flow folded into the Mine tab**
The v3.2.0 "Request Custom Playlist" path now lives inside the Playlist Hub as its Mine tab. Empty state = single "Request a playlist" CTA plus a nudge to browse Community in the meantime. Populated state = list of your requests with colored status pills (Pending → Reviewed → Building → In Bundled) and a 4-step progress strip per request. Done requests link directly to where the playlist landed in Bundled; in-flight requests link to the GitHub issue for progress tracking. The backend request endpoint is unchanged — `window.PlaylistRequests` module from v3.2.0 still owns submission, polling, and storage.

**Labeled "+ Add" / "✓ Added" select pill**
Every card gets a prominent pink pill top-left reading "+ Add" when unselected, flipping to neon-green "✓ Added" when selected. Replaces v3.2.0's faint empty corner circle that didn't read as an action. Picked from four design variants after live QA — details in the design shotgun board at `~/.gstack/projects/mholzi-beatify/designs/card-select-20260419/variants.html`. German pill reads "Hinzu" / "Drin" to fit the 10px caps type; full labels go on the aria-label for screen readers.

### 🔧 Under the Hood

New 1000-line `playlist-hub.js` ES module + `/beatify/api/usage?kind=top|recent` endpoint aggregating existing `GameRecord` data, every playlist tagged with `source` + `author` + `description` + `language` + `added_date` at discovery, en + de i18n coverage, three live-QA iterations of UX polish, zero schema migration, and no runtime fetch — community playlists ship on disk via HACS.

---

24 playlists · 2,481 songs · 5 music platforms · 5 languages

[Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md) · [Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions)
