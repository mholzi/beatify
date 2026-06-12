"""Title & Artist vote-window subsystem for :class:`GameState`.

Issue #1271 next-increment extraction: the **title/artist REVEAL vote-window**
cluster is pulled out of the ``game/state.py`` God-Object into this
``VoteWindowMixin``.

This is the scheduling + finalization half that the challenge-delegation cut
(:class:`~custom_components.beatify.game.state_challenge.ChallengeMixin`)
deliberately left behind — there the *read* surface (``is_title_artist_voting_open``,
``title_artist_vote_seconds_remaining``, …) was extracted, while the writers
that own the REVEAL dwell stayed on ``GameState`` because they are coupled to
the round scoring lock and the auto-advance task. This mixin now carries that
writer cluster (#1180 Phase 4):

* ``_schedule_title_artist_vote_window`` — opens (or skips) the conditional 30s
  near-miss window from the round-end path; reuses the ``_auto_advance_task``
  slot so a manual advance / pause / end cancels it.
* ``_title_artist_vote_window`` — the window task that holds REVEAL open, then
  finalizes near-misses, scores the deferred round, and re-broadcasts on expiry.
* ``_finalize_title_artist_window`` — resolves near-misses and applies the
  deferred title/artist scoring pass under the score lock (idempotent via the
  ``voting_open`` guard).
* ``_score_title_artist_round`` — the deferred per-player scoring pass; caller
  holds the lock.
* ``resolve_title_artist_if_pending`` — finalizes an open window early when the
  host advances (called from the next_round admin handler).

The mixin is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState``, so its public API and every caller / test
are unchanged.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.title_artist_mode`` — whether the title/artist challenge mode is on
  (a :class:`ChallengeMixin` property).
* ``self.has_near_misses`` / ``self._challenge_manager.resolve_title_artist``
  — the near-miss query + resolution surface delegated to the
  :class:`~custom_components.beatify.game.challenges.ChallengeManager`.
* ``self._title_artist_voting_open`` / ``self._title_artist_vote_deadline`` —
  the server-owned REVEAL vote-window flag + deadline (in ``self._now`` units);
  this mixin is the writer of those fields.
* ``self._now`` — the monotonic-ish clock callable used for the vote deadline.
* ``self._cancel_auto_advance`` / ``self._auto_advance_task`` — the REVEAL
  auto-advance task handle this window reuses (so a manual next_round / pause /
  end cancels the window via the same path).
* ``self._score_lock`` — the asyncio lock guarding score mutations; the
  deferred scoring pass runs under it.
* ``self._score_all_players`` — the shared per-player scoring loop (stays on
  ``GameState`` so the round-end and vote-window paths cannot drift).
* ``self.players`` / ``self.current_song`` / ``self.phase`` — round state read
  while the window is open.
* ``self._on_round_end`` — the async broadcast callback fired after expiry.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
window task (matching the ``powerups`` / ``serializers`` pattern) to avoid the
cyclic import with ``state.py`` (which imports this mixin at module load), so
the extraction introduces no import cycle.
"""

from __future__ import annotations

import asyncio
import logging

from custom_components.beatify.const import (
    TITLE_ARTIST_VOTE_WINDOW_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class VoteWindowMixin:
    """Title & Artist REVEAL vote-window behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads/writes.
    """

    def _schedule_title_artist_vote_window(self) -> None:
        """Open or skip the conditional 30s near-miss vote window (#1180 P4).

        Called from _end_round_unlocked while phase is REVEAL and title/artist
        mode is on. If there are near-misses, flip voting_open and spawn the
        window task (reused _auto_advance_task slot so a manual next_round,
        pause or end cancels it via _cancel_auto_advance). With no near-misses,
        resolve immediately so scoring/advance proceed unchanged.
        """
        if not self.title_artist_mode:
            return
        if self.has_near_misses():
            self._title_artist_voting_open = True
            self._title_artist_vote_deadline = (
                self._now() + TITLE_ARTIST_VOTE_WINDOW_SECONDS
            )
            self._cancel_auto_advance()
            self._auto_advance_task = asyncio.create_task(
                self._title_artist_vote_window(TITLE_ARTIST_VOTE_WINDOW_SECONDS)
            )
        else:
            # No vote-eligible fields — finalize now (everything exact/fuzzy/
            # skipped), no window, advance behaves exactly as the year mode.
            self._challenge_manager.resolve_title_artist()
            self._title_artist_voting_open = False
            self._title_artist_vote_deadline = None

    async def _title_artist_vote_window(self, window_seconds: int) -> None:
        """Hold REVEAL open for community voting, then resolve (#1180 P4).

        Sleeps in short polls so a manual host-advance / pause / end can
        cancel promptly. On natural expiry, finalizes near-misses via
        resolve_title_artist, scores the deferred round, then re-broadcasts so
        the accepted points and closed window reach every client. A late firing
        is a no-op once the phase has left REVEAL.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        poll = 0.5
        try:
            elapsed = 0.0
            while elapsed < window_seconds:
                await asyncio.sleep(poll)
                elapsed += poll
                if self.phase != GamePhase.REVEAL:
                    return  # advanced / paused / ended elsewhere
            # Window expired naturally — clear the handle first so a manual
            # start_round's _cancel_auto_advance() can't cancel this task.
            self._auto_advance_task = None
            if self.phase != GamePhase.REVEAL:
                return
            await self._finalize_title_artist_window()
            if self._on_round_end:
                try:
                    await self._on_round_end()
                except (ConnectionError, OSError, TypeError) as err:
                    _LOGGER.error("Vote-window broadcast failed: %s", err)
        except asyncio.CancelledError:
            # #1359: defense in depth — when end_game/next_round/pause cancels
            # this task mid-window, clear the vote-window flags so they can't
            # leak True into the next game (where they'd disable REVEAL
            # auto-advance and double-score a round). end_game/create_game also
            # reset these, but clearing here keeps the flag honest for any path
            # that cancels without a full reset.
            self._title_artist_voting_open = False
            self._title_artist_vote_deadline = None
            _LOGGER.debug("Title/artist vote window cancelled")
            raise

    async def _finalize_title_artist_window(self) -> None:
        """Resolve near-misses and apply title/artist scoring (#1180 P4).

        Guarded by voting_open so a host-advance + timer expiry race resolves
        exactly once. Scoring was deferred out of _end_round_unlocked's main
        loop (the per-player score depends on the final near-miss resolution),
        so this runs the single, post-resolve scoring pass under the score lock
        — accepted near-misses are now reflected in the leaderboard.
        """
        if not self._title_artist_voting_open:
            return
        self._title_artist_voting_open = False
        self._title_artist_vote_deadline = None
        self._challenge_manager.resolve_title_artist()
        async with self._score_lock:
            await self._score_title_artist_round()

    async def _score_title_artist_round(self) -> None:
        """Run the deferred title/artist scoring pass. Caller holds the lock.

        Scores every player exactly once now that near-misses are resolved,
        reusing _score_all_players so this path and _end_round_unlocked share
        one scoring loop. Players were intentionally NOT scored in the main
        loop (defer_title_artist), so this is the first and only score for the
        round — no double-counting.
        """
        correct_year = self.current_song.get("year") if self.current_song else None
        all_players = list(self.players.values())
        self._score_all_players(correct_year, all_players)

    async def resolve_title_artist_if_pending(self) -> None:
        """Finalize an open vote window early (host advanced) (#1180 P4).

        Called from the next_round admin handler before it starts the next
        round / ends the game, so accepted near-misses are scored first.
        Cancels the pending window task and finalizes. No-op when the window
        isn't open (year mode, no near-misses, or already resolved).
        """
        if not self._title_artist_voting_open:
            return
        self._cancel_auto_advance()
        await self._finalize_title_artist_window()
