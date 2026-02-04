"""Constants for Beatify."""

DOMAIN = "beatify"

# Game configuration
MAX_PLAYERS = 20
MIN_PLAYERS = 2
RECONNECT_TIMEOUT = 60  # seconds
DEFAULT_ROUND_DURATION = 45  # seconds
ROUND_DURATION_MIN = 15  # seconds (Story 13.1)
ROUND_DURATION_MAX = 60  # seconds (Story 13.1)
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

# Artist challenge bonus (Story 20.1)
ARTIST_BONUS_POINTS = 5

# Movie quiz bonus tiers by speed rank (Issue #28)
# Index 0 = fastest correct, index 1 = 2nd fastest, etc.
MOVIE_BONUS_TIERS: list[int] = [5, 3, 1]

# Intro mode constants (Issue #23)
INTRO_DURATION_SECONDS = 10
INTRO_ROUND_CHANCE = 0.20  # 20% chance per round
INTRO_BONUS_TIERS: list[int] = [5, 3, 1]  # Same as movie bonus
MIN_INTRO_BONUSES_FOR_AWARD = 1  # Minimum to qualify for superlative

# Steal power-up constants (Story 15.3)
STEAL_UNLOCK_STREAK = 3  # Consecutive correct answers to unlock steal
MAX_STEALS_PER_GAME = 1  # Maximum number of steals allowed per game

# Difficulty presets (Story 14.1)
DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"
DIFFICULTY_DEFAULT = DIFFICULTY_NORMAL

# Scoring config per difficulty level (Story 14.1)
# close_range/close_points: years off and points for "close" tier
# near_range/near_points: years off and points for "near" tier
# Exact match always awards 10 points (POINTS_EXACT)
DIFFICULTY_SCORING: dict[str, dict[str, int]] = {
    DIFFICULTY_EASY: {
        "close_range": 7,
        "close_points": 5,
        "near_range": 10,
        "near_points": 1,
    },
    DIFFICULTY_NORMAL: {
        "close_range": 3,
        "close_points": 5,
        "near_range": 5,
        "near_points": 1,
    },
    DIFFICULTY_HARD: {
        "close_range": 2,
        "close_points": 3,
        "near_range": 0,
        "near_points": 0,
    },
}

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
ERR_NO_STEAL_AVAILABLE = "NO_STEAL_AVAILABLE"  # Story 15.3 - player has no steal
ERR_TARGET_NOT_SUBMITTED = "TARGET_NOT_SUBMITTED"  # Story 15.3 - target hasn't submitted
ERR_CANNOT_STEAL_SELF = "CANNOT_STEAL_SELF"  # Story 15.3 - cannot target self
ERR_NO_ARTIST_CHALLENGE = "NO_ARTIST_CHALLENGE"  # Story 20.3 - no artist challenge
ERR_NO_MOVIE_CHALLENGE = "NO_MOVIE_CHALLENGE"  # Issue #28 - no movie quiz this round

# Song difficulty rating constants (Story 15.1)
MIN_PLAYS_FOR_DIFFICULTY = 3  # Minimum plays before showing difficulty rating
CORRECT_GUESS_THRESHOLD = 3  # Years off to count as "correct" for difficulty calc
DIFFICULTY_LABELS: dict[int, str] = {
    1: "easy",
    2: "medium",
    3: "hard",
    4: "extreme",
}
# Accuracy thresholds: key = stars, value = min accuracy percentage
DIFFICULTY_THRESHOLDS: dict[int, int] = {1: 70, 2: 40, 3: 20, 4: 0}

# Superlative award constants (Story 15.2)
MIN_SUBMISSIONS_FOR_SPEED = 3  # Minimum submissions to qualify for Speed Demon
MIN_STREAK_FOR_AWARD = 3  # Minimum streak to qualify for Lucky Streak
MIN_BETS_FOR_AWARD = 3  # Minimum bets placed to qualify for Risk Taker
MIN_ROUNDS_FOR_CLUTCH = 3  # Minimum rounds played for Clutch Player
MIN_CLOSE_CALLS = 2  # Minimum close guesses to qualify for Close Calls
MIN_MOVIE_WINS_FOR_AWARD = 1  # Minimum movie quiz bonus points for Film Buff (Issue #28)
MAX_SUPERLATIVES = 5  # Maximum number of superlatives to display

# External URLs
PLAYLIST_DOCS_URL = "https://github.com/mholzi/beatify/wiki/Creating-Playlists"
MEDIA_PLAYER_DOCS_URL = "https://www.home-assistant.io/integrations/#media-player"

# Playlist configuration
PLAYLIST_DIR = "beatify/playlists"

# Supported platforms for media playback routing
# See services/media_player.py PLATFORM_CAPABILITIES for full capability matrix
SUPPORTED_PLATFORMS = ("music_assistant", "sonos", "alexa_media")

# Multi-provider URI patterns (Story 17.1)
URI_PATTERN_SPOTIFY = r"^spotify:track:[a-zA-Z0-9]{22}$"
URI_PATTERN_APPLE_MUSIC = r"^applemusic://track/\d+$"  # Preserved for playlist validation
URI_PATTERN_YOUTUBE_MUSIC = r"^https://music\.youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}$"
URI_PATTERN_TIDAL = r"^tidal://track/\d+$"

# Provider identifiers (Story 17.1)
PROVIDER_SPOTIFY = "spotify"
PROVIDER_APPLE_MUSIC = "apple_music"  # Preserved for future use
PROVIDER_YOUTUBE_MUSIC = "youtube_music"
PROVIDER_TIDAL = "tidal"
PROVIDER_DEFAULT = PROVIDER_SPOTIFY
