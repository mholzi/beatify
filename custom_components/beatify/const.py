"""Constants for Beatify."""

DOMAIN = "beatify"

# Companion auth-bypass opt-in (#1357). The HA Android Companion bypass in
# server/companion_auth.py grants admin access on a UA + private-IP match with
# zero credentials. That is unsafe behind Nabu Casa / reverse proxies, so the
# bypass is OFF by default and only takes effect when the user explicitly
# enables this option in the integration's options flow.
CONF_ENABLE_COMPANION_AUTH_BYPASS = "enable_companion_auth_bypass"
DEFAULT_ENABLE_COMPANION_AUTH_BYPASS = False

# Game configuration
MAX_PLAYERS = 20
MIN_PLAYERS = 2
# #2699: the one place the Sudden Death floor is defined. server/game_views.py
# enforces it at the LOBBY->PLAYING transition, www/js/game-constants.js mirrors
# it for the wizard card (guarded by
# www/js/__tests__/game-constants-mirror.test.js), and the six locale files carry
# it as a `{min}` placeholder rather than a spelled-out digit. Before that the
# number sat in four places and none of them was the source of truth, so raising
# it here left the wizard offering a mode the server then quietly dropped.
SUDDEN_DEATH_MIN_PLAYERS = 3
DEFAULT_ROUND_DURATION = 45  # seconds
ROUND_DURATION_MIN = 15  # seconds (Story 13.1)
ROUND_DURATION_MAX = 60  # seconds (Story 13.1)

# #2562: the one place the reaction brake is defined. Reactions used to be
# capped at one per player per REVEAL phase, which is a sane budget for a
# five-second reveal and a nonsensical one for a 45-second round — and #2562
# opens reactions to anyone who has already submitted. Dropping the cap without
# a replacement lets one phone flood the TV, so the per-phase budget is replaced
# by this interval: the fewest seconds between two reactions from the SAME
# player. game/player_registry.py enforces it, server/ws_handlers/lifecycle.py
# echoes it back to the sender so the phone can draw the cooldown, and
# www/js/game-constants.js mirrors it (guarded by
# www/js/__tests__/game-constants-mirror.test.js) so the bar on the phone counts
# down exactly the interval the server is enforcing.
#
# 8 is a STARTING GUESS, not a measurement: it is roughly five reactions across
# a 45-second round, which felt like "a room reacting" rather than "a child
# hammering a button" on paper. Nobody has run a party on it yet. Tuning it is
# meant to be this one line.
REACTION_THROTTLE_SECONDS = 8

# #1936: how many playback timeouts IN A ROW count as a systemic failure that
# pauses the game. Below this, a timeout skips the song and play continues —
# a rate-limiting provider is not a broken one, and pausing on the first
# timeout ended whole games over it. A genuinely offline speaker still reaches
# the recovery banner, just a few songs later.
#
# #2682 raised MA_PLAYBACK_TIMEOUT to 25s, which now covers Music Assistant's
# backoff up to its fifth retry (~23s to first audio). A timeout that still
# happens under that budget means MA is at its sixth attempt or later, where
# the next retry alone is ~16s — so waiting is no longer the better answer and
# this counter is what keeps the game moving instead. Three of them in a row
# still pauses, and the log now says which of the two causes it was.
MAX_CONSECUTIVE_PLAYBACK_FAILURES = 3

# Server-side round backstop (#1865). A periodic tick ends a round whose
# deadline passed while the phase is still PLAYING, so the game does not depend
# on the per-round timer task surviving or on a client's countdown nudging it.
# The grace keeps it a backstop: the timer task running slightly late is normal
# and should still be the thing that ends the round.
ROUND_SUPERVISOR_INTERVAL_SECONDS = 2
ROUND_OVERDUE_GRACE_SECONDS = 2.0
# #1012 / #2626: the auto-advance delays a host can pick at the reveal, in
# seconds; 0 means "off" (advance manually or when the song ends). This tuple is
# the ONLY list of allowed values: server/game_views.py validates against it and
# www/js/game-constants.js mirrors it (guarded by
# www/js/__tests__/game-constants-mirror.test.js), so both the wizard chips and
# the admin chips are rendered from it. Before that, three hand-kept lists could
# disagree and a chip the UI showed as selected silently became "off".
REVEAL_AUTO_ADVANCE_OPTIONS: tuple[int, ...] = (0, 30, 60, 90)

# #2627: the one place the player-name cap is defined. game/player_registry.py
# enforces it, and www/js/game-constants.js mirrors it for the join forms
# (guarded by www/js/__tests__/game-constants-mirror.test.js) so the client
# never disables a Join button for a name the server would have accepted.
MAX_NAME_LENGTH = 20
MIN_NAME_LENGTH = 1
LOBBY_DISCONNECT_GRACE_PERIOD = 5  # seconds before removing disconnected player

# Year range for guesses
YEAR_MIN = 1950
YEAR_MAX = 2026

# Volume control step (10%) - Story 6.4
VOLUME_STEP = 0.1

# Streak milestone bonuses (Story 5.2, Issue #147)
# Key = streak count, Value = bonus points
STREAK_MILESTONES: dict[int, int] = {3: 20, 5: 50, 10: 100, 15: 150, 20: 250, 25: 400}

# Side-challenge bonus (Story 20.1 artist quiz, Issue #28 movie quiz).
# Both side challenges are winner-takes-all (Issue #1723): the single fastest
# correct guesser earns this bonus, everyone else earns 0. The movie quiz used
# to pay tiered [5, 3, 1] by speed rank, but that let one fast phone sweep every
# round in larger groups, so it was unified DOWN to match the artist challenge.
CHALLENGE_BONUS_POINTS = 5

# Title & Artist guessing mode (Issue #1180)
# Full-credit points for an exact or fuzzy match per field.
TITLE_POINTS = 10
ARTIST_POINTS = 5
# Partial-credit points for a vote-accepted near-miss per field.
TITLE_PARTIAL_POINTS = 5
ARTIST_PARTIAL_POINTS = 3
# Fuzzy matching: base Levenshtein budget to auto-accept as a typo, for
# normalized truths in the short range (FUZZY_MIN_LEN up to the first
# FUZZY_EXTRA_EDIT_LENGTHS threshold).
FUZZY_MAX_EDITS = 3
# Guard: only apply fuzzy matching when the normalized truth is at least
# this long, to avoid edit-slack false positives on short words.
FUZZY_MIN_LEN = 5
# Longer titles can absorb more slips: each normalized-length threshold here
# grants +1 to the fuzzy edit budget. With base 3 and (12, 20): 12-19 -> 4,
# 20+ -> 5. Tune by adjusting the base or thresholds.
FUZZY_EXTRA_EDIT_LENGTHS = (12, 20)
# Hard cap so short titles stay strict: the budget never exceeds one edit per
# this many characters. With 3: a 5-char title tolerates 1 edit, 6-8 -> 2,
# 9-11 -> 3 (where the scaled budget takes over). Stops "Queen" matching 3 typos.
FUZZY_BUDGET_LEN_DIVISOR = 3
# Near-miss band: beyond the fuzzy auto-accept, a guess is still "debatable"
# (-> community vote) if its edit distance is within this fraction of the longer
# string, or it shares a significant word with the truth. Anything further is
# just wrong (no vote, 0 points). Keeps "Beatles" for "Queen" out of the vote.
NEAR_MISS_MAX_RATIO = 0.5
# Hard length cap for a single title/artist guess field (#1362). A real title
# or artist never approaches this, but aiohttp accepts WS messages up to 4 MB,
# so an unbounded guess would feed a multi-megabyte string into the pure-Python
# O(n*m) Levenshtein DP and freeze the HA event loop. Guesses are truncated to
# this length at WS ingest (before storing/broadcasting) and defensively again
# inside classify_field.
MAX_GUESS_LEN = 200
# Conditional near-miss community-vote window (REVEAL phase), in seconds.
TITLE_ARTIST_VOTE_WINDOW_SECONDS = 30

# Intro mode constants (Issue #23)
INTRO_DURATION_SECONDS = 15
# #2583: INTRO_ROUND_CHANCE lived here and was never read — the per-round
# probability is `_INTRO_PROBABILITY` in game/round_manager.py. Two homes
# for one number meant either could drift without anyone noticing.
INTRO_BONUS_TIERS: list[int] = [5, 3, 1]  # Same as movie bonus
MIN_INTRO_BONUSES_FOR_AWARD = 1  # Minimum to qualify for superlative

# Steal power-up constants (Story 15.3)
STEAL_UNLOCK_STREAK = 3  # Consecutive correct answers to unlock steal
# Difficulty presets (Story 14.1)
DIFFICULTY_EASY = "easy"
DIFFICULTY_NORMAL = "normal"
DIFFICULTY_HARD = "hard"
DIFFICULTY_DEFAULT = DIFFICULTY_NORMAL

# Points for the two tiers that do not depend on difficulty. They used to live
# in game/scoring.py, one import away from the table they belong to; #2625
# brought them here so the whole year-guess payout is readable in one place —
# and so the frontend mirror in www/js/game-constants.js has a single file to
# be checked against.
POINTS_EXACT = 10
POINTS_WRONG = 0

# Scoring config per difficulty level (Story 14.1)
# close_range/close_points: years off and points for "close" tier
# near_range/near_points: years off and points for "near" tier
# A near_range of 0 means the level has no near tier at all — everything
# outside close_range scores POINTS_WRONG.
# Exact match always awards POINTS_EXACT.
#
# #2625: the difficulty hints the wizard and the admin panel show are BUILT
# from these numbers (www/js/game-constants.js + the {placeholder} templates in
# www/i18n/*.json), not written out again as prose. The admin hint had already
# drifted — it promised "only close guesses score" where the wizard promised
# the concrete "3 pts within ±2 years".
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

# ---------------------------------------------------------------------------
# Host pause reasons (#2645)
# ---------------------------------------------------------------------------
# Every pause reason that existed before #2645 is one the *server* decided: the
# admin socket dropped, the speaker stopped answering, the playlist ran dry.
# ``pause_game()`` has taken a reason string for a long time, but no code path
# let the host name one — the host had Stop, which takes the music away while
# the clock keeps running and scores the whole room as "missed".
#
# These four are the reasons a host picks on purpose, and they double as the
# announcement the room reads: the TV prints the reason large with the word
# "Pause" small underneath, so twenty people learn what is happening without
# anyone having to shout it. ``HOST_PAUSE_REASON`` is what a bare Pause tap
# sends — a host who opened the door without picking a tile has still paused,
# and the TV then simply says "Pause".
HOST_PAUSE_REASON = "host_pause"
HOST_PAUSE_REASON_FOOD = "host_pause_food"
HOST_PAUSE_REASON_DOOR = "host_pause_door"
HOST_PAUSE_REASON_AWAY = "host_pause_away"

#: The reasons an admin socket may set. A reason outside this set is rejected,
#: and — just as important — a pause the *server* owns can never be relabelled
#: into one of these: "Pizza is here" must not be able to cover a dead speaker.
HOST_PAUSE_REASONS: frozenset[str] = frozenset(
    {
        HOST_PAUSE_REASON,
        HOST_PAUSE_REASON_FOOD,
        HOST_PAUSE_REASON_DOOR,
        HOST_PAUSE_REASON_AWAY,
    }
)

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
# #2294: the two create-game rejections a host can actually act on. They used to
# share INVALID_REQUEST with ten unrelated ones, which the client renders as a
# single generic sentence — "this request was invalid, check your setup".
ERR_NO_PLAYLISTS_SELECTED = "NO_PLAYLISTS_SELECTED"
ERR_NO_PLAYABLE_SONGS = "NO_PLAYABLE_SONGS"
ERR_INVALID_ACTION = "INVALID_ACTION"
# #2336: a handler raised. Distinct from INVALID_ACTION, which means "the
# server understood you and said no" — this one means the server broke.
ERR_INTERNAL = "INTERNAL_ERROR"
ERR_GAME_FULL = "GAME_FULL"
ERR_NO_SONGS_REMAINING = "NO_SONGS_REMAINING"
ERR_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"  # Story 11.2
ERR_SESSION_TAKEOVER = "SESSION_TAKEOVER"  # Story 11.2 - dual-tab scenario
ERR_ADMIN_CANNOT_LEAVE = "ADMIN_CANNOT_LEAVE"  # Story 11.5
ERR_NO_STEAL_AVAILABLE = "NO_STEAL_AVAILABLE"  # Story 15.3 - player has no steal
ERR_TARGET_NOT_SUBMITTED = (
    "TARGET_NOT_SUBMITTED"  # Story 15.3 - target hasn't submitted
)
ERR_CANNOT_STEAL_SELF = "CANNOT_STEAL_SELF"  # Story 15.3 - cannot target self
ERR_NO_SABOTAGE_AVAILABLE = "NO_SABOTAGE_AVAILABLE"  # #1665 - no sabotage token
ERR_CANNOT_SABOTAGE_SELF = "CANNOT_SABOTAGE_SELF"  # #1665 - cannot target self
ERR_TARGET_ALREADY_SUBMITTED = (
    "TARGET_ALREADY_SUBMITTED"  # #1665 - target is already locked in
)
ERR_TARGET_ALREADY_SABOTAGED = (
    "TARGET_ALREADY_SABOTAGED"  # #1665 - one hit per target per round
)
ERR_FROZEN = "FROZEN"  # #1665 - freeze effect: guess is still locked
ERR_NO_ARTIST_CHALLENGE = "NO_ARTIST_CHALLENGE"  # Story 20.3 - no artist challenge
ERR_NO_MOVIE_CHALLENGE = "NO_MOVIE_CHALLENGE"  # Issue #28 - no movie quiz this round
ERR_NO_TITLE_ARTIST_CHALLENGE = "NO_TITLE_ARTIST_CHALLENGE"  # #1180 - no T&A this round
ERR_UNAUTHORIZED = "UNAUTHORIZED"  # Issue #477 - invalid admin token
ERR_ELIMINATED = "ELIMINATED"  # #1748 - Sudden Death: eliminated player may not act

# Sabotage power-up constants (Issue #1665)
# The effect is rolled server-side on use — the saboteur picks only the target.
SABOTAGE_TIMER_CUT = "timer_cut"
SABOTAGE_FORCED_BET = "forced_bet"
SABOTAGE_FREEZE = "freeze"
SABOTAGE_EFFECTS: tuple[str, ...] = (
    SABOTAGE_TIMER_CUT,
    SABOTAGE_FORCED_BET,
    SABOTAGE_FREEZE,
)
SABOTAGE_TIMER_CUT_SECONDS = 5  # Target loses this much guess time
SABOTAGE_FREEZE_SECONDS = 3  # Target cannot submit for this long

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
MIN_MOVIE_WINS_FOR_AWARD = (
    1  # Minimum movie quiz bonus points for Film Buff (Issue #28)
)
MIN_ROUNDS_FOR_COMEBACK = 6  # Minimum rounds played for Comeback King (Issue #143)
MIN_COMEBACK_IMPROVEMENT = (
    2.0  # Minimum avg score improvement for Comeback King (Issue #143)
)
# Title & Artist mode superlatives (#1180). These award off cumulative per-field
# correctness counters tracked only while title_artist_mode is on.
MIN_EXACT_TITLES_FOR_AWARD = 2  # Minimum exact titles to qualify for Name Dropper
MIN_CORRECT_ARTISTS_FOR_AWARD = (
    2  # Minimum artists named to qualify for Artist Whisperer
)
MIN_PERFECT_PAIRS_FOR_AWARD = (
    2  # Minimum title+artist rounds to qualify for Perfect Pair
)
MIN_NEAR_MISSES_FOR_AWARD = 2  # Minimum near misses to qualify for So Close
MAX_SUPERLATIVES = 6  # Maximum number of superlatives to display

# External URLs
PLAYLIST_DOCS_URL = "https://github.com/mholzi/beatify/wiki/Creating-Playlists"
MEDIA_PLAYER_DOCS_URL = "https://www.home-assistant.io/integrations/#media-player"

# Playlist configuration
PLAYLIST_DIR = "beatify/playlists"

# Multi-provider URI patterns (Story 17.1).
# Restored in #688 — these ARE used by game/playlist.py for URI validation
# during playlist discovery. Removed in #687 by mistake.
URI_PATTERN_SPOTIFY = r"^spotify:track:[a-zA-Z0-9]{22}$"
URI_PATTERN_APPLE_MUSIC = r"^applemusic://track/\d+$"
URI_PATTERN_YOUTUBE_MUSIC = r"^https://music\.youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}$"
URI_PATTERN_TIDAL = r"^tidal://track/\d+$"
URI_PATTERN_DEEZER = r"^deezer://track/\d+$"
URI_PATTERN_MA_LIBRARY = r"^[a-z0-9_]+(--[^:]+)?://track/.+$"
# #2426: sproft/music-assistant-ytmusic registers as `ytmusic_free` and streams
# YouTube Music without a Premium account. Its track item_id IS the YouTube
# video id (`_encode_track_id` in the provider returns it unchanged unless a
# trim window is set), so Beatify derives the URI from the `uri_youtube_music`
# the catalogue already carries rather than storing a second copy of the same
# id. `multi_instance` is true for that provider, hence the optional
# `--<suffix>` on the instance name.
URI_PATTERN_YTMUSIC_FREE = r"^ytmusic_free(--[^:]+)?://track/[a-zA-Z0-9_-]{11}$"

# Provider identifiers (Story 17.1)
PROVIDER_SPOTIFY = "spotify"
PROVIDER_APPLE_MUSIC = "apple_music"  # Preserved for future use
PROVIDER_YOUTUBE_MUSIC = "youtube_music"
PROVIDER_TIDAL = "tidal"
PROVIDER_DEEZER = "deezer"
PROVIDER_MA_LIBRARY = "ma_library"
PROVIDER_AMAZON_MUSIC = "amazon_music"
PROVIDER_YTMUSIC_FREE = "ytmusic_free"  # #2426, third-party MA provider
PROVIDER_DEFAULT = PROVIDER_SPOTIFY
