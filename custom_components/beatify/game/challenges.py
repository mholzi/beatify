"""Challenge management for Beatify (artist + movie quiz challenges)."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from custom_components.beatify.const import (
    ARTIST_PARTIAL_POINTS,
    ARTIST_POINTS,
    MOVIE_BONUS_TIERS,
    TITLE_PARTIAL_POINTS,
    TITLE_POINTS,
)
from custom_components.beatify.game.text_match import (
    STATUS_EXACT,
    STATUS_FUZZY,
    STATUS_NEAR_MISS,
    classify_field,
)

# Status stored on a near-miss field once a community vote / host override
# accepts it during resolve_title_artist (Issue #1180). Distinct from the
# raw classification STATUS_* values produced at submit time.
STATUS_NEAR_MISS_ACCEPTED = "near_miss_accepted"

_LOGGER = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class ArtistChallenge:
    """Artist challenge state for bonus points feature (Epic 20)."""

    correct_artist: str
    options: list[str]  # Shuffled: correct + decoys
    winner: str | None = None
    winner_time: float | None = None

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        """
        Convert to JSON-serializable dictionary.

        Args:
            include_answer: If True, include correct_artist (for REVEAL phase).
                           If False, hide answer (for PLAYING phase).

        """
        result: dict[str, Any] = {
            "options": self.options,
            "winner": self.winner,
        }
        if self.winner_time is not None:
            result["winner_time"] = self.winner_time
        if include_answer:
            result["correct_artist"] = self.correct_artist
        return result


@dataclass
class MovieChallenge:
    """Movie quiz challenge state for bonus points feature (Issue #28)."""

    correct_movie: str
    options: list[str]  # Shuffled: 3 movie choices (correct + 2 decoys)
    correct_guesses: list[dict[str, Any]] = field(
        default_factory=list
    )  # [{name, time}]
    wrong_guesses: list[dict[str, Any]] = field(default_factory=list)  # [{name, guess}]

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        """
        Convert to JSON-serializable dictionary.

        Args:
            include_answer: If True, include correct_movie and results (for REVEAL).
                           If False, only show options (for PLAYING).

        """
        result: dict[str, Any] = {
            "options": self.options,
        }
        if include_answer:
            result["correct_movie"] = self.correct_movie
            result["results"] = self._build_results()
        return result

    def _build_results(self) -> dict[str, Any]:
        """Build movie quiz results for reveal display."""
        winners = []
        for i, guess in enumerate(self.correct_guesses):
            bonus = MOVIE_BONUS_TIERS[i] if i < len(MOVIE_BONUS_TIERS) else 0
            winners.append(
                {
                    "name": guess["name"],
                    "time": round(guess["time"], 2),
                    "bonus": bonus,
                }
            )
        return {
            "winners": winners,
            "wrong_guesses": [
                {"name": g["name"], "guess": g["guess"]} for g in self.wrong_guesses
            ],
        }

    def get_player_bonus(self, player_name: str) -> int:
        """
        Get the bonus points for a specific player.

        Args:
            player_name: Name of the player

        Returns:
            Bonus points (5/3/1/0 based on speed rank)

        """
        for i, guess in enumerate(self.correct_guesses):
            if guess["name"] == player_name:
                return MOVIE_BONUS_TIERS[i] if i < len(MOVIE_BONUS_TIERS) else 0
        return 0


@dataclass
class TitleArtistChallenge:
    """Title & Artist guessing challenge state (Issue #1180).

    Replaces the year guess for the whole game. Title and artist are matched
    independently. ``guesses`` holds the raw text plus the per-field
    classification (exact/fuzzy/near_miss/skipped, and later
    near_miss_accepted once resolved). ``votes`` and ``overrides`` are the
    per-near-miss aggregation state (wired to WS handlers in Phase 4).
    """

    correct_title: str
    correct_artist: str
    # player_name -> {"title": str, "artist": str,
    #                 "title_status": str, "artist_status": str, "ts": float}
    guesses: dict[str, dict[str, Any]] = field(default_factory=dict)
    # nearmiss_id ("player:field") -> {voter_name: accept_bool}
    votes: dict[str, dict[str, bool]] = field(default_factory=dict)
    # nearmiss_id ("player:field") -> host accept_bool
    overrides: dict[str, bool] = field(default_factory=dict)
    resolved: bool = False


# ------------------------------------------------------------------
# Option builder helpers
# ------------------------------------------------------------------


def build_movie_options(song: dict[str, Any]) -> list[str] | None:
    """
    Build shuffled movie options from song data (Issue #28).

    Args:
        song: Song dictionary with 'movie' and 'movie_choices'

    Returns:
        Shuffled list of movie options, or None if insufficient data

    """
    movie = song.get("movie", "")
    if isinstance(movie, str):
        movie = movie.strip()
    else:
        movie = ""

    movie_choices = song.get("movie_choices", [])

    # Validate required data
    if not movie:
        return None

    if not movie_choices or not isinstance(movie_choices, list):
        return None

    # Filter valid choices and deduplicate while preserving order
    valid_choices = list(
        dict.fromkeys(
            c.strip() for c in movie_choices if isinstance(c, str) and c.strip()
        )
    )

    # Ensure correct movie is included
    if movie not in valid_choices:
        valid_choices.insert(0, movie)

    if len(valid_choices) < 2:
        return None

    # Trim to exactly 3 options (correct + 2 decoys), keeping correct movie
    if len(valid_choices) > 3:
        others = [c for c in valid_choices if c != movie]
        valid_choices = [movie] + others[:2]

    # Shuffle and return
    random.shuffle(valid_choices)

    return valid_choices


def build_artist_options(song: dict[str, Any]) -> list[str] | None:
    """
    Build shuffled artist options from song data (Story 20.2).

    Args:
        song: Song dictionary with 'artist' and optional 'alt_artists'

    Returns:
        Shuffled list of artist options, or None if insufficient data

    """
    artist = song.get("artist", "")
    if isinstance(artist, str):
        artist = artist.strip()
    else:
        artist = ""

    alt_artists = song.get("alt_artists", [])

    # Validate required data
    if not artist:
        return None

    if not alt_artists or not isinstance(alt_artists, list):
        return None

    # Filter valid alternatives
    valid_alts = [a.strip() for a in alt_artists if isinstance(a, str) and a.strip()]

    if not valid_alts:
        return None

    # Build and shuffle options
    options = [artist] + valid_alts
    random.shuffle(options)

    return options


# ------------------------------------------------------------------
# ChallengeManager
# ------------------------------------------------------------------


class ChallengeManager:
    """Manages artist challenge and movie quiz challenge state."""

    def __init__(self) -> None:
        """Initialize challenge manager with default state."""
        self.artist_challenge: ArtistChallenge | None = None
        self.artist_challenge_enabled: bool = False

        self.movie_challenge: MovieChallenge | None = None
        self.movie_quiz_enabled: bool = False

        # Issue #1180: Title & Artist guessing mode
        self.title_artist_mode: bool = False
        self.title_artist_challenge: TitleArtistChallenge | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        artist_challenge_enabled: bool = True,
        movie_quiz_enabled: bool = True,
        title_artist_mode: bool = False,
    ) -> None:
        """
        Set challenge configuration for a new game.

        Args:
            artist_challenge_enabled: Whether to enable artist guessing
            movie_quiz_enabled: Whether to enable movie quiz bonus
            title_artist_mode: Whether title/artist guessing replaces the year guess

        """
        self.artist_challenge_enabled = artist_challenge_enabled
        self.artist_challenge = None

        self.movie_quiz_enabled = movie_quiz_enabled
        self.movie_challenge = None

        self.title_artist_mode = title_artist_mode
        self.title_artist_challenge = None

    def reset(self) -> None:
        """Reset challenge state (for game reset / end)."""
        self.artist_challenge = None
        self.artist_challenge_enabled = True  # Reset to default (Story 20.7)

        self.movie_challenge = None
        self.movie_quiz_enabled = True  # Reset to default

        # Issue #1180: Title & Artist mode is opt-in, default off
        self.title_artist_challenge = None
        self.title_artist_mode = False

    # ------------------------------------------------------------------
    # Round initialization
    # ------------------------------------------------------------------

    def init_round(self, song: dict[str, Any]) -> None:
        """
        Initialize challenges for a new round.

        Args:
            song: Song dict with artist/movie info from playlist

        """
        self.artist_challenge = self._init_artist_challenge(song)
        self.movie_challenge = self._init_movie_challenge(song)
        self.title_artist_challenge = self._init_title_artist_challenge(song)

    def _init_title_artist_challenge(
        self, song: dict[str, Any]
    ) -> TitleArtistChallenge | None:
        """
        Initialize the title/artist challenge for a round (Issue #1180).

        Args:
            song: Song dict with title/artist info from playlist

        Returns:
            TitleArtistChallenge instance or None if mode disabled.

        """
        if not self.title_artist_mode:
            return None

        title = song.get("title", "")
        title = title.strip() if isinstance(title, str) else ""
        artist = song.get("artist", "")
        artist = artist.strip() if isinstance(artist, str) else ""

        return TitleArtistChallenge(
            correct_title=title,
            correct_artist=artist,
            guesses={},
            votes={},
            overrides={},
        )

    def _init_artist_challenge(self, song: dict[str, Any]) -> ArtistChallenge | None:
        """
        Initialize artist challenge for a round (Story 20.2).

        Args:
            song: Song dict with artist info from playlist

        Returns:
            ArtistChallenge instance or None if artist challenge disabled
            or song lacks alt_artists data.

        """
        if not self.artist_challenge_enabled:
            return None

        options = build_artist_options(song)

        if not options or len(options) < 2:
            _LOGGER.debug("Skipping artist challenge: insufficient options")
            return None

        artist = song.get("artist", "")
        if isinstance(artist, str):
            artist = artist.strip()
        else:
            artist = ""

        return ArtistChallenge(
            correct_artist=artist,
            options=options,
            winner=None,
            winner_time=None,
        )

    def _init_movie_challenge(self, song: dict[str, Any]) -> MovieChallenge | None:
        """
        Initialize movie quiz challenge for a round (Issue #28).

        Args:
            song: Song dict with movie info from playlist

        Returns:
            MovieChallenge instance or None if movie quiz disabled
            or song lacks movie_choices data.

        """
        if not self.movie_quiz_enabled:
            return None

        options = build_movie_options(song)

        if not options or len(options) < 2:
            _LOGGER.debug("Skipping movie quiz: insufficient options")
            return None

        movie = song.get("movie", "")
        if isinstance(movie, str):
            movie = movie.strip()
        else:
            movie = ""

        if not movie:
            return None

        return MovieChallenge(
            correct_movie=movie,
            options=options,
            correct_guesses=[],
            wrong_guesses=[],
        )

    # ------------------------------------------------------------------
    # Guess submission
    # ------------------------------------------------------------------

    def submit_artist_guess(
        self, player_name: str, artist: str, guess_time: float
    ) -> dict[str, Any]:
        """
        Submit artist guess for bonus points (Story 20.3).

        Args:
            player_name: Name of player guessing
            artist: Artist name guessed
            guess_time: Timestamp of guess

        Returns:
            Dict with keys: correct (bool), first (bool), winner (str|None)

        Raises:
            ValueError: If no artist challenge active

        """
        if not self.artist_challenge:
            raise ValueError("No artist challenge active")

        # Case-insensitive comparison
        correct = artist.strip().lower() == self.artist_challenge.correct_artist.lower()

        result: dict[str, Any] = {
            "correct": correct,
            "first": False,
            "winner": self.artist_challenge.winner,
        }

        if correct and not self.artist_challenge.winner:
            # First correct guess!
            self.artist_challenge.winner = player_name
            self.artist_challenge.winner_time = guess_time
            result["first"] = True
            result["winner"] = player_name
            _LOGGER.info("Artist challenge won by %s", player_name)

        return result

    def submit_movie_guess(
        self,
        player_name: str,
        movie: str,
        guess_time: float,
        round_start_time: float | None,
    ) -> dict[str, Any]:
        """
        Submit movie guess for bonus points (Issue #28).

        Uses server-side timing. Correct guesses are ranked by speed
        for tiered bonus scoring (5/3/1 points).

        Args:
            player_name: Name of player guessing
            movie: Movie title guessed
            guess_time: Server timestamp of guess (time.time())
            round_start_time: Round start timestamp for elapsed time calculation

        Returns:
            Dict with keys: correct (bool), rank (int|None),
            bonus (int), already_guessed (bool)

        Raises:
            ValueError: If no movie challenge active

        """
        if not self.movie_challenge:
            raise ValueError("No movie challenge active")

        # Check if player already guessed
        for g in self.movie_challenge.correct_guesses:
            if g["name"] == player_name:
                return {
                    "correct": True,
                    "already_guessed": True,
                    "rank": None,
                    "bonus": 0,
                }
        for g in self.movie_challenge.wrong_guesses:
            if g["name"] == player_name:
                return {
                    "correct": False,
                    "already_guessed": True,
                    "rank": None,
                    "bonus": 0,
                }

        # Calculate elapsed time from round start (server-side timing)
        elapsed = 0.0
        if round_start_time is not None:
            elapsed = guess_time - round_start_time

        # Case-insensitive comparison
        correct = movie.strip().lower() == self.movie_challenge.correct_movie.lower()

        result: dict[str, Any] = {
            "correct": correct,
            "already_guessed": False,
            "rank": None,
            "bonus": 0,
        }

        if correct:
            self.movie_challenge.correct_guesses.append(
                {"name": player_name, "time": elapsed}
            )
            # Sort by time (fastest first) - ensures ranking is consistent
            self.movie_challenge.correct_guesses.sort(key=lambda g: g["time"])
            # Determine rank (0-indexed position)
            rank = next(
                i
                for i, g in enumerate(self.movie_challenge.correct_guesses)
                if g["name"] == player_name
            )
            bonus = MOVIE_BONUS_TIERS[rank] if rank < len(MOVIE_BONUS_TIERS) else 0
            result["rank"] = rank + 1  # 1-indexed for display
            result["bonus"] = bonus
            _LOGGER.info(
                "Movie quiz correct by %s (rank #%d, +%d bonus, %.2fs)",
                player_name,
                rank + 1,
                bonus,
                elapsed,
            )
        else:
            self.movie_challenge.wrong_guesses.append(
                {"name": player_name, "guess": movie.strip()}
            )
            _LOGGER.debug(
                "Movie quiz wrong by %s: '%s' (correct: '%s')",
                player_name,
                movie.strip(),
                self.movie_challenge.correct_movie,
            )

        return result

    # ------------------------------------------------------------------
    # Title & Artist guess submission + voting (Issue #1180)
    # ------------------------------------------------------------------

    def submit_title_artist_guess(
        self, player_name: str, title: str, artist: str, ts: float
    ) -> dict[str, str]:
        """
        Submit a title + artist guess; classify each field independently.

        Args:
            player_name: Name of the player guessing
            title: Raw title guess (may be empty)
            artist: Raw artist guess (may be empty)
            ts: Server timestamp of the submission

        Returns:
            Dict with keys: title_status, artist_status
            (each in exact|fuzzy|near_miss|skipped)

        Raises:
            ValueError: If no title/artist challenge active

        """
        if not self.title_artist_challenge:
            raise ValueError("No title/artist challenge active")

        title_status = classify_field(title, self.title_artist_challenge.correct_title)
        artist_status = classify_field(
            artist, self.title_artist_challenge.correct_artist
        )

        self.title_artist_challenge.guesses[player_name] = {
            "title": title,
            "artist": artist,
            "title_status": title_status,
            "artist_status": artist_status,
            "ts": ts,
        }

        return {"title_status": title_status, "artist_status": artist_status}

    def register_title_artist_vote(
        self,
        voter_name: str,
        nearmiss_id: str,
        accept: bool,  # noqa: FBT001
    ) -> None:
        """
        Record one player's vote on a near-miss (Issue #1180).

        Wired to the WS vote handler in Phase 4. A no-op if there is no
        active challenge.

        Args:
            voter_name: Name of the voting player
            nearmiss_id: "player:field" identifier of the near-miss
            accept: True for 👍 (accept), False for 👎 (reject)

        """
        if not self.title_artist_challenge:
            return
        self.title_artist_challenge.votes.setdefault(nearmiss_id, {})[voter_name] = (
            accept
        )

    def set_title_artist_override(
        self,
        nearmiss_id: str,
        accept: bool,  # noqa: FBT001
    ) -> None:
        """
        Record a host override for a near-miss (Issue #1180).

        Wired to the WS override handler in Phase 4. A no-op if there is no
        active challenge.

        Args:
            nearmiss_id: "player:field" identifier of the near-miss
            accept: True to accept, False to reject

        """
        if not self.title_artist_challenge:
            return
        self.title_artist_challenge.overrides[nearmiss_id] = accept

    def get_near_misses(self) -> list[dict[str, Any]]:
        """
        Return every near-miss field across all players (Issue #1180).

        Returns:
            List of dicts: {id, player, field, guess, votes_yes, votes_no}.
            ``field`` is "title" or "artist". Empty list if no active
            challenge or no near-misses.

        """
        if not self.title_artist_challenge:
            return []

        near_misses: list[dict[str, Any]] = []

        for player_name, guess in self.title_artist_challenge.guesses.items():
            for field_name in ("title", "artist"):
                if guess[f"{field_name}_status"] != STATUS_NEAR_MISS:
                    continue
                nearmiss_id = f"{player_name}:{field_name}"
                cast = self.title_artist_challenge.votes.get(nearmiss_id, {})
                votes_yes = sum(1 for v in cast.values() if v)
                votes_no = sum(1 for v in cast.values() if not v)
                near_misses.append(
                    {
                        "id": nearmiss_id,
                        "player": player_name,
                        "field": field_name,
                        "guess": guess[field_name],
                        "votes_yes": votes_yes,
                        "votes_no": votes_no,
                    }
                )
        return near_misses

    def has_near_misses(self) -> bool:
        """Whether any field is currently a near-miss (Issue #1180)."""
        return bool(self.get_near_misses())

    def get_near_miss_outcomes(self) -> list[dict[str, Any]]:
        """Return the resolved verdict for every near-miss that went to a vote.

        Only populated AFTER the challenge is resolved — while voting is open the
        live tally lives in ``get_near_misses`` instead. Accepted near-misses flip
        to ``near_miss_accepted`` (and drop out of ``get_near_misses``), so without
        this the client can't show "accepted ✓ +5"; rejected fields stay
        ``near_miss``. Both are surfaced here with their final tally and points
        (Issue #1180, #1243).

        Returns:
            List of dicts: {id, player, field, guess, votes_yes, votes_no,
            accepted, points}. Empty list if there is no challenge, it is not
            yet resolved, or nothing went to a vote.

        """
        if not self.title_artist_challenge or not self.title_artist_challenge.resolved:
            return []

        outcomes: list[dict[str, Any]] = []
        for player_name, guess in self.title_artist_challenge.guesses.items():
            for field_name in ("title", "artist"):
                status = guess[f"{field_name}_status"]
                # exact / fuzzy / skipped were never near-misses — skip them.
                if status not in (STATUS_NEAR_MISS, STATUS_NEAR_MISS_ACCEPTED):
                    continue
                nearmiss_id = f"{player_name}:{field_name}"
                cast = self.title_artist_challenge.votes.get(nearmiss_id, {})
                accepted = status == STATUS_NEAR_MISS_ACCEPTED
                if field_name == "title":
                    points = TITLE_PARTIAL_POINTS if accepted else 0
                else:
                    points = ARTIST_PARTIAL_POINTS if accepted else 0
                outcomes.append(
                    {
                        "id": nearmiss_id,
                        "player": player_name,
                        "field": field_name,
                        "guess": guess[field_name],
                        "votes_yes": sum(1 for v in cast.values() if v),
                        "votes_no": sum(1 for v in cast.values() if not v),
                        "accepted": accepted,
                        "points": points,
                    }
                )
        return outcomes

    def resolve_title_artist(self) -> None:
        """
        Finalize all near-misses and mark the challenge resolved (Issue #1180).

        Per near-miss field, accept if:
          * a host override is present -> use the override value; else
          * cast votes exist and 👍 / (👍 + 👎) >= 0.5 (majority of cast).
        Default with no votes and no override -> reject.

        Accepted fields get their status set to "near_miss_accepted" so
        title_artist_points awards partial credit. Idempotent: a no-op if
        there is no active challenge or it is already resolved.

        """
        if not self.title_artist_challenge or self.title_artist_challenge.resolved:
            return

        for near_miss in self.get_near_misses():
            nearmiss_id = near_miss["id"]
            override = self.title_artist_challenge.overrides.get(nearmiss_id)
            if override is not None:
                accepted = override
            else:
                yes = near_miss["votes_yes"]
                no = near_miss["votes_no"]
                total = yes + no
                accepted = total > 0 and (yes / total) >= 0.5

            if accepted:
                player = near_miss["player"]
                field_name = near_miss["field"]
                self.title_artist_challenge.guesses[player][f"{field_name}_status"] = (
                    STATUS_NEAR_MISS_ACCEPTED
                )

        self.title_artist_challenge.resolved = True

    def title_artist_points(self, player_name: str) -> tuple[int, int]:
        """
        Return (title_pts, artist_pts) for a player (Issue #1180).

        exact/fuzzy -> full points; near_miss_accepted -> partial points;
        anything else (near_miss/skipped/unknown) -> 0.

        Args:
            player_name: Name of the player

        Returns:
            (title_pts, artist_pts)

        """
        if not self.title_artist_challenge:
            return 0, 0
        guess = self.title_artist_challenge.guesses.get(player_name)
        if not guess:
            return 0, 0

        title_pts = self._field_points(
            guess["title_status"], TITLE_POINTS, TITLE_PARTIAL_POINTS
        )
        artist_pts = self._field_points(
            guess["artist_status"], ARTIST_POINTS, ARTIST_PARTIAL_POINTS
        )
        return title_pts, artist_pts

    def title_artist_status(self, player_name: str) -> str:
        """
        Return the stored title field status for a player (Issue #1180).

        Used by scoring to decide streak ("correct") on the title field.
        Returns "skipped" if the player has no stored guess.

        """
        if not self.title_artist_challenge:
            return "skipped"
        guess = self.title_artist_challenge.guesses.get(player_name)
        if not guess:
            return "skipped"
        return guess["title_status"]

    @staticmethod
    def _field_points(status: str, full: int, partial: int) -> int:
        """Map a stored field status to awarded points."""
        if status in (STATUS_EXACT, STATUS_FUZZY):
            return full
        if status == STATUS_NEAR_MISS_ACCEPTED:
            return partial
        return 0

    # ------------------------------------------------------------------
    # State serialization helpers
    # ------------------------------------------------------------------

    def get_artist_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """
        Get artist challenge state for broadcast, or None if inactive.

        Args:
            include_answer: If True, include correct_artist (for REVEAL phase).

        """
        if self.artist_challenge_enabled and self.artist_challenge:
            return self.artist_challenge.to_dict(include_answer=include_answer)
        return None

    def get_movie_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """
        Get movie challenge state for broadcast, or None if inactive.

        Args:
            include_answer: If True, include correct_movie and results (for REVEAL).

        """
        if self.movie_quiz_enabled and self.movie_challenge:
            return self.movie_challenge.to_dict(include_answer=include_answer)
        return None

    def get_title_artist_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """
        Get title/artist challenge state for broadcast, or None if inactive (#1180).

        PLAYING (include_answer=False): ``{"active": True}`` with NO truth, or
        None when the mode/challenge is inactive. REVEAL (include_answer=True):
        truth + per-player results + (Phase 4) voting state. ``near_misses`` and
        ``voting_open`` are emitted as empty/False here and filled by Phase 4.

        Args:
            include_answer: If True, include the truth + results (for REVEAL).

        """
        if not self.title_artist_mode or self.title_artist_challenge is None:
            return None

        if not include_answer:
            return {"active": True}

        results = [
            {
                "player": name,
                "title": g.get("title", ""),
                "artist": g.get("artist", ""),
                "title_status": g.get("title_status", ""),
                "artist_status": g.get("artist_status", ""),
            }
            for name, g in self.title_artist_challenge.guesses.items()
        ]
        return {
            "correct_title": self.title_artist_challenge.correct_title,
            "correct_artist": self.title_artist_challenge.correct_artist,
            "results": results,
            "near_misses": [],
            "near_miss_outcomes": [],
            "voting_open": False,
        }
