"""#2143: give the host their own queue back after a game.

Beatify plays every round with ``enqueue: "replace"`` (services/media_player.py).
That wipes whatever the host had queued in Music Assistant — in every round, for
every MA user, whether or not they use Crate Digger. Before this change nothing
was remembered, so a game left the speaker on Beatify's last track with the
host's own music gone.

What is testable here is deliberately narrow, because MA's ``get_queue`` is
narrow: it reports ``items`` as a COUNT and exposes only ``current_item`` /
``next_item``. The entries BEHIND the current track cannot be read and therefore
cannot be restored. Measured against a live queue on 2026-08-13; the original
plan in the issue ("first entry with replace, the rest with add") is not
implementable against this interface.

The second half of the file covers the speaker switch. ``UpdateLobbyView``
permits switching the speaker during PLAYING and REVEAL, and that path used to
null the MediaPlayerService outright — dropping both the queue snapshot and the
older ``_saved_volume`` promise from #1516. The volume half was already broken
before #2143 existed and nobody had noticed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from tests.conftest import make_game_state, make_songs

QUEUE_RESPONSE = {
    "media_player.esszimmer": {
        "queue_id": "RINCON_C43875ED053801400",
        "active": True,
        "name": "Esszimmer",
        "items": 4,
        "shuffle_enabled": True,
        "repeat_mode": "all",
        "current_index": 3,
        "elapsed_time": 9,
        "current_item": {
            "queue_item_id": "921e004eb99a47d198d1226cdbdb1263",
            "name": "Stealers Wheel - Stuck In The Middle With You",
            "duration": 205,
            "media_item": {
                "media_type": "track",
                "uri": "apple_music://track/1686851478",
                "name": "Stuck In The Middle With You",
            },
        },
        "next_item": None,
    }
}


def _hass(queue_response=QUEUE_RESPONSE, speaker_state="playing") -> MagicMock:
    hass = MagicMock()
    hass.services.async_call = AsyncMock(return_value=queue_response)
    state = MagicMock()
    state.state = speaker_state
    state.attributes = {"volume_level": 0.5}
    hass.states.get = MagicMock(return_value=state)
    return hass


def _service(hass, entity_id="media_player.esszimmer", **kwargs) -> MediaPlayerService:
    return MediaPlayerService(hass, entity_id, platform="music_assistant", **kwargs)


def _calls_to(hass, domain, service):
    return [
        c
        for c in hass.services.async_call.await_args_list
        if c.args[:2] == (domain, service)
    ]


class TestQueueSnapshot:
    @pytest.mark.asyncio
    async def test_captures_track_position_shuffle_and_repeat(self):
        svc = _service(_hass())

        await svc.save_queue()

        assert svc._saved_queue == {
            "uri": "apple_music://track/1686851478",
            "name": "Stuck In The Middle With You",
            "elapsed_time": 9.0,
            "shuffle": True,
            "repeat_mode": "all",
        }

    @pytest.mark.asyncio
    async def test_is_idempotent_so_round_two_does_not_capture_beatify(self):
        """The whole point: round two's "current track" is OUR track.

        Without the guard the game would faithfully hand the host back the
        song Beatify had just played to them.
        """
        hass = _hass()
        svc = _service(hass)

        await svc.save_queue()
        hass.services.async_call.return_value = {
            "media_player.esszimmer": {
                "elapsed_time": 30,
                "current_item": {
                    "media_item": {"uri": "spotify:track:beatify", "name": "Round 2"}
                },
            }
        }
        await svc.save_queue()

        assert svc._saved_queue["uri"] == "apple_music://track/1686851478"
        assert len(_calls_to(hass, "music_assistant", "get_queue")) == 1

    @pytest.mark.asyncio
    async def test_idle_speaker_captures_nothing_but_still_counts_as_captured(self):
        """`{}` not None — otherwise every round would re-ask the speaker."""
        hass = _hass({"media_player.esszimmer": {"current_item": None}})
        svc = _service(hass)

        await svc.save_queue()
        await svc.save_queue()

        assert svc._saved_queue == {}
        assert len(_calls_to(hass, "music_assistant", "get_queue")) == 1
        assert await svc.restore_queue() is False

    @pytest.mark.asyncio
    async def test_non_ma_platform_never_asks(self):
        """Only Music Assistant has get_queue. Sonos/Alexa must not be probed."""
        hass = _hass()
        svc = MediaPlayerService(hass, "media_player.sonos", platform="sonos")

        await svc.save_queue()

        assert svc._saved_queue is None
        assert hass.services.async_call.await_count == 0

    @pytest.mark.asyncio
    async def test_missing_response_is_swallowed_not_raised(self):
        """An older core ignores return_response and hands back None.

        Losing the snapshot is acceptable; failing the round is not — this runs
        on the play path.
        """
        hass = _hass(queue_response=None)
        svc = _service(hass)

        await svc.save_queue()

        assert svc._saved_queue == {}


class TestQueueRestore:
    @pytest.mark.asyncio
    async def test_plays_the_saved_track_seeks_to_position_and_pauses(self):
        hass = _hass()
        svc = _service(hass)
        await svc.save_queue()
        hass.services.async_call.reset_mock()

        assert await svc.restore_queue() is True

        play = _calls_to(hass, "music_assistant", "play_media")
        assert len(play) == 1
        assert play[0].args[2]["media_id"] == "apple_music://track/1686851478"
        assert play[0].args[2]["enqueue"] == "replace"

        seek = _calls_to(hass, "media_player", "media_seek")
        assert len(seek) == 1
        assert seek[0].args[2]["seek_position"] == 9.0

        # Paused, not playing: the host just ended the game. Starting their
        # music unasked would be its own surprise.
        assert len(_calls_to(hass, "media_player", "media_pause")) == 1
        assert _calls_to(hass, "media_player", "shuffle_set")[0].args[2]["shuffle"]
        assert _calls_to(hass, "media_player", "repeat_set")[0].args[2]["repeat"] == (
            "all"
        )

    @pytest.mark.asyncio
    async def test_restore_clears_so_a_second_call_is_a_no_op(self):
        hass = _hass()
        svc = _service(hass)
        await svc.save_queue()

        assert await svc.restore_queue() is True
        assert await svc.restore_queue() is False

    @pytest.mark.asyncio
    async def test_seek_is_skipped_when_the_track_never_confirms(self):
        """A seek against a track that has not loaded moves the wrong song.

        The position is the cheap half of the promise — the track still comes
        back, just from 0:00.
        """
        hass = _hass(speaker_state="idle")
        svc = _service(hass)
        await svc.save_queue()
        hass.services.async_call.reset_mock()

        # Wait cut to keep the suite fast — the production budget is 5s and
        # this test would otherwise spin through all of it.
        with (
            patch(
                "custom_components.beatify.services.media_player.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.beatify.services.media_player.MA_QUEUE_RESTORE_WAIT",
                0.05,
            ),
        ):
            assert await svc.restore_queue() is True

        assert _calls_to(hass, "music_assistant", "play_media")
        assert _calls_to(hass, "media_player", "media_seek") == []
        assert len(_calls_to(hass, "media_player", "media_pause")) == 1


class TestSnapshotSurvivesASpeakerSwitch:
    @pytest.mark.asyncio
    async def test_snapshot_carries_volume_and_queue(self):
        hass = _hass()
        svc = _service(hass)
        svc.save_volume()
        await svc.save_queue()

        snapshot = svc.snapshot_saved_states()

        assert snapshot["media_player.esszimmer"]["volume"] == 0.5
        assert snapshot["media_player.esszimmer"]["queue"]["elapsed_time"] == 9.0

    @pytest.mark.asyncio
    async def test_the_old_speaker_is_restored_at_ITS_level_not_the_new_one(self):
        """The bug this guards against is subtle.

        Carrying the snapshot forward is right; APPLYING it to the new speaker
        would be a fresh bug — the host's living-room level landing on the
        kitchen speaker.
        """
        hass = _hass()
        new_svc = _service(
            hass,
            entity_id="media_player.kueche",
            inherited_states={"media_player.esszimmer": {"volume": 0.2}},
        )
        new_svc.save_volume()  # captures the NEW speaker at 0.5

        assert await new_svc.restore_volume() is True

        by_entity = {
            c.args[2]["entity_id"]: c.args[2]["volume_level"]
            for c in _calls_to(hass, "media_player", "volume_set")
        }
        assert by_entity == {
            "media_player.esszimmer": 0.2,
            "media_player.kueche": 0.5,
        }

    @pytest.mark.asyncio
    async def test_switching_back_does_not_recapture_an_altered_level(self):
        """A→B→A must not "remember" the volume Beatify itself had set.

        The service adopts its own entity's inherited snapshot instead of
        keeping it in the inherited bag, so save_volume's idempotency guard
        sees an already-captured value and stands down.
        """
        hass = _hass()
        svc = _service(
            hass, inherited_states={"media_player.esszimmer": {"volume": 0.2}}
        )

        svc.save_volume()  # would capture the current 0.5 if the adopt failed

        assert svc._saved_volume == 0.2
        assert svc._inherited_states == {}

    @pytest.mark.asyncio
    async def test_the_old_speaker_gets_its_queue_back_too(self):
        hass = _hass()
        svc = _service(
            hass,
            entity_id="media_player.kueche",
            inherited_states={
                "media_player.esszimmer": {
                    "queue": {"uri": "apple_music://track/1", "elapsed_time": 0}
                }
            },
        )

        assert await svc.restore_queue() is True

        play = _calls_to(hass, "music_assistant", "play_media")
        assert len(play) == 1
        assert play[0].kwargs["target"]["entity_id"] == "media_player.esszimmer"


class TestGameStateKeepsThePromiseAcrossTheSwitch:
    def test_release_parks_the_snapshot_on_the_game(self):
        """`release_media_player_service` is the whole difference to `= None`."""
        gs = make_game_state()
        service = MagicMock()
        service.snapshot_saved_states.return_value = {
            "media_player.esszimmer": {"volume": 0.2}
        }
        gs._media_player_service = service

        gs.release_media_player_service()

        assert gs._media_player_service is None
        assert gs._pending_speaker_states == {"media_player.esszimmer": {"volume": 0.2}}

    def test_the_new_service_inherits_what_the_old_one_owed(self):
        gs = make_game_state()
        gs.media_player = "media_player.kueche"
        gs.platform = "music_assistant"
        gs._pending_speaker_states = {"media_player.esszimmer": {"volume": 0.2}}

        gs._ensure_media_player_service()

        assert gs._media_player_service._inherited_states == {
            "media_player.esszimmer": {"volume": 0.2}
        }
        # Handed over, not shared — a later release/build cycle must not
        # restore the same speaker twice.
        assert gs._pending_speaker_states == {}

    def test_a_new_game_starts_owing_nothing(self):
        """A promise made in a previous game must not be paid out in this one."""
        gs = make_game_state()
        gs._pending_speaker_states = {"media_player.esszimmer": {"volume": 0.2}}

        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.kueche",
            base_url="http://x",
        )

        assert gs._pending_speaker_states == {}


class TestPlayPathTakesTheSnapshotFirst:
    @pytest.mark.asyncio
    async def test_get_queue_is_asked_before_the_replace_wipes_it(self):
        """Ordering is the whole fix — after the replace there is nothing left."""
        hass = _hass()
        svc = _service(hass)

        # Both budgets cut: this test is about call ORDER, not about waiting
        # out the real playback confirmation window.
        with (
            patch(
                "custom_components.beatify.services.media_player.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.beatify.services.media_player.MA_PLAYBACK_TIMEOUT",
                0.05,
            ),
        ):
            await svc._try_ma_play("spotify:track:abc", "New Song")

        services = [c.args[:2] for c in hass.services.async_call.await_args_list]
        assert services.index(("music_assistant", "get_queue")) < services.index(
            ("music_assistant", "play_media")
        )
