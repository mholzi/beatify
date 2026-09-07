"""#2678: two lifetimes used to share one object, and the shorter one won.

``MediaPlayerService`` holds state with two different lifetimes:

* ``_preflight_verified`` (#179) belongs to THE SPEAKER. The service is rebuilt
  whenever the entity or platform changes, so the flag dying with it is right —
  a new speaker has to answer its own ping.
* the pre-game volume (#1516) and pre-game queue (#2143) belong to THE GAME.
  They have to survive every rebuild, because the promise to hand a speaker
  back what it had is owed until the game ends.

The bridge between the two is ``snapshot_saved_states`` → ``inherited_states``,
and it used to write the queue only ``if self._saved_queue``. ``{}`` — "asked
the speaker, it was idle, nothing to hand back", the flag that stops the next
round capturing Beatify's own track — is falsy, so every rebuild forgot it.

These tests drive the sequence that made that visible, and pin the boundary
that now separates the two lifetimes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback import queue_restore
from custom_components.beatify.services.speaker_promises import SpeakerPromises

ESSZIMMER = "media_player.esszimmer"
KUECHE = "media_player.kueche"

#: The host's speaker was idle when the game started: MA answers get_queue,
#: but there is no current item.
IDLE_QUEUE = {ESSZIMMER: {"current_item": None}}

#: Round seven. The only thing on the speaker now is Beatify's own quiz track.
BEATIFY_QUEUE = {
    ESSZIMMER: {
        "elapsed_time": 30,
        "current_item": {
            "media_item": {"uri": "spotify:track:beatify_round_7", "name": "Round 7"}
        },
    }
}

HOSTS_OWN_QUEUE = {
    ESSZIMMER: {
        "elapsed_time": 9,
        "shuffle_enabled": True,
        "repeat_mode": "all",
        "current_item": {
            "media_item": {
                "uri": "apple_music://track/1686851478",
                "name": "Stuck In The Middle With You",
            }
        },
    }
}


@pytest.fixture(autouse=True)
def _fast_pause_guard(monkeypatch):
    """The #2605 pause guard on a compressed clock — durations only."""
    monkeypatch.setattr(queue_restore, "MA_PAUSE_CONFIRM_WAIT", 0.05)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_SETTLE_HOLD", 0.05)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_GUARD_WINDOW", 0.30)
    monkeypatch.setattr(queue_restore, "MA_LATE_START_WATCH", 0.30)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_POLL", 0.01)


def _hass(queue_response) -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock(return_value=queue_response)
    state = MagicMock()
    state.state = "playing"
    state.attributes = {"volume_level": 0.5}
    hass.states.get = MagicMock(return_value=state)
    return hass


def _service(hass, entity_id=ESSZIMMER, **kwargs) -> MediaPlayerService:
    return MediaPlayerService(hass, entity_id, platform="music_assistant", **kwargs)


def _calls_to(hass, domain, service):
    return [
        c
        for c in hass.services.async_call.await_args_list
        if c.args[:2] == (domain, service)
    ]


class TestTheGamesPromisesSurviveTheServiceRebuild:
    """The game-lifetime half must cross every hand-over intact."""

    def test_an_empty_capture_is_still_a_capture_on_the_other_side(self):
        """`{}` is the flag, not the absence of one — it has to travel.

        This is the whole defect in one assertion: the snapshot wrote the queue
        only when it was truthy, so the idle capture never reached the service
        that replaced this one.
        """
        first = _service(_hass(IDLE_QUEUE))
        first._promises.queue = {}

        second = _service(
            _hass(IDLE_QUEUE), inherited_states=first.snapshot_saved_states()
        )

        assert second._promises.queue == {}

    @pytest.mark.asyncio
    async def test_a_rebuild_does_not_let_round_two_capture_beatifys_own_track(self):
        """The sequence, end to end, on one speaker.

        1. The game starts on an MA speaker that is idle. Round one asks
           get_queue and records the empty capture.
        2. Anything that rebuilds the service happens — a speaker switch, or
           the lobby update the admin UI fires on every settings save.
        3. Round N asks get_queue again, because the new service believes
           nothing has been captured. The speaker is now on Beatify's own quiz
           track, so THAT is recorded as "the host's music".
        4. The game ends and parks Beatify's round-seven track on the host's
           speaker — the exact outcome the capture-once rule exists to prevent.
        """
        first_hass = _hass(IDLE_QUEUE)
        first = _service(first_hass)
        await first.save_queue()
        assert first._promises.queue == {}

        second_hass = _hass(BEATIFY_QUEUE)
        second = _service(second_hass, inherited_states=first.snapshot_saved_states())
        await second.save_queue()

        assert second._promises.queue == {}
        assert _calls_to(second_hass, "music_assistant", "get_queue") == []
        assert await second.restore_queue() is False
        assert _calls_to(second_hass, "music_assistant", "play_media") == []

    @pytest.mark.asyncio
    async def test_the_same_holds_when_the_game_switches_away_and_back(self):
        """A → B → A. The empty capture rides along in the inherited bag."""
        on_a = _service(_hass(IDLE_QUEUE))
        await on_a.save_queue()

        on_b = _service(
            _hass(IDLE_QUEUE),
            entity_id=KUECHE,
            inherited_states=on_a.snapshot_saved_states(),
        )
        assert on_b._promises.others == {ESSZIMMER: {"queue": {}}}

        back_hass = _hass(BEATIFY_QUEUE)
        back_on_a = _service(back_hass, inherited_states=on_b.snapshot_saved_states())

        assert back_on_a._promises.queue == {}
        await back_on_a.save_queue()
        assert back_on_a._promises.queue == {}
        assert await back_on_a.restore_queue() is False

    @pytest.mark.asyncio
    async def test_a_real_track_still_travels_and_still_comes_back(self):
        """The fix must not turn every capture into "nothing owed"."""
        first = _service(_hass(HOSTS_OWN_QUEUE))
        first.save_volume()
        await first.save_queue()

        second_hass = _hass(HOSTS_OWN_QUEUE)
        second = _service(second_hass, inherited_states=first.snapshot_saved_states())

        assert second._promises.volume == 0.5
        assert second._promises.queue["uri"] == "apple_music://track/1686851478"
        assert await second.restore_queue() is True
        play = _calls_to(second_hass, "music_assistant", "play_media")
        assert len(play) == 1
        assert play[0].args[2]["media_id"] == "apple_music://track/1686851478"


class TestTheSpeakersOwnStateDoesNotTravel:
    """The other half of the split: what belongs to the speaker stays put."""

    def test_the_new_service_re_verifies_the_speaker(self):
        """#179's cache is the SERVICE's, and a rebuild means a new speaker
        may be behind the same game. It must not ride in on the promises."""
        first = _service(_hass(HOSTS_OWN_QUEUE))
        first._preflight_verified = True
        first.save_volume()

        second = _service(
            _hass(HOSTS_OWN_QUEUE),
            entity_id=KUECHE,
            inherited_states=first.snapshot_saved_states(),
        )

        assert second._preflight_verified is False
        # ...while the game's promise to the old speaker did cross.
        assert second._promises.others == {ESSZIMMER: {"volume": 0.5}}

    def test_the_hand_over_carries_nothing_but_the_promises(self):
        """A snapshot is game state only — no speaker, platform or ping flag."""
        svc = _service(_hass(HOSTS_OWN_QUEUE))
        svc._preflight_verified = True
        svc.save_volume()

        snapshot = svc.snapshot_saved_states()

        assert snapshot == {ESSZIMMER: {"volume": 0.5}}


class TestSpeakerPromises:
    """The boundary itself, without a speaker in the way."""

    def test_an_uncaptured_queue_is_absent_a_captured_empty_one_is_present(self):
        uncaptured = SpeakerPromises(ESSZIMMER)
        assert uncaptured.snapshot() == {}

        captured = SpeakerPromises(ESSZIMMER)
        captured.queue = {}
        assert captured.snapshot() == {ESSZIMMER: {"queue": {}}}

    def test_it_adopts_its_own_entitys_entry_and_leaves_the_rest(self):
        promises = SpeakerPromises(
            ESSZIMMER,
            {ESSZIMMER: {"volume": 0.2, "queue": {}}, KUECHE: {"volume": 0.4}},
        )

        assert promises.volume == 0.2
        assert promises.queue == {}
        assert promises.others == {KUECHE: {"volume": 0.4}}

    def test_taking_a_promise_clears_it(self):
        promises = SpeakerPromises(ESSZIMMER, {KUECHE: {"volume": 0.4, "queue": {}}})
        promises.volume = 0.2
        promises.queue = {"uri": "spotify:track:x"}

        assert promises.take_owed_volumes() == [(KUECHE, 0.4)]
        assert promises.take_volume() == 0.2
        assert promises.take_owed_queues() == [(KUECHE, {})]
        assert promises.take_queue() == {"uri": "spotify:track:x"}

        assert promises.snapshot() == {}
        assert promises.take_owed_volumes() == []
        assert promises.take_volume() is None

    def test_a_snapshot_is_a_copy_not_a_view(self):
        """The outgoing service is discarded, but nothing may share its dicts."""
        promises = SpeakerPromises(ESSZIMMER, {KUECHE: {"volume": 0.4}})
        promises.queue = {"uri": "spotify:track:x"}

        snapshot = promises.snapshot()
        snapshot[ESSZIMMER]["queue"]["uri"] = "spotify:track:tampered"
        snapshot[KUECHE]["volume"] = 0.9

        assert promises.queue == {"uri": "spotify:track:x"}
        assert promises.others == {KUECHE: {"volume": 0.4}}
