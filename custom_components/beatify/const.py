"""Constants for Beatify."""

import logging

_LOGGER = logging.getLogger(__name__)

DOMAIN = "beatify"

# Game configuration
MAX_PLAYERS = 20
MIN_PLAYERS = 2
RECONNECT_TIMEOUT = 60  # seconds
DEFAULT_ROUND_DURATION = 30  # seconds
MAX_NAME_LENGTH = 20
MIN_NAME_LENGTH = 1

# Error codes
ERR_NAME_TAKEN = "NAME_TAKEN"
ERR_NAME_INVALID = "NAME_INVALID"
ERR_GAME_NOT_STARTED = "GAME_NOT_STARTED"
ERR_GAME_ALREADY_STARTED = "GAME_ALREADY_STARTED"
ERR_NOT_ADMIN = "NOT_ADMIN"
ERR_ROUND_EXPIRED = "ROUND_EXPIRED"
ERR_MA_UNAVAILABLE = "MA_UNAVAILABLE"
ERR_INVALID_ACTION = "INVALID_ACTION"

# External URLs
MA_SETUP_URL = "https://music-assistant.io/getting-started/"

# Playlist configuration
PLAYLIST_DIR = "beatify/playlists"
