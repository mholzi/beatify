"""RoundManager delegation properties for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the round-timer / REVEAL
transition cut
:class:`~custom_components.beatify.game.state_reveal_transition.RevealTransitionMixin`):
the **RoundManager delegation property cluster** is pulled out of the
``game/state.py`` God-Object into this ``RoundManagerDelegationMixin``.

The cluster is the read-only / setter ``@property`` facade that keeps the
``GameState`` public interface identical while the round-scoped attributes
themselves live on the owned :class:`RoundManager`. It is **behavior-
preserving**: it carries the exact same properties that previously lived on
``GameState``, so its public API and every caller / test are unchanged.

The properties delegated to ``self._round_manager``:

* ``round`` / ``total_rounds`` — round number + total-round count.
* ``deadline`` — round deadline in ms.
* ``current_song`` — the current song dict.
* ``last_round`` — last-round flag.
* ``round_start_time`` / ``round_duration`` — round-timer anchors.
* ``song_stopped`` — playback-stopped flag.
* ``round_analytics`` — per-round analytics (stored on RoundManager for
  lifecycle coherence).
* ``intro_mode_enabled`` / ``is_intro_round`` / ``intro_stopped`` /
  ``intro_splash_pending`` — intro-mode flags (``intro_splash_pending`` is
  read-only).
* ``early_reveal`` — early-reveal flag (read-only).
* ``metadata_pending`` — album-art metadata-pending flag.

``songs_remaining`` is delegated to the optional :class:`PlaylistManager`
instead (read-only count of unplayed songs), and is grouped here as part of
the read-only round-scoped facade.

The mixin relies on attributes the host class owns and that live on ``self``
at runtime:

* ``self._round_manager`` — the owned :class:`RoundManager`; backs every
  delegated round-scoped attribute above.
* ``self._playlist_manager`` — optional :class:`PlaylistManager`; gates the
  ``songs_remaining`` count (returns ``0`` when unset).

It carries no state of its own. ``RoundManager`` / ``PlaylistManager`` are the
single source of truth; this mixin is a pure pass-through facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import RoundAnalytics


class RoundManagerDelegationMixin:
    """RoundManager / PlaylistManager delegation properties for :class:`GameState`.

    Carries the read-only / setter ``@property`` facade that keeps the
    round-scoped public interface identical while the underlying attributes
    live on the owned ``RoundManager`` (and ``PlaylistManager`` for
    ``songs_remaining``) (#1271 extraction). See the module docstring for the
    full attribute contract this mixin expects on ``self`` at runtime.
    """

    @property
    def round(self) -> int:
        """Current round number — delegated to RoundManager."""
        return self._round_manager.round

    @round.setter
    def round(self, value: int) -> None:
        self._round_manager.round = value

    @property
    def total_rounds(self) -> int:
        """Total rounds — delegated to RoundManager."""
        return self._round_manager.total_rounds

    @total_rounds.setter
    def total_rounds(self, value: int) -> None:
        self._round_manager.total_rounds = value

    @property
    def deadline(self) -> int | None:
        """Round deadline (ms) — delegated to RoundManager."""
        return self._round_manager.deadline

    @deadline.setter
    def deadline(self, value: int | None) -> None:
        self._round_manager.deadline = value

    @property
    def current_song(self) -> dict[str, Any] | None:
        """Current song dict — delegated to RoundManager."""
        return self._round_manager.current_song

    @current_song.setter
    def current_song(self, value: dict[str, Any] | None) -> None:
        self._round_manager.current_song = value

    @property
    def last_round(self) -> bool:
        """Whether this is the last round — delegated to RoundManager."""
        return self._round_manager.last_round

    @last_round.setter
    def last_round(self, value: bool) -> None:
        self._round_manager.last_round = value

    @property
    def round_start_time(self) -> float | None:
        """Round start timestamp — delegated to RoundManager."""
        return self._round_manager.round_start_time

    @round_start_time.setter
    def round_start_time(self, value: float | None) -> None:
        self._round_manager.round_start_time = value

    @property
    def round_duration(self) -> float:
        """Round timer duration — delegated to RoundManager."""
        return self._round_manager.round_duration

    @round_duration.setter
    def round_duration(self, value: float) -> None:
        self._round_manager.round_duration = value

    @property
    def song_stopped(self) -> bool:
        """Song stopped flag — delegated to RoundManager."""
        return self._round_manager.song_stopped

    @song_stopped.setter
    def song_stopped(self, value: bool) -> None:
        self._round_manager.song_stopped = value

    @property
    def round_analytics(self) -> RoundAnalytics | None:
        """Round analytics — stored on RoundManager for lifecycle coherence."""
        return self._round_manager.round_analytics

    @round_analytics.setter
    def round_analytics(self, value: RoundAnalytics | None) -> None:
        self._round_manager.round_analytics = value

    @property
    def intro_mode_enabled(self) -> bool:
        """Intro mode enabled — delegated to RoundManager."""
        return self._round_manager.intro_mode_enabled

    @intro_mode_enabled.setter
    def intro_mode_enabled(self, value: bool) -> None:
        self._round_manager.intro_mode_enabled = value

    @property
    def is_intro_round(self) -> bool:
        """Whether current round is intro mode — delegated to RoundManager."""
        return self._round_manager.is_intro_round

    @is_intro_round.setter
    def is_intro_round(self, value: bool) -> None:
        self._round_manager.is_intro_round = value

    @property
    def intro_stopped(self) -> bool:
        """Intro stopped flag — delegated to RoundManager."""
        return self._round_manager.intro_stopped

    @intro_stopped.setter
    def intro_stopped(self, value: bool) -> None:
        self._round_manager.intro_stopped = value

    @property
    def intro_splash_pending(self) -> bool:
        """Intro splash pending flag — delegated to RoundManager."""
        return self._round_manager._intro_splash_pending

    @property
    def early_reveal(self) -> bool:
        """Early reveal flag — delegated to RoundManager."""
        return self._round_manager._early_reveal

    @property
    def songs_remaining(self) -> int:
        """Count of unplayed songs remaining in the playlist."""
        if self._playlist_manager:
            return self._playlist_manager.get_remaining_count()
        return 0

    @property
    def metadata_pending(self) -> bool:
        """Metadata pending flag — delegated to RoundManager."""
        return self._round_manager.metadata_pending

    @metadata_pending.setter
    def metadata_pending(self, value: bool) -> None:
        self._round_manager.metadata_pending = value
