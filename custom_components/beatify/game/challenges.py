"""Challenge management for Beatify (artist + movie quiz challenges)."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from custom_components.beatify.const import MOVIE_BONUS_TIERS

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
    valid_choices = list(dict.fromkeys(
        c.strip() for c in movie_choices if isinstance(c, str) and c.strip()
    ))

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

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        *,
        artist_challenge_enabled: bool = True,
        movie_quiz_enabled: bool = True,
    ) -> None:
        """
        Set challenge configuration for a new game.

        Args:
            artist_challenge_enabled: Whether to enable artist guessing
            movie_quiz_enabled: Whether to enable movie quiz bonus

        """
        self.artist_challenge_enabled = artist_challenge_enabled
        self.artist_challenge = None

        self.movie_quiz_enabled = movie_quiz_enabled
        self.movie_challenge = None

    def reset(self) -> None:
        """Reset challenge state (for game reset / end)."""
        self.artist_challenge = None
        self.artist_challenge_enabled = True  # Reset to default (Story 20.7)

        self.movie_challenge = None
        self.movie_quiz_enabled = True  # Reset to default

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
