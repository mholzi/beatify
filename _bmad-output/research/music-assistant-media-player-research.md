# Music Assistant & Media Player Research

**Date:** 2025-12-17
**Purpose:** Technical research for Beatify architecture decisions

---

## Music Assistant Overview

Music Assistant (MA) is now a **native Home Assistant integration** (as of HA 2024.12), no longer requiring HACS installation. It serves as a music library manager for both local and streaming providers.

### Key Architecture Points for Beatify

1. **MA is a separate server** — The HA integration connects to a Music Assistant Server
2. **Requires MA server v2.4+** — Minimum version for full functionality
3. **WebSocket API** — MA uses WebSocket API (partially exposed as REST)
4. **Python client available** — `music-assistant/client` for programmatic access

### Music Assistant Services/Actions

| Action | Purpose | Beatify Relevance |
|--------|---------|-------------------|
| `music_assistant.play_media` | Play/enqueue content | **Primary** — Start song playback |
| `music_assistant.search` | Global search across providers | Playlist song lookup |
| `music_assistant.get_library` | Query local library | Browse available tracks |
| `music_assistant.get_queue` | Retrieve current queue | Monitor playback state |
| `music_assistant.transfer_queue` | Move queue between players | Not needed (single player) |
| `music_assistant.play_announcement` | Play URL-based announcements | Potential for sound effects |

### play_media Action Details

**Supported media_id formats:**
- Track/artist names: `"Queen"` or `"Queen - Innuendo"`
- Provider URIs: `spotify://artist/12345`
- Direct URLs: Spotify/streaming links

**Key parameters:**
- `media_type`: artist, album, track, playlist, or radio
- `artist`/`album`: Optional filters for name-based searches
- `enqueue`: `play`, `replace`, `next`, `replace_next`, `add`
- `radio_mode`: Auto-generate similar tracks

### 2025 Features

- **Native integration** — No longer HACS-only
- **"Don't stop the music" mode** — Auto-continues with similar songs
- **External audio sources** — Including Spotify Connect plugin
- **Player outsourcing** — Can delegate volume/power control to HA entities
- **Queue transfer** — Move playing queue between players

---

## Home Assistant Media Player API

Media player is a **building block integration** — other integrations provide the actual devices.

### Media Player States

| State | Meaning |
|-------|---------|
| `off` | Not accepting commands |
| `on` | Active, no media details |
| `idle` | Ready, not playing |
| `playing` | Media in progress |
| `paused` | Temporarily stopped |
| `buffering` | Preparing playback |

### Supported Features (MediaPlayerEntityFeature)

**Playback Control:**
- `PLAY`, `PAUSE`, `STOP`
- `NEXT_TRACK`, `PREVIOUS_TRACK`
- `SEEK`

**Volume:**
- `VOLUME_SET`, `VOLUME_STEP`, `VOLUME_MUTE`

**Media Selection:**
- `PLAY_MEDIA`, `SELECT_SOURCE`, `SELECT_SOUND_MODE`
- `MEDIA_ENQUEUE`, `BROWSE_MEDIA`, `SEARCH_MEDIA`

**Advanced:**
- `GROUPING` — Sync playback across devices
- `MEDIA_ANNOUNCE` — TTS/announcements
- `TURN_ON`, `TURN_OFF`

### Key Service Methods

```python
# Play media
media_player.play_media(
    media_content_type="music",
    media_content_id="spotify://track/xxx",
    enqueue="replace"  # add, next, play, replace
)

# Volume control
media_player.volume_set(volume_level=0.5)  # 0.0 to 1.0
media_player.volume_up()
media_player.volume_down()

# Playback control
media_player.media_play()
media_player.media_pause()
media_player.media_stop()
```

### State Attributes (Read-Only)

**Media metadata:**
- `media_title`, `media_artist`, `media_album_name`
- `media_content_type`, `media_content_id`
- `media_duration`, `media_position`

**Device state:**
- `volume_level` (0.0-1.0)
- `is_volume_muted` (bool)
- `source`, `sound_mode`

**Group state:**
- `group_members` (list of entity IDs)

---

## Architecture Implications for Beatify

### Recommended Approach

1. **Use Music Assistant for playback** — Better queue control, cross-provider support
2. **Use HA media_player for volume** — Direct control, simpler API
3. **Detect MA availability** — Check if `music_assistant` integration is loaded
4. **Support both MA players and raw HA media_players** — Flexibility

### Integration Strategy

```
Beatify Integration
    │
    ├── Music Assistant (if available)
    │   ├── music_assistant.play_media → Play songs
    │   ├── music_assistant.search → Find tracks
    │   └── MA exposes players as media_player entities
    │
    └── Home Assistant Media Player
        ├── media_player.volume_set → Volume control
        ├── media_player.media_stop → Stop playback
        └── State monitoring → Track playback status
```

### Playlist Format Decision

**Option A: MA Native Playlists**
- Use MA's playlist management
- Requires songs to exist in MA library
- Automatic metadata (year, artist, album art)

**Option B: Custom JSON Format (PRD approach)**
- Artist, year, and URI per track
- No MA library dependency
- Manual metadata management
- More control over song data (year is critical for game)

**Recommendation:** Option B (Custom JSON) because:
- Year data is **game-critical** and must be reliable
- Don't want to depend on MA metadata accuracy
- Simpler for users to curate game-specific playlists

### Service Calls for Beatify

```yaml
# Start playing a specific track
service: music_assistant.play_media
data:
  entity_id: media_player.living_room_speaker
  media_id: "spotify://track/4cOdK2wGLETKBW3PvgPWqT"
  media_type: track
  enqueue: replace

# Or using standard media_player (if MA not available)
service: media_player.play_media
data:
  entity_id: media_player.living_room_speaker
  media_content_type: music
  media_content_id: "spotify://track/4cOdK2wGLETKBW3PvgPWqT"

# Volume control
service: media_player.volume_set
data:
  entity_id: media_player.living_room_speaker
  volume_level: 0.7

# Stop playback
service: media_player.media_stop
data:
  entity_id: media_player.living_room_speaker
```

---

## Sources

- [Music Assistant - Home Assistant](https://www.home-assistant.io/integrations/music_assistant)
- [Music Assistant 2.0 Announcement](https://www.home-assistant.io/blog/2024/05/09/music-assistant-2/)
- [Music Assistant's Next Big Hit (2025)](https://www.home-assistant.io/blog/2025/03/05/music-assistants-next-big-hit/)
- [Media Player Entity Developer Docs](https://developers.home-assistant.io/docs/core/entity/media-player/)
- [Media Player Integration](https://www.home-assistant.io/integrations/media_player/)
- [Music Assistant Official Site](https://www.music-assistant.io/)
- [Music Assistant GitHub](https://github.com/music-assistant)
- [Music Assistant Python Client](https://github.com/music-assistant/client)
- [How to Setup Music Assistant (2025 Guide)](https://www.michaelsleen.com/music-assistant/)

---

## HACS Integration Structure

### Directory Layout

```
beatify/
├── custom_components/
│   └── beatify/
│       ├── __init__.py          # Integration setup
│       ├── manifest.json        # Integration metadata
│       ├── config_flow.py       # UI configuration flow
│       ├── const.py             # Constants (DOMAIN, etc.)
│       ├── coordinator.py       # Data update coordinator
│       ├── translations/        # UI strings
│       │   └── en.json
│       └── www/                  # Static web assets
│           ├── admin.html
│           ├── player.html
│           ├── css/
│           └── js/
├── hacs.json                    # HACS metadata
├── README.md                    # Documentation
└── LICENSE
```

### manifest.json Reference

```json
{
  "domain": "beatify",
  "name": "Beatify",
  "version": "1.0.0",
  "documentation": "https://github.com/user/beatify",
  "issue_tracker": "https://github.com/user/beatify/issues",
  "codeowners": ["@username"],
  "dependencies": ["http", "websocket_api"],
  "after_dependencies": ["music_assistant"],
  "requirements": [],
  "config_flow": true,
  "integration_type": "service",
  "iot_class": "local_push"
}
```

### Key manifest.json Fields

| Field | Value | Rationale |
|-------|-------|-----------|
| `domain` | `"beatify"` | Unique identifier |
| `integration_type` | `"service"` | Single service, not a hub |
| `iot_class` | `"local_push"` | Local network, WebSocket push updates |
| `config_flow` | `true` | UI-based setup |
| `dependencies` | `["http", "websocket_api"]` | HA's built-in web server and WS |
| `after_dependencies` | `["music_assistant"]` | Optional MA integration |

### Integration Type Options

| Type | Use Case |
|------|----------|
| `hub` | Gateway to multiple devices (default) |
| `device` | Single device provider |
| `service` | **Best for Beatify** — Single service |
| `helper` | Automation helpers |
| `system` | Reserved for HA core |

### IoT Class Options

| Class | Description |
|-------|-------------|
| `local_polling` | Local network, periodic updates |
| `local_push` | **Best for Beatify** — Local, immediate updates |
| `cloud_polling` | Cloud API, periodic |
| `cloud_push` | Cloud API, push notifications |
| `assumed_state` | State cannot be verified |
| `calculated` | Computed values |

### hacs.json Format

```json
{
  "name": "Beatify",
  "render_readme": true,
  "homeassistant": "2025.11.0"
}
```

### HACS Publishing Requirements

1. **GitHub Repository** — Public repo with releases
2. **Brand Registration** — Submit to `home-assistant/brands` repo
3. **Required manifest.json fields:**
   - `domain`, `name`, `version`
   - `documentation`, `issue_tracker`
   - `codeowners`
4. **File Structure** — Must be in `custom_components/<domain>/`
5. **Releases** — Recommended (HACS shows last 5 releases)

---

## Integration Architecture Patterns

### __init__.py Structure

```python
"""Beatify - Home Assistant Party Game."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = []  # No entity platforms needed

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beatify from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize game server
    # Register web views
    # Set up WebSocket handlers

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Beatify config entry."""
    # Cleanup game server
    # Unregister views
    return True
```

### Config Flow Pattern

```python
"""Config flow for Beatify."""
from homeassistant import config_entries
from homeassistant.core import callback

from .const import DOMAIN

class BeatifyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Beatify."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(
                title="Beatify",
                data=user_input
            )

        return self.async_show_form(step_id="user")
```

### Serving Web Content

```python
from homeassistant.components.http import HomeAssistantView

class BeatifyAdminView(HomeAssistantView):
    """Serve admin interface."""

    url = "/beatify/admin"
    name = "beatify:admin"
    requires_auth = False  # Intentional - frictionless access

    async def get(self, request):
        """Return admin HTML."""
        return web.FileResponse(
            self.hass.config.path("custom_components/beatify/www/admin.html")
        )
```

### WebSocket Handler

```python
from homeassistant.components import websocket_api

@websocket_api.websocket_command({
    "type": "beatify/join_game",
    "player_name": str,
})
@websocket_api.async_response
async def ws_join_game(hass, connection, msg):
    """Handle player joining game."""
    # Game logic here
    connection.send_result(msg["id"], {"status": "joined"})
```

---

## Beatify-Specific Architecture Decisions

### Web Server Options

| Option | Pros | Cons |
|--------|------|------|
| HA's `http` component | Built-in, no extra deps | Limited customization |
| aiohttp directly | Full control | May conflict with HA |
| **Recommended: HA http** | Stable, documented | Sufficient for Beatify |

### WebSocket Options

| Option | Pros | Cons |
|--------|------|------|
| HA's `websocket_api` | Auth built-in, HA-native | Auth may add friction |
| Custom aiohttp WS | No auth, full control | More code, security concerns |
| **Recommended: Custom WS** | Frictionless player access | Separate from HA's WS |

### Static Assets Serving

```python
# Register static path for CSS/JS
hass.http.register_static_path(
    "/beatify/static",
    hass.config.path("custom_components/beatify/www/static"),
    cache_headers=True
)
```

---

## Additional Sources

- [HACS Publishing Docs](https://www.hacs.xyz/docs/publish/integration/)
- [Integration Manifest Reference](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Creating Your First Integration](https://developers.home-assistant.io/docs/creating_component_index/)
- [HACS 2.0 Announcement](https://www.home-assistant.io/blog/2024/08/21/hacs-the-best-way-to-share-community-made-projects/)
- [Building a HA Custom Component](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)
- [Blueprint Template](https://github.com/custom-components/blueprint)
