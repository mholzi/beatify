## 4.8.5-rc1 — Hold the Intro

The intro round waits quietly now, and one setting is safe behind a reverse proxy.

### 🎤 Intro rounds

- When the host picks an intro round, the last song no longer keeps playing under the waiting card.
- The countdown on the admin page holds until the round starts, like the one on the TV.
- The intro song stops after 15 seconds instead of running the whole round. The reveal plays it again.

Thanks to **@aenkieh** for the report.

### 🔒 Companion login behind a proxy

If you turned on the Android Companion login bypass and reach Home Assistant through a reverse proxy (nginx, Traefik, Caddy), requests from the internet could pass as local. The bypass now refuses any proxied request. It stays off by default.

### 🎵 Playlist repairs

Broken links are fixed in Eurovision Winners, Sommerklassiker, Funk Carioca and American Classics.

---

**70 playlists · 8,724 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
