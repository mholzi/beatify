"""Challenge-delegation subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the media/lights extraction,
PR #1335): the **challenge-delegation** cluster is pulled out of the
``game/state.py`` God-Object into this ``ChallengeMixin``.

The cluster is the thin pass-through layer between ``GameState`` and the
:class:`~custom_components.beatify.game.challenges.ChallengeManager`:

* artist-challenge / movie-quiz / title-artist state properties (getters +
  setters that forward to ``self._challenge_manager``),
* the per-mode challenge-dict builders
  (``get_artist_challenge_dict`` / ``get_movie_challenge_dict`` /
  ``get_title_artist_challenge_dict``),
* the Title & Artist vote-delegation surface (``register_title_artist_vote``,
  ``set_title_artist_override``, ``get_near_misses``, ``has_near_misses``,
  ``get_near_miss_outcomes``, ``is_title_artist_voting_open``,
  ``title_artist_vote_seconds_remaining``) — originally #1180 Phase 4, and
* the three ``submit_*_guess`` entry points (Stories 20.3 / #28 / #1180).

The mixin is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState``, so its public API and every caller / test
are unchanged.

The mixin relies on attributes the host class owns and that live on ``self``
at runtime:

* ``self._challenge_manager`` — :class:`ChallengeManager`, the actual
  challenge state + logic this layer delegates to.
* ``self._title_artist_voting_open`` / ``self._title_artist_vote_deadline`` —
  the server-owned REVEAL vote-window flag + deadline (in ``self._now`` units).
  These are **read** here; the vote-window scheduling that **writes** them
  stays on ``GameState`` (it is coupled to the round scoring lock /
  auto-advance task and is deliberately not part of this cut).
* ``self._now`` — the monotonic-ish clock callable used for the vote deadline.
* ``self.round_start_time`` — passed through to the movie-guess submission.

It carries no state of its own and imports nothing from ``state.py`` at
runtime (``ArtistChallenge`` / ``MovieChallenge`` are typing-only imports), so
the extraction introduces no cyclic imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .challenges import ArtistChallenge, MovieChallenge


class ChallengeMixin:
    """Challenge-delegation behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads.
    """

    # ------------------------------------------------------------------
    # Challenge delegation properties (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def artist_challenge(self) -> ArtistChallenge | None:
        """Current artist challenge state."""
        return self._challenge_manager.artist_challenge

    @artist_challenge.setter
    def artist_challenge(self, value: ArtistChallenge | None) -> None:
        self._challenge_manager.artist_challenge = value

    @property
    def artist_challenge_enabled(self) -> bool:
        """Whether artist challenge is enabled."""
        return self._challenge_manager.artist_challenge_enabled

    @artist_challenge_enabled.setter
    def artist_challenge_enabled(self, value: bool) -> None:
        self._challenge_manager.artist_challenge_enabled = value

    @property
    def movie_challenge(self) -> MovieChallenge | None:
        """Current movie quiz challenge state."""
        return self._challenge_manager.movie_challenge

    @movie_challenge.setter
    def movie_challenge(self, value: MovieChallenge | None) -> None:
        self._challenge_manager.movie_challenge = value

    @property
    def movie_quiz_enabled(self) -> bool:
        """Whether movie quiz is enabled."""
        return self._challenge_manager.movie_quiz_enabled

    @movie_quiz_enabled.setter
    def movie_quiz_enabled(self, value: bool) -> None:
        self._challenge_manager.movie_quiz_enabled = value

    @property
    def title_artist_mode(self) -> bool:
        """Whether title/artist guessing mode is enabled (Issue #1180)."""
        return self._challenge_manager.title_artist_mode

    @title_artist_mode.setter
    def title_artist_mode(self, value: bool) -> None:
        self._challenge_manager.title_artist_mode = value

    @property
    def title_artist_challenge(self) -> Any:
        """Current title/artist challenge state (Issue #1180)."""
        return self._challenge_manager.title_artist_challenge

    @title_artist_challenge.setter
    def title_artist_challenge(self, value: Any) -> None:
        self._challenge_manager.title_artist_challenge = value

    def get_artist_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """Build artist challenge dict — delegated to ChallengeManager."""
        return self._challenge_manager.get_artist_challenge_dict(
            include_answer=include_answer
        )

    def get_movie_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """Build movie challenge dict — delegated to ChallengeManager."""
        return self._challenge_manager.get_movie_challenge_dict(
            include_answer=include_answer
        )

    def get_title_artist_challenge_dict(
        self, *, include_answer: bool
    ) -> dict[str, Any] | None:
        """Build Title & Artist challenge dict — delegated to ChallengeManager (#1180).

        PLAYING (include_answer=False): {"active": True} with NO truth, or None
        when the mode/challenge is inactive. REVEAL (include_answer=True):
        truth + per-player results + (Phase 4) voting state.
        """
        challenge_dict = self._challenge_manager.get_title_artist_challenge_dict(
            include_answer=include_answer
        )
        # Phase 4 (#1180): surface the vote-eligible near-misses tally and the
        # REVEAL vote window flag so the player vote cards / host override
        # controls can render. ``_title_artist_voting_open`` lives on GameState,
        # so the truth-bearing REVEAL dict is finalized here, not in the manager.
        if include_answer and challenge_dict is not None:
            challenge_dict["near_misses"] = self.get_near_misses()
            challenge_dict["near_miss_outcomes"] = self.get_near_miss_outcomes()
            challenge_dict["voting_open"] = self.is_title_artist_voting_open()
            challenge_dict["vote_seconds_remaining"] = (
                self.title_artist_vote_seconds_remaining()
            )
        return challenge_dict

    def title_artist_vote_seconds_remaining(self) -> int:
        """Whole seconds left in the open vote window, server-authoritative.

        Computed from the server-owned deadline against the same clock that set
        it, so clients never compare their wall clock to the server's. Returns 0
        when voting is closed or no deadline is set (#1180).
        """
        if (
            not self._title_artist_voting_open
            or self._title_artist_vote_deadline is None
        ):
            return 0
        return max(0, round(self._title_artist_vote_deadline - self._now()))

    # ------------------------------------------------------------------
    # Title/Artist vote delegation (#1180 Phase 4)
    # ------------------------------------------------------------------

    def register_title_artist_vote(
        self, voter_name: str, nearmiss_id: str, accept: bool
    ) -> None:
        """Record a community vote on a near-miss — delegates to ChallengeManager."""
        self._challenge_manager.register_title_artist_vote(
            voter_name, nearmiss_id, accept
        )

    def set_title_artist_override(self, nearmiss_id: str, accept: bool) -> None:
        """Record a host override on a near-miss — delegates to ChallengeManager."""
        self._challenge_manager.set_title_artist_override(nearmiss_id, accept)

    def get_near_misses(self) -> list[dict[str, Any]]:
        """List vote-eligible near-misses — delegates to ChallengeManager."""
        return self._challenge_manager.get_near_misses()

    def has_near_misses(self) -> bool:
        """True if any near-miss is vote-eligible — delegates to ChallengeManager."""
        return self._challenge_manager.has_near_misses()

    def get_near_miss_outcomes(self) -> list[dict[str, Any]]:
        """Resolved near-miss verdicts — delegates to ChallengeManager (#1180)."""
        return self._challenge_manager.get_near_miss_outcomes()

    def is_title_artist_voting_open(self) -> bool:
        """True while the conditional REVEAL vote window is open (#1180 P4)."""
        return self._title_artist_voting_open

    # ------------------------------------------------------------------
    # Challenge guess submission entry points
    # ------------------------------------------------------------------

    def submit_artist_guess(
        self, player_name: str, artist: str, guess_time: float
    ) -> dict[str, Any]:
        """Submit artist guess for bonus points (Story 20.3). Delegates to ChallengeManager."""
        return self._challenge_manager.submit_artist_guess(
            player_name, artist, guess_time
        )

    def submit_movie_guess(
        self, player_name: str, movie: str, guess_time: float
    ) -> dict[str, Any]:
        """Submit movie guess for bonus points (Issue #28). Delegates to ChallengeManager."""
        return self._challenge_manager.submit_movie_guess(
            player_name, movie, guess_time, self.round_start_time
        )

    def submit_title_artist_guess(
        self, player_name: str, title: str, artist: str, ts: float
    ) -> dict[str, Any]:
        """Submit a Title & Artist guess (#1180). Delegates to ChallengeManager.

        Returns {"title_status": str, "artist_status": str}; classification and
        storage live on the challenge.
        """
        return self._challenge_manager.submit_title_artist_guess(
            player_name, title, artist, ts
        )
