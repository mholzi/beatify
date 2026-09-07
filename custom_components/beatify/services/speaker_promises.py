"""What a game still owes the speakers it has touched (#1516/#2143).

Split out of :class:`~.media_player.MediaPlayerService` for #2678, because two
different lifetimes shared that one object and nothing said so:

* **The speaker's** — ``_preflight_verified``. A service is built for one
  entity on one platform and thrown away the moment either changes, so "this
  speaker answered a ping" (#179) is exactly as long-lived as the service. It
  stays there.
* **The game's** — the host's pre-game volume (#1516) and pre-game queue
  (#2143). These outlive any single service: a mid-game speaker switch
  (#1516/#2143) discards the service, and ``UpdateLobbyView`` rebuilds it on a
  lobby update, but the promise to hand a speaker back what it had is owed
  until the game ends.

The mismatch was bridged by copying a plain ``dict`` from the outgoing service
into the incoming one (``snapshot_saved_states`` / ``inherited_states``), and
that copy silently lost one of the queue's three states — see
:meth:`SpeakerPromises.snapshot`. Everything with the game's lifetime now lives
in this one object, and this object is what travels.
"""

from __future__ import annotations

from typing import Any


class SpeakerPromises:
    """Every promise this game has made to a speaker, for one service.

    Deliberately a plain state holder. WHEN a promise is made or paid out is
    game lifecycle and stays with :class:`~.media_player.MediaPlayerService`
    (the same split #2636 drew for ``save_queue``); WHAT is owed, and how it
    survives a service rebuild, is here.

    ``volume`` — the speaker's level as it was BEFORE Beatify first changed it
    this game (#1516). ``None`` means nothing to restore.

    ``queue`` — what the speaker was playing before Beatify claimed it (#2143).
    Three shapes, deliberately distinct:

      ``None`` — not captured yet (or already restored)
      ``{}``   — captured, but the speaker was idle: nothing to hand back
      ``{…}``  — the track, its position, shuffle and repeat mode

    What CANNOT be captured is the queue BEHIND the current track: MA's
    ``get_queue`` reports ``items`` as a COUNT and exposes only
    ``current_item`` / ``next_item`` — measured against a live queue on
    2026-08-13. Restoring "the first entry with replace, the rest with add"
    (the original plan in #2143) is therefore not implementable.

    ``others`` — speakers this game already switched away from,
    ``{entity_id: {"volume": …, "queue": …}}``. Our OWN entity's entry is
    adopted into the two fields above instead of staying here, so a switch back
    to a speaker does not re-capture an already-Beatify-altered level as if it
    were the host's original.
    """

    def __init__(
        self,
        entity_id: str,
        inherited: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._entity_id = entity_id
        self.volume: float | None = None
        self.queue: dict[str, Any] | None = None
        self.others: dict[str, dict[str, Any]] = {
            eid: dict(snap) for eid, snap in (inherited or {}).items()
        }
        own = self.others.pop(entity_id, None)
        if own is not None:
            self.volume = own.get("volume")
            self.queue = own.get("queue")

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """The hand-over to whichever service replaces this one.

        ``queue`` is written whenever it has been CAPTURED — the empty capture
        included. ``{}`` means "asked the speaker, it was idle, nothing to hand
        back", and it is what stops the next round from capturing Beatify's own
        track and calling it the host's music (#2143).

        Writing it only ``if self.queue`` (#2678) dropped that flag at every
        service rebuild, because ``{}`` is falsy. An idle-at-start speaker then
        looked uncaptured to the new service, the next round captured Beatify's
        quiz track, and the game ended by parking that track on the host's
        speaker — the exact outcome the capture-once rule exists to prevent.
        """
        # A speaker whose promises have all been paid out leaves an empty
        # entry behind. Dropping it here keeps "is anything still owed?" — the
        # question ``end_game`` asks of ``_pending_speaker_states`` — an honest
        # truthiness test on the bag as a whole.
        states = {eid: dict(snap) for eid, snap in self.others.items() if snap}
        own: dict[str, Any] = {}
        if self.volume is not None:
            own["volume"] = self.volume
        if self.queue is not None:
            own["queue"] = dict(self.queue)
        if own:
            states[self._entity_id] = own
        return states

    def take_volume(self) -> float | None:
        """This speaker's volume promise, cleared as it is handed out.

        Cleared BEFORE the caller awaits anything, so a re-entrant restore
        cannot pay the same promise twice and the next game starts from a clean
        (uncaptured) slate.
        """
        level, self.volume = self.volume, None
        return level

    def take_owed_volumes(self) -> list[tuple[str, float]]:
        """Every OTHER speaker's volume promise, each cleared as it is taken.

        Each speaker is owed ITS own level, never this one's — restoring the
        old speaker's volume onto the new one would be a different bug.
        """
        owed: list[tuple[str, float]] = []
        for entity_id, snapshot in list(self.others.items()):
            level = snapshot.pop("volume", None)
            if level is not None:
                owed.append((entity_id, level))
        return owed

    def take_queue(self) -> dict[str, Any] | None:
        """This speaker's queue promise, cleared as it is handed out."""
        queue, self.queue = self.queue, None
        return queue

    def take_owed_queues(self) -> list[tuple[str, dict[str, Any] | None]]:
        """Every OTHER speaker's queue promise, each cleared as it is taken."""
        return [
            (entity_id, snapshot.pop("queue", None))
            for entity_id, snapshot in list(self.others.items())
        ]
