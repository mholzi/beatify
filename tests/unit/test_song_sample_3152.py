"""#3152 — the host sets how long the song plays, separately from the answer time.

One ``round_duration`` used to be both the answer deadline and the length of
the music. ``sample_duration`` splits the two: the song is stopped after that
many seconds while the round timer keeps running, and the state tells the
clients so (``sample_stopped``). 0 means "the whole round", which is what every
game did before.

Covered here: the validation at create and in the lobby, the stop on a normal
round, intro rounds (untouched without a sample, the shorter length wins with
one), both sides of pause/resume, the reveal getting its song back, and the
state fields.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import (
    DOMAIN,
    HOST_PAUSE_REASON,
    INTRO_DURATION_SECONDS,
    SAMPLE_DURATION_OPTIONS,
)
from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.round_manager import RoundManager
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.game_views import UpdateLobbyView
from custom_components.beatify.server.serializers import (
    _PLAYER_VISIBLE_BASE,
)
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state, make_start_game_request

T0 = 1_000_000.0
ROUND = 30.0
SAMPLE = 15


class _Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _playing_round(
    clock: _Clock, *, sample: int = SAMPLE, round_duration: float = ROUND
) -> GameState:
    """A game one round in: PLAYING, started at ``T0``, speaker mocked."""
    state = make_game_state(time_fn=clock)
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.add_player("Host", MagicMock())
    state.set_admin("Host")
    state.add_player("Guest", MagicMock())
    state.phase = GamePhase.PLAYING
    state.current_song = {"year": 1984, "title": "Big in Japan", "artist": "Alphaville"}
    state.round_duration = round_duration
    state.sample_duration = sample
    state.round_start_time = T0
    state.deadline = int(T0 * 1000) + int(round_duration * 1000)
    speaker = MagicMock()
    speaker.stop = AsyncMock()
    speaker.play = AsyncMock()
    state._media_player_service = speaker
    state._on_round_end = AsyncMock()
    return state


async def _settle() -> None:
    """Let a task armed with a zero delay run to completion."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _let_the_sample_run_out(state: GameState, clock: _Clock) -> None:
    """Move the clock to the end of the sample and let the stop fire."""
    left = state._round_manager.sample_remaining_seconds()
    assert left is not None
    clock.t += max(0.0, left)
    state._arm_sample_stop()
    await _settle()


async def _cleanup(state: GameState) -> None:
    state.cancel_timer()
    state._round_manager._cancel_intro_timer()
    state._round_manager._cancel_sample_timer()
    state._cancel_auto_advance()
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Validation — create
# ---------------------------------------------------------------------------


class TestStartGameValidation:
    @pytest.mark.parametrize("seconds", SAMPLE_DURATION_OPTIONS)
    async def test_every_offered_step_is_accepted(self, start_game_env, seconds):
        view, hass, body = start_game_env
        body["round_duration"] = 45
        body["sample_duration"] = seconds

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 200
        assert hass.data[DOMAIN]["game"].sample_duration == seconds

    @pytest.mark.parametrize("value", ["absent", None, 0])
    async def test_absent_null_and_zero_are_the_whole_round(
        self, start_game_env, value
    ):
        view, hass, body = start_game_env
        if value != "absent":
            body["sample_duration"] = value

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 200
        assert hass.data[DOMAIN]["game"].sample_duration == 0

    @pytest.mark.parametrize("value", [5, 12, 25, 45, -10, "abc", True, 15.5, [15]])
    async def test_a_value_that_is_not_an_offered_step_is_rejected(
        self, start_game_env, value
    ):
        view, hass, body = start_game_env
        body["round_duration"] = 60
        body["sample_duration"] = value

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 400
        payload = json.loads(resp.body)
        assert payload["code"] == "INVALID_REQUEST"
        assert payload["message_key"] == "SAMPLE_DURATION_INVALID"
        assert hass.data[DOMAIN]["game"].game_id is None

    @pytest.mark.parametrize(
        ("round_duration", "sample"),
        [(15, 15), (15, 20), (15, 30), (30, 30)],
    )
    async def test_a_sample_not_shorter_than_the_round_is_rejected(
        self, start_game_env, round_duration, sample
    ):
        view, hass, body = start_game_env
        body["round_duration"] = round_duration
        body["sample_duration"] = sample

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 400
        payload = json.loads(resp.body)
        assert payload["message_key"] == "SAMPLE_DURATION_TOO_LONG"
        # _json_error merges the details into the body for the i18n params.
        assert (payload["sample"], payload["round"]) == (sample, round_duration)
        assert hass.data[DOMAIN]["game"].game_id is None

    async def test_the_default_round_duration_is_what_it_is_measured_against(
        self, start_game_env
    ):
        """No round_duration in the body: the round is 45 s, so 30 s is fine."""
        view, hass, body = start_game_env
        body.pop("round_duration", None)
        body["sample_duration"] = 30

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 200
        assert hass.data[DOMAIN]["game"].sample_duration == 30

    @pytest.mark.parametrize(
        "options",
        [
            GameOptions(round_duration=30, sample_duration=30),
            GameOptions(round_duration=45, sample_duration=12),
        ],
    )
    def test_create_game_is_the_backstop(self, options):
        state = make_game_state()
        with pytest.raises(ValueError, match="sample"):
            state.create_game(
                playlists=["test.json"],
                songs=make_songs(5),
                media_player="media_player.test",
                base_url="http://localhost:8123",
                options=options,
            )
        assert state.game_id is None

    def test_both_error_texts_exist_in_all_six_locales(self):
        from pathlib import Path

        i18n = Path("custom_components/beatify/www/i18n")
        for lang in ("en", "de", "es", "fr", "it", "nl"):
            host = json.loads((i18n / f"{lang}.json").read_text())["errors"]["host"]
            assert host["SAMPLE_DURATION_INVALID"], lang
            assert "{options}" in host["SAMPLE_DURATION_INVALID"], lang
            assert host["SAMPLE_DURATION_TOO_LONG"], lang


# ---------------------------------------------------------------------------
# Validation — lobby update
# ---------------------------------------------------------------------------


def _lobby(**options: Any) -> GameState:
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(12),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(**options),
    )
    assert state.phase is GamePhase.LOBBY
    return state


async def _post_lobby(state: GameState, game_options: dict[str, Any]):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": None}}
    request = MagicMock()
    request.json = AsyncMock(return_value={"game_options": game_options})
    with patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    ):
        response = await UpdateLobbyView(hass).post(request)
    return response.status, json.loads(response.body)


class TestLobbyUpdate:
    async def test_the_lobby_takes_a_sample_length(self):
        state = _lobby(round_duration=30)

        status, body = await _post_lobby(state, {"sample_duration": 15})

        assert status == 200
        assert state.sample_duration == 15
        assert "sample_duration" in body["fields"]

    async def test_round_and_sample_can_change_together(self):
        state = _lobby(round_duration=15)

        status, _ = await _post_lobby(
            state, {"round_duration": 45, "sample_duration": 30}
        )

        assert status == 200
        assert (state.round_duration, state.sample_duration) == (45, 30)

    @pytest.mark.parametrize("value", [0, None])
    async def test_back_to_the_whole_round(self, value):
        state = _lobby(round_duration=45, sample_duration=20)

        status, _ = await _post_lobby(state, {"sample_duration": value})

        assert status == 200
        assert state.sample_duration == 0

    async def test_an_unoffered_step_is_rejected_and_changes_nothing(self):
        state = _lobby(round_duration=45, sample_duration=20)

        status, body = await _post_lobby(state, {"sample_duration": 12})

        assert status == 400
        assert body["message_key"] == "SAMPLE_DURATION_INVALID"
        assert state.sample_duration == 20

    async def test_a_sample_not_shorter_than_the_round_is_rejected(self):
        state = _lobby(round_duration=30)

        status, body = await _post_lobby(state, {"sample_duration": 30})

        assert status == 400
        assert body["message_key"] == "SAMPLE_DURATION_TOO_LONG"
        assert state.sample_duration == 0

    async def test_shortening_the_round_under_the_sample_is_rejected(self):
        state = _lobby(round_duration=45, sample_duration=20)

        status, body = await _post_lobby(state, {"round_duration": 15})

        assert status == 400
        assert body["message_key"] == "SAMPLE_DURATION_TOO_LONG"
        assert (state.round_duration, state.sample_duration) == (45, 20)

    async def test_the_rematch_keeps_the_sample_length(self):
        state = _lobby(round_duration=30, sample_duration=10)
        captured = GameOptions.capture(state)
        assert captured.sample_duration == 10


# ---------------------------------------------------------------------------
# How long the song plays
# ---------------------------------------------------------------------------


class TestSampleLength:
    def _rm(self, *, round_duration: float, sample: int, intro: bool = False):
        rm = RoundManager(_Clock())
        rm.round_duration = round_duration
        rm.sample_duration = sample
        rm.is_intro_round = intro
        return rm

    def test_no_sample_means_the_whole_round(self):
        assert self._rm(round_duration=45, sample=0).sample_playback_seconds() is None

    def test_a_sample_shorter_than_the_round(self):
        assert self._rm(round_duration=45, sample=20).sample_playback_seconds() == 20

    def test_a_sample_as_long_as_the_round_is_no_sample(self):
        assert self._rm(round_duration=30, sample=30).sample_playback_seconds() is None

    def test_an_intro_round_without_a_sample_plays_the_intro_length(self):
        rm = self._rm(round_duration=45, sample=0, intro=True)
        assert rm.sample_playback_seconds() == INTRO_DURATION_SECONDS

    def test_an_intro_round_not_longer_than_the_intro_plays_whole(self):
        rm = self._rm(round_duration=INTRO_DURATION_SECONDS, sample=0, intro=True)
        assert rm.sample_playback_seconds() is None

    @pytest.mark.parametrize(
        ("sample", "expected"),
        [
            (10, 10),
            (15, 15),
            (20, INTRO_DURATION_SECONDS),
            (30, INTRO_DURATION_SECONDS),
        ],
    )
    def test_on_an_intro_round_the_shorter_length_wins(self, sample, expected):
        rm = self._rm(round_duration=45, sample=sample, intro=True)
        assert rm.sample_playback_seconds() == expected

    def test_the_sample_is_measured_on_the_round_clock(self):
        clock = _Clock()
        rm = RoundManager(clock)
        rm.round_duration = 30
        rm.sample_duration = 10
        rm.deadline = int(T0 * 1000) + 30_000
        assert rm.sample_remaining_seconds() == pytest.approx(10.0)
        clock.t = T0 + 4
        assert rm.sample_remaining_seconds() == pytest.approx(6.0)
        clock.t = T0 + 12
        assert rm.sample_remaining_seconds() == pytest.approx(-2.0)

    async def test_announcements_move_the_sample_with_the_round(self):
        """The re-stamp once the song is audible carries the sample along."""
        clock = _Clock()
        state = _playing_round(clock)
        rm = state._round_manager
        rm.defer_deadline()
        clock.t = T0 + 7  # round number + countdown spoken

        async def _countdown(_delay: float) -> None:
            await asyncio.sleep(3600)

        rm.start_timer_at_playback(_countdown, extra_seconds=2.0)
        state._arm_sample_stop()

        assert rm.sample_remaining_seconds() == pytest.approx(SAMPLE + 2.0)
        assert rm._sample_stop_task is not None
        await _cleanup(state)


# ---------------------------------------------------------------------------
# Normal round
# ---------------------------------------------------------------------------


class TestNormalRound:
    async def test_the_round_start_arms_the_stop(self):
        clock = _Clock()
        state = _playing_round(clock)
        state.phase = GamePhase.LOBBY
        state.round_duration = ROUND

        state._initialize_round(
            {"uri": "spotify:track:x", "year": 1999, "title": "t", "artist": "a"},
            {},
            "spotify:track:x",
            False,
        )

        rm = state._round_manager
        assert state.phase == GamePhase.PLAYING
        assert rm._sample_stop_task is not None and not rm._sample_stop_task.done()
        assert rm.sample_remaining_seconds() == pytest.approx(SAMPLE)
        assert state.sample_stopped is False
        await _cleanup(state)

    async def test_the_song_stops_and_the_round_goes_on(self):
        clock = _Clock()
        state = _playing_round(clock)
        deadline = state.deadline
        state._arm_sample_stop()

        clock.t = T0 + SAMPLE - 1
        await _settle()
        state._media_player_service.stop.assert_not_awaited()
        assert state.sample_stopped is False

        await _let_the_sample_run_out(state, clock)

        state._media_player_service.stop.assert_awaited_once_with()
        assert state.sample_stopped is True
        assert state.phase == GamePhase.PLAYING
        assert state.deadline == deadline
        assert state.is_deadline_passed() is False
        assert (state.deadline - int(clock() * 1000)) / 1000 == pytest.approx(
            ROUND - SAMPLE
        )
        # The clients are told: this is the frame that flips the chip.
        state._on_round_end.assert_awaited_once()
        # Not the host's stop: that one keeps the reveal silent.
        assert state.song_stopped is False
        await _cleanup(state)

    async def test_a_game_without_a_sample_never_stops_the_song(self):
        clock = _Clock()
        state = _playing_round(clock, sample=0)

        state._arm_sample_stop()
        clock.t = T0 + ROUND - 1
        await _settle()

        assert state._round_manager._sample_stop_task is None
        state._media_player_service.stop.assert_not_awaited()
        assert state.sample_stopped is False
        await _cleanup(state)

    async def test_a_failing_speaker_still_tells_the_clients(self):
        clock = _Clock()
        state = _playing_round(clock)
        state._media_player_service.stop = AsyncMock(side_effect=RuntimeError("boom"))

        await _let_the_sample_run_out(state, clock)

        assert state.sample_stopped is True
        state._on_round_end.assert_awaited_once()
        await _cleanup(state)

    async def test_the_next_round_starts_with_its_song(self):
        clock = _Clock()
        state = _playing_round(clock)
        await _let_the_sample_run_out(state, clock)
        assert state.sample_stopped is True

        state._initialize_round(
            {"uri": "spotify:track:y", "year": 2001, "title": "t", "artist": "a"},
            {},
            "spotify:track:y",
            False,
        )

        assert state.sample_stopped is False
        assert state._round_manager.sample_remaining_seconds() == pytest.approx(SAMPLE)
        await _cleanup(state)

    async def test_a_voided_round_does_not_fire_the_stop_later(self):
        clock = _Clock()
        state = _playing_round(clock)
        state._arm_sample_stop()
        task = state._round_manager._sample_stop_task

        assert await state.void_round("silence")
        await _settle()

        assert task.cancelled()
        assert state._round_manager._sample_stop_task is None
        await _cleanup(state)


# ---------------------------------------------------------------------------
# Reveal
# ---------------------------------------------------------------------------


class TestReveal:
    async def test_the_reveal_gets_its_song_back(self):
        clock = _Clock()
        state = _playing_round(clock)
        await _let_the_sample_run_out(state, clock)
        state._media_player_service.play.assert_not_awaited()

        clock.t = T0 + ROUND
        await state.end_round()

        assert state.phase == GamePhase.REVEAL
        state._media_player_service.play.assert_awaited_once_with()
        assert state._round_manager._sample_stop_task is None
        await _cleanup(state)

    async def test_an_early_reveal_before_the_stop_touches_nothing(self):
        clock = _Clock()
        state = _playing_round(clock)
        state._arm_sample_stop()
        task = state._round_manager._sample_stop_task

        clock.t = T0 + 5
        await state.end_round()
        await _settle()

        assert state.phase == GamePhase.REVEAL
        assert task.cancelled()
        state._media_player_service.stop.assert_not_awaited()
        state._media_player_service.play.assert_not_awaited()
        assert state.sample_stopped is False
        await _cleanup(state)

    async def test_a_song_the_host_stopped_stays_stopped(self):
        clock = _Clock()
        state = _playing_round(clock)
        await _let_the_sample_run_out(state, clock)
        state.song_stopped = True  # the host tapped "stop song" afterwards

        await state.end_round()

        assert state.phase == GamePhase.REVEAL
        state._media_player_service.play.assert_not_awaited()
        await _cleanup(state)

    async def test_a_round_without_a_sample_is_not_resumed(self):
        clock = _Clock()
        state = _playing_round(clock, sample=0)

        await state.end_round()

        state._media_player_service.play.assert_not_awaited()
        await _cleanup(state)


# ---------------------------------------------------------------------------
# Intro rounds
# ---------------------------------------------------------------------------


class TestIntroRounds:
    async def test_without_a_sample_the_intro_song_is_cut_after_the_intro(self):
        """#3199: flag and broadcast after 15 s, and the song stops with them."""
        clock = _Clock()
        state = _playing_round(clock, sample=0, round_duration=45)
        state.is_intro_round = True
        rm = state._round_manager

        state._arm_sample_stop()
        assert rm.sample_remaining_seconds() == pytest.approx(
            float(INTRO_DURATION_SECONDS)
        )
        assert rm._sample_stop_task is not None
        await _let_the_sample_run_out(state, clock)
        state._media_player_service.stop.assert_awaited_once_with()
        assert state.sample_stopped is True

        await rm._intro_auto_stop(0, state._on_round_end)
        assert state.intro_stopped is True
        await _cleanup(state)

    @pytest.mark.parametrize(
        ("sample", "audible"),
        [
            (10, 10.0),
            (20, float(INTRO_DURATION_SECONDS)),
            (30, float(INTRO_DURATION_SECONDS)),
        ],
    )
    async def test_with_a_sample_the_shorter_length_wins(self, sample, audible):
        clock = _Clock()
        state = _playing_round(clock, sample=sample, round_duration=45)
        state.is_intro_round = True
        rm = state._round_manager
        rm._intro_round_start_time = T0

        state._arm_sample_stop()

        assert rm.sample_remaining_seconds() == pytest.approx(audible)
        await _let_the_sample_run_out(state, clock)
        state._media_player_service.stop.assert_awaited_once_with()
        # The intro's own clock, flag and bonus cutoff are not touched.
        assert state.intro_stopped is False
        assert rm._intro_round_start_time == T0
        await _cleanup(state)

    async def test_a_splash_round_counts_from_the_confirmation(self):
        clock = _Clock()
        state = _playing_round(clock, sample=10, round_duration=45)
        rm = state._round_manager
        state.phase = GamePhase.LOBBY
        rm.is_intro_round = True
        rm._intro_splash_pending = True
        rm._intro_splash_deferred_song = {"uri": "spotify:track:x"}
        state.play_deferred_song = AsyncMock(return_value=True)

        state._initialize_round(
            {"uri": "spotify:track:x", "year": 1999, "title": "t", "artist": "a"},
            {},
            "spotify:track:x",
            True,
        )
        # Waiting for the host: no song yet, so nothing to stop.
        assert rm._sample_stop_task is None

        clock.t = T0 + 40  # the host takes their time
        await state.confirm_intro_splash()

        assert rm._sample_stop_task is not None
        assert rm.sample_remaining_seconds() == pytest.approx(10.0)
        assert state.sample_stopped is False
        await _cleanup(state)


# ---------------------------------------------------------------------------
# Pause / resume
# ---------------------------------------------------------------------------


class TestPauseResume:
    async def test_paused_before_the_stop_the_rest_of_the_sample_plays(self):
        clock = _Clock()
        state = _playing_round(clock)
        state.end_round = AsyncMock()
        state._arm_sample_stop()
        armed = state._round_manager._sample_stop_task

        clock.t = T0 + 5
        assert await state.pause_game(HOST_PAUSE_REASON)
        await _settle()
        assert armed.cancelled()
        assert state._round_manager._sample_stop_task is None
        state._media_player_service.stop.assert_awaited_once_with()  # the pause

        clock.t = T0 + 65  # a minute's break does not eat the sample
        assert await state.resume_game()

        rm = state._round_manager
        assert state.phase == GamePhase.PLAYING
        state._media_player_service.play.assert_awaited_once_with()
        assert state.sample_stopped is False
        assert rm._sample_stop_task is not None and not rm._sample_stop_task.done()
        assert rm.sample_remaining_seconds() == pytest.approx(SAMPLE - 5)

        # ... and it still ends when those ten seconds are up.
        await _let_the_sample_run_out(state, clock)
        assert state.sample_stopped is True
        assert state._media_player_service.stop.await_count == 2
        await _cleanup(state)

    async def test_paused_after_the_stop_the_resume_stays_silent(self):
        clock = _Clock()
        state = _playing_round(clock)
        state.end_round = AsyncMock()
        await _let_the_sample_run_out(state, clock)
        assert state.sample_stopped is True

        clock.t = T0 + 20
        assert await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 80
        assert await state.resume_game()

        rm = state._round_manager
        assert state.phase == GamePhase.PLAYING
        state._media_player_service.play.assert_not_awaited()
        assert state.sample_stopped is True
        assert rm._sample_stop_task is None
        # The answer time is all there: 10 s were left, 10 s are left.
        assert (state.deadline - int(clock() * 1000)) / 1000 == pytest.approx(10.0)
        assert rm._timer_task is not None
        state.end_round.assert_not_awaited()
        await _cleanup(state)

    async def test_paused_in_the_instant_the_sample_ends(self):
        """The stop task was cancelled by the pause before it could fire."""
        clock = _Clock()
        state = _playing_round(clock)
        state.end_round = AsyncMock()
        state._arm_sample_stop()

        clock.t = T0 + SAMPLE  # due, but the pause gets there first
        assert await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 100
        assert await state.resume_game()

        state._media_player_service.play.assert_not_awaited()
        assert state.sample_stopped is True
        assert state._round_manager._sample_stop_task is None
        await _cleanup(state)

    async def test_a_game_without_a_sample_resumes_as_before(self):
        clock = _Clock()
        state = _playing_round(clock, sample=0)
        state.end_round = AsyncMock()

        clock.t = T0 + 20
        assert await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 50
        assert await state.resume_game()

        state._media_player_service.play.assert_awaited_once_with()
        assert state._round_manager._sample_stop_task is None
        assert state.sample_stopped is False
        await _cleanup(state)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class TestState:
    async def test_the_state_says_how_long_the_song_plays_and_that_it_stopped(self):
        clock = _Clock()
        state = _playing_round(clock)

        frame = state.get_state()
        assert frame["sample_duration"] == SAMPLE
        assert frame["sample_stopped"] is False
        assert frame["round_duration"] == ROUND

        await _let_the_sample_run_out(state, clock)

        frame = state.get_state()
        assert frame["phase"] == "PLAYING"
        assert frame["sample_stopped"] is True
        await _cleanup(state)

    def test_the_lobby_already_carries_the_setting(self):
        state = _lobby(round_duration=45, sample_duration=20)
        frame = state.get_state()
        assert frame["sample_duration"] == 20
        assert frame["sample_stopped"] is False

    def test_a_game_without_the_setting_reports_zero(self):
        frame = _lobby().get_state()
        assert frame["sample_duration"] == 0
        assert frame["sample_stopped"] is False

    def test_the_phones_may_see_both_fields(self):
        assert {"sample_duration", "sample_stopped"} <= _PLAYER_VISIBLE_BASE

    def test_ending_the_game_clears_the_round_flag(self):
        rm = RoundManager(_Clock())
        rm.sample_duration = 15
        rm.sample_stopped = True
        rm.reset()
        assert rm.sample_duration == 0
        assert rm.sample_stopped is False
