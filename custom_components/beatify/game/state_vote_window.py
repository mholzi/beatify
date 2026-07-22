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
* ``self._append_round_results`` — the shared round_results classifier (owned by
  :class:`RoundScoringMixin`); called after the deferred scoring pass so the
  share grid reflects the resolved title/artist field statuses (#1373).
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

    def all_crowd_court_votes_in(self) -> bool:
        """True when every eligible voter has voted on every near-miss (#1667).

        The vote window's job is to give the room time to weigh in; once the
        room has, waiting out the rest of the 30 s is dead air. This is the
        same idea as ``all_submitted`` for guesses, applied to the REVEAL vote.

        Eligibility mirrors the two rules the WS handler already enforces:

        * **Active players only.** Uses ``is_active`` rather than the raw
          ``connected`` flag, so a stale ghost (closed socket not yet reaped,
          #928) cannot hold the whole room hostage — and eliminated players
          (#827) are out, exactly as in ``PlayerRegistry.all_submitted``.
        * **No self-votes.** ``guessing.py`` rejects a vote on one's own
          near-miss, so the owner is not counted as an eligible voter for it.
          Counting them would make early resolve unreachable for any near-miss.

        Returns False when there is nothing to decide (no near-misses, or a
        near-miss whose only possible voter is its own owner) — the caller then
        simply lets the timer run, which is the pre-#1667 behaviour and never
        resolves *earlier* than the host expects.
        """
        near_misses = self.get_near_misses()
        if not near_misses:
            return False
        active = [
            p.name
            for p in self.players.values()
            if getattr(p, "is_active", False) and not p.eliminated
        ]
        if not active:
            return False
        # get_near_misses() already returns [] without an active challenge, so
        # this cannot be None here — read defensively anyway, because a future
        # caller reaching this method by another path should not crash REVEAL.
        challenge = self._challenge_manager.title_artist_challenge
        if challenge is None:
            return False
        votes = challenge.votes
        for near_miss in near_misses:
            owner = near_miss["id"].rsplit(":", 1)[0]
            eligible = [name for name in active if name != owner]
            if not eligible:
                # Solo game, or the only other players left. Nobody may vote on
                # this one, so "everyone has voted" can never become true —
                # fall back to the timer instead of resolving instantly.
                return False
            cast = votes.get(near_miss["id"], {})
            if any(name not in cast for name in eligible):
                return False
        return True

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
                # #1667: everyone eligible has voted — resolve now instead of
                # staring at a countdown nobody is going to change. Checked in
                # the existing poll rather than pushed from the vote handler on
                # purpose: no second task, no new cancellation path, and the
                # worst case is resolving up to one poll (0.5 s) late.
                if self.all_crowd_court_votes_in():
                    _LOGGER.debug(
                        "Crowd-Court: all votes in after %.1fs of %ss — "
                        "resolving early (#1667)",
                        elapsed,
                        window_seconds,
                    )
                    break
            # Window over — either expired naturally or every vote is in.
            # Clear the handle first so a manual start_round's
            # _cancel_auto_advance() can't cancel this task.
            self._auto_advance_task = None
            if self.phase != GamePhase.REVEAL:
                return
            await self._finalize_title_artist_window()
            if self._on_round_end:
                try:
                    await self._on_round_end()
                except (ConnectionError, OSError, TypeError) as err:
                    _LOGGER.error("Vote-window broadcast failed: %s", err)
            # #1755: opening the vote window took over the _auto_advance_task
            # slot, so REVEAL is now parked with no song-end advance armed. Re-arm
            # it so an unattended title/artist near-miss round still advances at
            # song-end (never-stall invariant #1012) — and a final unattended
            # round still reaches END — instead of holding on REVEAL until the
            # host taps Next. Only re-arm while still in REVEAL (a manual advance
            # or end during the broadcast would have moved the phase on).
            if self.phase == GamePhase.REVEAL:
                self._schedule_song_end_auto_advance()
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
            # #1747: the deferred title/artist scores are now final, so run the
            # Sudden Death cut that _end_round_unlocked deferred for this path.
            # Guarded by voting_open above so it runs exactly once per round (the
            # host-advance and window-expiry races both resolve through here).
            # Caller-held _score_lock is required by _apply_sudden_death_elimination.
            self._apply_sudden_death_elimination()
            # #1724: the deferred scores are now final too, so run the halfway
            # comeback-token grant that _end_round_unlocked deferred for this
            # path. Idempotent per game via the per-player granted flag.
            self._maybe_grant_comeback_tokens()

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
        # #1373: append round_results here for the deferred title/artist path —
        # the main scoring pass skipped it so this classifies the resolved
        # field statuses (years_off is None in this mode) instead of "missed".
        self._append_round_results()

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
