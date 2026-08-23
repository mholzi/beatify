"""TTS announcement subsystem for :class:`GameState`.

Issue #1271 first-increment extraction: the TTS / spoken-announcement
cluster (~365 lines, originally Issues #447 / #471 / #840 / #841 / #842 /
#1211) is pulled out of the ``game/state.py`` God-Object into this
``TtsAnnouncerMixin``.

The mixin is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState`` (``configure_tts``, ``disable_tts``, the
``announce_*`` family, plus the private ``_lang`` / ``_tts_announce`` /
``_announce_reveal`` helpers). ``GameState`` inherits them, so its public API
and every caller / test are unchanged.

The mixin relies on attributes that the host class owns and that live on
``self`` at runtime:

* ``self._hass`` — Home Assistant instance (for the TTS provider).
* ``self._bg_tasks`` — set of fire-and-forget background tasks.
* ``self.media_player`` — speaker entity the audio is routed through.
* ``self.language`` — game language (resolved defensively via ``_lang``).
* ``self.players`` / ``self.total_rounds`` / ``self.round`` /
  ``self.difficulty`` / ``self.closest_wins_mode`` — read for phrasing.

The ``_tts_*`` state (service handle, per-event toggles, dedup sets) is
initialized by :meth:`_init_tts_state`, which ``GameState.__init__`` calls so
the attributes exist before any announcement fires.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from . import tts_phrases

_LOGGER = logging.getLogger(__name__)


class TtsAnnouncerMixin:
    """Spoken-announcement behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads.
    """

    def _init_tts_state(self) -> None:
        """Initialize all TTS state. Called from ``GameState.__init__``.

        Kept as a single method so the (long) set of per-event toggle
        defaults lives next to the code that consumes them, instead of
        bloating ``GameState.__init__``.
        """
        # Issue #447: TTS announcement service
        self._tts_service: Any = None  # TTSService (lazy import)
        self._tts_announce_game_start: bool = True
        self._tts_announce_winner: bool = True
        # Issue #471 Phase 1: Game Flow announcements
        self._tts_announce_round_start: bool = True
        self._tts_announce_countdown: bool = (
            False  # off by default — intrusive every round
        )
        self._tts_announce_time_up: bool = True
        self._tts_announce_correct_answer: bool = True
        self._tts_announce_nobody_correct: bool = True
        # Issue #840 Phase 2: Player Achievement announcements
        self._tts_announce_exact_guess: bool = True
        self._tts_announce_closest_guess: bool = True
        self._tts_announce_streak_milestone: bool = True
        self._tts_announce_streak_broken: bool = False  # off — noisy mid-game
        self._tts_announce_leader_change: bool = True
        self._tts_announce_tied_first: bool = True
        # Leader-change detection needs the prior round's leader name.
        self._tts_previous_leader: str | None = None
        # Issue #841 Phase 3: Betting & Game State announcements
        self._tts_announce_bet_won: bool = True
        self._tts_announce_bet_lost: bool = True
        self._tts_announce_player_join: bool = True
        # off — phones re-establish the WS constantly (screen lock, network)
        self._tts_announce_player_reconnect: bool = False
        self._tts_announce_last_round: bool = True
        self._tts_announce_podium: bool = True
        self._tts_announce_rematch: bool = True
        # Issue #842 Phase 4: Special Modes announcements
        self._tts_announce_intro_round: bool = True
        self._tts_announce_steal_unlocked: bool = True
        self._tts_announce_steal_used: bool = True
        # Steal-unlock is announced once per player per game.
        self._tts_steal_unlocked_announced: set[str] = set()
        # Issue #1211: seconds to add to the deadline so the timer only starts
        # counting once music has resumed after pre-round TTS announcements.
        self._tts_pre_round_delay: float = 0.0

    async def configure_tts(
        self,
        entity_id: str,
        *,
        announce_game_start: bool = True,
        announce_winner: bool = True,
        # Issue #471 Phase 1: Game Flow announcements
        announce_round_start: bool = True,
        announce_countdown: bool = False,
        announce_time_up: bool = True,
        announce_correct_answer: bool = True,
        announce_nobody_correct: bool = True,
        # Issue #840 Phase 2: Player Achievement announcements
        announce_exact_guess: bool = True,
        announce_closest_guess: bool = True,
        announce_streak_milestone: bool = True,
        announce_streak_broken: bool = False,
        announce_leader_change: bool = True,
        announce_tied_first: bool = True,
        # Issue #841 Phase 3: Betting & Game State announcements
        announce_bet_won: bool = True,
        announce_bet_lost: bool = True,
        announce_player_join: bool = True,
        announce_player_reconnect: bool = False,
        announce_last_round: bool = True,
        announce_podium: bool = True,
        announce_rematch: bool = True,
        # Issue #842 Phase 4: Special Modes announcements
        announce_intro_round: bool = True,
        announce_steal_unlocked: bool = True,
        announce_steal_used: bool = True,
        # Issue #1211: seconds to add to the round deadline when pre-round TTS
        # fires, so the countdown only starts once music has actually resumed.
        tts_pre_round_delay: float = 0.0,
    ) -> None:
        """Configure TTS announcement service for the game.

        ``entity_id`` is the TTS provider entity (e.g. ``tts.google_gemini_tts``).
        Beatify routes the audio through the game's existing speaker
        (``self.media_player``) — see #793 for why we need both identifiers.

        The announce_* booleans toggle individual event types; defaults match
        the most common host expectation (round start + time's up + correct
        answer announced; per-round 3-2-1 countdown opt-in only).
        """
        from custom_components.beatify.services.tts import TTSService

        self._tts_service = TTSService(
            self._hass,
            tts_entity_id=entity_id,
            media_player_entity_id=self.media_player,
        )
        self._tts_announce_game_start = announce_game_start
        self._tts_announce_winner = announce_winner
        self._tts_announce_round_start = announce_round_start
        self._tts_announce_countdown = announce_countdown
        self._tts_announce_time_up = announce_time_up
        self._tts_announce_correct_answer = announce_correct_answer
        self._tts_announce_nobody_correct = announce_nobody_correct
        self._tts_announce_exact_guess = announce_exact_guess
        self._tts_announce_closest_guess = announce_closest_guess
        self._tts_announce_streak_milestone = announce_streak_milestone
        self._tts_announce_streak_broken = announce_streak_broken
        self._tts_announce_leader_change = announce_leader_change
        self._tts_announce_tied_first = announce_tied_first
        self._tts_announce_bet_won = announce_bet_won
        self._tts_announce_bet_lost = announce_bet_lost
        self._tts_announce_player_join = announce_player_join
        self._tts_announce_player_reconnect = announce_player_reconnect
        self._tts_announce_last_round = announce_last_round
        self._tts_announce_podium = announce_podium
        self._tts_announce_rematch = announce_rematch
        self._tts_announce_intro_round = announce_intro_round
        self._tts_announce_steal_unlocked = announce_steal_unlocked
        self._tts_announce_steal_used = announce_steal_used
        # Issue #1211: deadline offset to compensate for pre-round TTS overhead.
        self._tts_pre_round_delay = max(0.0, float(tts_pre_round_delay))
        # Fresh game — no prior leader, no steal unlocks announced yet.
        self._tts_previous_leader = None
        self._tts_steal_unlocked_announced = set()

    async def disable_tts(self) -> None:
        """Disable TTS announcements."""
        self._tts_service = None

    def _lang(self) -> str:
        """Resolve the game's TTS language, defaulting to English.

        ``self.language`` is injected by the start-game handlers; fall back to
        English defensively so announcements never crash if it's unset.
        """
        return tts_phrases.normalize_language(getattr(self, "language", None))

    # Rough speech rate used to estimate how long an announcement occupies the
    # speaker. Beatify never learns when audio actually FINISHES (tts.speak is
    # called with blocking=False and MA queues announcements internally), so
    # an estimate is the only signal available without polling the device.
    _TTS_WORDS_PER_SECOND = 2.6
    _TTS_OVERHEAD_S = 1.6  # provider round-trip + device chime/attention
    _TTS_MAX_ESTIMATE_S = 12.0

    @classmethod
    def _estimate_speech_seconds(cls, message: str) -> float:
        """Estimate how long `message` will occupy the speaker. Pure."""
        words = len([w for w in str(message).split() if w])
        est = cls._TTS_OVERHEAD_S + (words / cls._TTS_WORDS_PER_SECOND)
        return min(est, cls._TTS_MAX_ESTIMATE_S)

    def estimate_round_start_announcements(self) -> float:
        """Estimated seconds the ENABLED round-start announcements will take.

        Built from the very phrases ``announce_round_start`` /
        ``announce_countdown`` would speak, so the round deadline can be
        shifted by the real announcement cost instead of a hand-tuned
        "Timer delay" guess (a 60s round was starting its song with 49s left).
        """
        if not self._tts_service:
            return 0.0
        total = 0.0
        with contextlib.suppress(Exception):
            lang = self._lang()
            if getattr(self, "_tts_announce_round_start", False):
                total += self._estimate_speech_seconds(
                    tts_phrases.phrase(
                        lang,
                        "round_start",
                        round=tts_phrases.spoken_number(lang, self.round),
                    )
                )
            if getattr(self, "_tts_announce_countdown", False):
                total += self._estimate_speech_seconds(
                    tts_phrases.phrase(lang, "countdown")
                )
        return total

    def announcement_busy_seconds(self) -> float:
        """Seconds the speaker is still expected to be announcing (0 = free)."""
        until = getattr(self, "_announce_busy_until", 0.0)
        return max(0.0, until - time.monotonic())

    async def _tts_announce(self, message: str) -> None:
        """Speak a TTS announcement, serialized and staleness-guarded.

        Announcements used to be pure fire-and-forget: every call spawned a
        task that immediately handed the text to `tts.speak` with
        blocking=False. Music Assistant then queued them per player, so on a
        slow device the AUDIO lagged behind the game while the code believed
        each announcement was done the moment the service call returned. Two
        user-visible failures came out of that (both reported on voice
        satellites, both only with TTS enabled):

        * Phrases arrived out of order — the previous round's "time's up"
          played after the next round had already started, followed by that
          round's countdown.
        * Rounds skipped their song. Playback starts while the device is
          still working through queued announcements, so the play
          verification window saw the announcement instead of the expected
          track, timed out, and the song was dropped.

        Fix: announcements queue behind each other using an estimated
        duration, and an announcement that is no longer relevant when it
        reaches the front of the queue is DROPPED rather than played late —
        a "time's up" belonging to a finished round is worse than silence.
        `announcement_busy_seconds()` lets the round start wait for the
        speaker instead of racing it.
        """
        if not self._tts_service:
            return

        lock = getattr(self, "_announce_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._announce_lock = lock
        # Snapshot the context this announcement belongs to; if the game has
        # moved on by the time we reach the front of the queue, drop it.
        # Staleness keys on the ROUND ONLY. Keying on the phase too silently
        # swallowed every end-of-round announcement (reveal / "nobody got it"
        # / time's up): those are fired exactly AS the phase changes
        # PLAYING -> REVEAL, so they were always "stale" by the time they
        # reached the front of the queue. A phase change within the same
        # round is normal; only a NEW ROUND makes a pending phrase wrong.
        # #2334: `self.round`, not `current_round`. GameState has no attribute
        # by that name — it has the `round` property from
        # RoundManagerDelegationMixin, and GameState composes both mixins, so
        # it was on this object all along. With the wrong name both sides of
        # the comparison below resolved to None, `None != None` was never
        # true, and this guard has never dropped a single announcement.
        round_at_enqueue = self.round

        # RESERVE the speaker window NOW, at enqueue — not when this phrase
        # reaches the front of the queue. Everything that asks "is the speaker
        # still announcing?" runs immediately after the announcements are
        # fired (the resume watchdog arms, the round deadline is computed, the
        # song-end poll starts), so a window that only appears once speech
        # begins reads as zero to all of them. Hardware showed the cost: the
        # watchdog's anticipatory kick never fired at all, leaving the
        # observational path (2 idle polls) to do the work.
        est = self._estimate_speech_seconds(message)
        now = time.monotonic()
        start_at = max(now, getattr(self, "_announce_busy_until", 0.0))
        self._announce_busy_until = start_at + est

        async def _run() -> None:
            async with lock:
                delay = start_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                round_now = self.round
                if round_now != round_at_enqueue:
                    _LOGGER.info(
                        "TTS: dropping stale announcement (queued in round %s, "
                        "now round %s): %.40s",
                        round_at_enqueue,
                        round_now,
                        message,
                    )
                    # Give the reservation back if nothing queued behind us,
                    # so a dropped phrase doesn't hold the speaker "busy".
                    if abs(self._announce_busy_until - (start_at + est)) < 0.01:
                        self._announce_busy_until = start_at
                    return
                try:
                    await self._tts_service.speak(message, language=self._lang())
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("TTS announcement failed")
                    if abs(self._announce_busy_until - (start_at + est)) < 0.01:
                        self._announce_busy_until = start_at

        try:
            task = asyncio.create_task(_run())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except Exception:  # noqa: BLE001
            _LOGGER.warning("TTS announcement failed")

    async def announce_game_start(self) -> None:
        """Announce game start (use case 16)."""
        if not self._tts_service or not self._tts_announce_game_start:
            return
        lang = self._lang()
        message = tts_phrases.phrase(
            lang,
            "game_start",
            rounds=tts_phrases.spoken_number(lang, self.total_rounds),
            difficulty=tts_phrases.difficulty_label(lang, self.difficulty),
        )
        await self._tts_announce(message)

    async def announce_winner(self) -> None:
        """Announce the winner (use case 18)."""
        if not self._tts_service or not self._tts_announce_winner or not self.players:
            return
        lang = self._lang()
        top_score = max(p.score for p in self.players.values())
        winners = [p for p in self.players.values() if p.score == top_score]
        points = tts_phrases.spoken_number(lang, top_score)
        if len(winners) == 1:
            message = tts_phrases.phrase(
                lang, "winner_single", name=winners[0].name, points=points
            )
        else:
            names = tts_phrases.join_names(lang, [w.name for w in winners])
            message = tts_phrases.phrase(lang, "winner_tie", names=names, points=points)
        await self._tts_announce(message)

    # ------------------------------------------------------------------
    # Issue #471 Phase 1 — Game Flow announcements
    # ------------------------------------------------------------------

    async def announce_round_start(self) -> None:
        """Announce round start (use case 1). Fires after round number bump."""
        if not self._tts_service or not self._tts_announce_round_start:
            return
        lang = self._lang()
        message = tts_phrases.phrase(
            lang, "round_start", round=tts_phrases.spoken_number(lang, self.round)
        )
        await self._tts_announce(message)

    async def announce_countdown(self) -> None:
        """Announce 3-2-1 countdown before round start (use case 2).

        Single utterance, not a per-second sequence. Defaults off because
        firing on every round is intrusive — opt-in for hosts who want a
        rhythmic intro.
        """
        if not self._tts_service or not self._tts_announce_countdown:
            return
        message = tts_phrases.phrase(self._lang(), "countdown")
        await self._tts_announce(message)

    async def announce_time_up(self) -> None:
        """Announce timer expiration (use case 3). Fires only when the
        round-timer ran to zero — NOT on early-reveal (all-submitted) path.
        """
        if not self._tts_service or not self._tts_announce_time_up:
            return
        message = tts_phrases.phrase(self._lang(), "time_up")
        await self._tts_announce(message)

    async def _announce_reveal(self, correct_year: int | None) -> None:
        """Build and speak the single combined REVEAL announcement.

        The per-round REVEAL events from phases 1-4 (correct answer,
        accuracy, streaks, bet outcomes, steal unlocks, standings) used to
        fire as up to ~7 separate TTS utterances — a stutter of clips. They
        are now collected into ONE narrated sentence, each fragment still
        gated by its own ``_tts_announce_*`` toggle, so the audio flows the
        way a host would describe the round.

        Fragment order is intentional: answer → accuracy → streaks → bets →
        steal → standings.
        """
        if not self._tts_service:
            return
        lang = self._lang()
        players = list(self.players.values())
        frags: list[str] = []

        # Correct answer.
        if self._tts_announce_correct_answer and correct_year is not None:
            year = tts_phrases.spoken_number(lang, correct_year, "year")
            frags.append(tts_phrases.phrase(lang, "answer", year=year))

        # Accuracy — exact guesses, else the Closest-Wins winner, else the
        # "nobody got it" line (mutually exclusive).
        exact = [p.name for p in players if p.submitted and p.years_off == 0]
        had_submitters = any(p.submitted for p in players)
        if exact and self._tts_announce_exact_guess:
            names = tts_phrases.join_names(lang, exact)
            frags.append(tts_phrases.phrase(lang, "exact", names=names))
        elif self.closest_wins_mode and not exact and self._tts_announce_closest_guess:
            submitted = [p for p in players if p.submitted and p.years_off is not None]
            if submitted:
                winner = min(submitted, key=lambda p: p.years_off)
                if winner.round_score > 0:
                    frags.append(tts_phrases.phrase(lang, "closest", name=winner.name))
        elif had_submitters and not exact and self._tts_announce_nobody_correct:
            frags.append(tts_phrases.phrase(lang, "nobody"))

        # Streak milestones — streak_bonus is non-zero only on the exact
        # round a milestone (3/5/10/15/20/25) is reached.
        if self._tts_announce_streak_milestone:
            for p in players:
                if p.streak_bonus > 0:
                    frags.append(
                        tts_phrases.phrase(
                            lang,
                            "streak_milestone",
                            name=p.name,
                            streak=tts_phrases.spoken_number(lang, p.streak),
                        )
                    )

        # Streak broken — previous_streak holds the pre-reset length. Gate
        # at >= 3 so a one-off miss after a short run doesn't trigger it.
        if self._tts_announce_streak_broken:
            for p in players:
                if p.streak == 0 and p.previous_streak >= 3:
                    frags.append(
                        tts_phrases.phrase(
                            lang,
                            "streak_broken",
                            name=p.name,
                            previous=tts_phrases.spoken_number(lang, p.previous_streak),
                        )
                    )

        # Bet outcomes — gated on submitted so a stale outcome can't misfire.
        for p in players:
            if not (p.submitted and p.bet):
                continue
            if p.bet_outcome == "won" and self._tts_announce_bet_won:
                frags.append(tts_phrases.phrase(lang, "bet_won", name=p.name))
            elif p.bet_outcome == "lost" and self._tts_announce_bet_lost:
                frags.append(tts_phrases.phrase(lang, "bet_lost", name=p.name))

        # Steal unlocks — once per player per game. The dedup set is updated
        # regardless of the toggle so a mid-game toggle-on can't replay it.
        for p in players:
            if p.steal_available and p.name not in self._tts_steal_unlocked_announced:
                self._tts_steal_unlocked_announced.add(p.name)
                if self._tts_announce_steal_unlocked:
                    frags.append(
                        tts_phrases.phrase(lang, "steal_unlocked", name=p.name)
                    )

        # Standings — leader change / tie at the top. _tts_previous_leader
        # is updated regardless of the toggles so detection stays correct.
        leaderboard = sorted(players, key=lambda p: p.score, reverse=True)
        if leaderboard and leaderboard[0].score > 0:
            top_score = leaderboard[0].score
            leaders = [p for p in leaderboard if p.score == top_score]
            if len(leaders) > 1:
                if self._tts_announce_tied_first:
                    frags.append(tts_phrases.phrase(lang, "tie_at_top"))
                self._tts_previous_leader = None
            else:
                new_leader = leaders[0].name
                if new_leader != self._tts_previous_leader:
                    # Suppress round 1 — the leader always "changes" from
                    # nobody on the first scored round.
                    if (
                        self._tts_previous_leader is not None
                        and self._tts_announce_leader_change
                    ):
                        frags.append(
                            tts_phrases.phrase(lang, "leader_change", name=new_leader)
                        )
                self._tts_previous_leader = new_leader

        if frags:
            await self._tts_announce(" ".join(frags))

    # ------------------------------------------------------------------
    # Issue #841 Phase 3 — Betting & Game State announcements
    # ------------------------------------------------------------------

    async def announce_player_join(self, player_name: str) -> None:
        """Announce a new player joining the game (use case 14)."""
        if not self._tts_service or not self._tts_announce_player_join:
            return
        message = tts_phrases.phrase(self._lang(), "player_join", name=player_name)
        await self._tts_announce(message)

    async def announce_player_reconnect(self, player_name: str) -> None:
        """Announce a player reconnecting (use case 15).

        Off by default — phones drop and re-establish the WebSocket
        constantly (screen lock, network handoff), so firing on every
        reconnect is noisy. Opt-in for hosts who want it.
        """
        if not self._tts_service or not self._tts_announce_player_reconnect:
            return
        message = tts_phrases.phrase(self._lang(), "player_reconnect", name=player_name)
        await self._tts_announce(message)

    async def announce_last_round(self) -> None:
        """Announce that the final round is starting (use case 17).

        Fires from start_round, chained after announce_round_start, only
        when the round just started is the last one.
        """
        if not self._tts_service or not self._tts_announce_last_round:
            return
        message = tts_phrases.phrase(self._lang(), "last_round")
        await self._tts_announce(message)

    async def announce_podium(self) -> None:
        """Announce the top-3 finishers at game end (use case 19).

        Fires from advance_to_end after announce_winner. Names the podium
        bottom-up — 3rd, 2nd, 1st — the way a host reads an awards list.
        With fewer than three scoring players the podium shrinks to match.
        """
        if not self._tts_service or not self._tts_announce_podium:
            return
        ranked = sorted(self.players.values(), key=lambda p: p.score, reverse=True)
        podium = [p for p in ranked if p.score > 0][:3]
        if not podium:
            return
        lang = self._lang()
        segments = [
            f"{tts_phrases.place_label(lang, i + 1)}: "
            f"{podium[i].name}{'!' if i == 0 else '.'}"
            for i in reversed(range(len(podium)))
        ]
        await self._tts_announce(" ".join(segments))

    async def announce_rematch(self) -> None:
        """Announce a rematch starting (use case 20)."""
        if not self._tts_service or not self._tts_announce_rematch:
            return
        message = tts_phrases.phrase(self._lang(), "rematch")
        await self._tts_announce(message)

    # ------------------------------------------------------------------
    # Issue #842 Phase 4 — Special Modes announcements
    # ------------------------------------------------------------------

    async def announce_intro_round(self) -> None:
        """Announce the start of an intro-mode round (use case 21)."""
        if not self._tts_service or not self._tts_announce_intro_round:
            return
        await self._tts_announce(tts_phrases.phrase(self._lang(), "intro_round"))

    async def announce_steal_used(self, stealer_name: str, target_name: str) -> None:
        """Announce a player using steal on another (use case 23)."""
        if not self._tts_service or not self._tts_announce_steal_used:
            return
        await self._tts_announce(
            tts_phrases.phrase(
                self._lang(), "steal_used", stealer=stealer_name, target=target_name
            )
        )
