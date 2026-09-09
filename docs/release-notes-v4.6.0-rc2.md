## 4.6.0-rc2 — Second Wind

Everything from rc1 is unchanged: the ghost league, the encore, taking a guest out mid-game. This candidate adds no gameplay at all. It exists because a catalogue check went looking for broken links and found something about itself.

### 🎵 Four broken links, and two of them deleted rather than replaced

`polish-all-time-hits` had four provider URIs that no longer play. Two are simply gone instead of swapped: a missing URI makes Beatify skip that provider, a dead one makes playback fail in front of your guests. One was worse than dead — it pointed at a 2016 live recording while the answer on screen said 1995.

### 🔍 The checker was asking the wrong questions

Five of that run's nine findings were false alarms. Deezer was judged on its display name, which carries an album prefix on compilations; Apple was looked up in US/DE/GB for a Polish playlist. Now the ISRC decides for Deezer, and Apple is asked in the storefronts the entry itself claims. Both real defects still fail the check.

Also in: 97 more YouTube links, and a build toolchain that resolves the same way twice — with its security advisories down from eight to zero.

---

**66 playlists · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
