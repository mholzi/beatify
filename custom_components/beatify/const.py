"""Constants for Beatify."""

DOMAIN = "beatify"

# Game configuration
MAX_PLAYERS = 20
MIN_PLAYERS = 2
RECONNECT_TIMEOUT = 60  # seconds
DEFAULT_ROUND_DURATION = 30  # seconds
MAX_NAME_LENGTH = 20
MIN_NAME_LENGTH = 1
LOBBY_DISCONNECT_GRACE_PERIOD = 5  # seconds before removing disconnected player

# Year range for guesses
YEAR_MIN = 1950
YEAR_MAX = 2025

# Volume control step (10%) - Story 6.4
VOLUME_STEP = 0.1

# Streak milestone bonuses (Story 5.2)
# Key = streak count, Value = bonus points
STREAK_MILESTONES: dict[int, int] = {3: 20, 5: 50, 10: 100}

# Error codes
ERR_NAME_TAKEN = "NAME_TAKEN"
ERR_NAME_INVALID = "NAME_INVALID"
ERR_GAME_NOT_STARTED = "GAME_NOT_STARTED"
ERR_GAME_ALREADY_STARTED = "GAME_ALREADY_STARTED"
ERR_GAME_ENDED = "GAME_ENDED"
ERR_NOT_ADMIN = "NOT_ADMIN"
ERR_ADMIN_EXISTS = "ADMIN_EXISTS"
ERR_ROUND_EXPIRED = "ROUND_EXPIRED"
ERR_ALREADY_SUBMITTED = "ALREADY_SUBMITTED"
ERR_NOT_IN_GAME = "NOT_IN_GAME"
ERR_MEDIA_PLAYER_UNAVAILABLE = "MEDIA_PLAYER_UNAVAILABLE"
ERR_INVALID_ACTION = "INVALID_ACTION"
ERR_GAME_FULL = "GAME_FULL"
ERR_NO_SONGS_REMAINING = "NO_SONGS_REMAINING"
ERR_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"  # Story 11.2
ERR_SESSION_TAKEOVER = "SESSION_TAKEOVER"  # Story 11.2 - dual-tab scenario
ERR_ADMIN_CANNOT_LEAVE = "ADMIN_CANNOT_LEAVE"  # Story 11.5

# External URLs
PLAYLIST_DOCS_URL = "https://github.com/mholzi/beatify/wiki/Creating-Playlists"
MEDIA_PLAYER_DOCS_URL = "https://www.home-assistant.io/integrations/#media-player"

# Playlist configuration
PLAYLIST_DIR = "beatify/playlists"
