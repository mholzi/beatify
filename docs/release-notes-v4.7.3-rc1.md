## 4.7.3-rc1 — Back in the Room

Three fixes for a host who steps away and comes back, and a new playlist for the dance floor.

### 🚪 The host gets back in after a reload

If the host reloaded the player view on their phone, or iOS threw the tab away in the background, the page tried to rejoin by name alone. The game rightly refused that for the host seat, so the phone sat on "Connecting…" and a paused game could not be resumed. The page now reconnects the same way every other player does.

### ⏸️ A pause during the intro start holds

Pausing in the two or three seconds while an intro song was starting could let the song play through the whole break, or leave the round after it in silence. The intro now stops as soon as it starts, and on resume it plays again from the top with the full round time.

### 🎛️ The lobby follows your playlist change

Picking different playlists in setup and heading back to the lobby used to keep the old songs. The game now plays what the screen shows, and everyone who already joined stays in.

### 🇿🇦 New: South Africa by Q

89 tracks of Amapiano, Afro House, Afrobeats and Highlife.

---

**67 playlists · 8,557 songs · 6 music platforms · 6 languages**

[Report a Bug](https://github.com/mholzi/beatify/issues) · [Discussions](https://github.com/mholzi/beatify/discussions) · [Full Changelog](https://github.com/mholzi/beatify/blob/main/CHANGELOG.md)
