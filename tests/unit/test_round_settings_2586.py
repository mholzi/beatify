"""#2586 — the host changes timer and difficulty between two rounds.

The settings are parked on the reveal and land when the next round is
committed. A title/artist round is scored at the end of its vote window, during
REVEAL, so writing them straight away would rescore the round on screen.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    DOMAIN,
    ERR_INVALID_ACTION,
    ERR_NOT_ADMIN,
)
from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.server.serializers import (
    ADMIN_ONLY_KEYS,
    HOST_PLAYER_KEYS,
    PLAYER_VISIBLE_KEYS,
    redact_state_for_player,
    state_for_host_player,
)
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _ws() -> MagicMock:
    ws = MagicMock()
    ws.closed = False
    ws.send_json = AsyncMock()
    return ws


def _media() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


async def _playing_game(*, options: GameOptions | None = None, songs: int = 6):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        options=options or GameOptions(),
    )
    gs._media_player_service = _media()
    gs.platform = "music_assistant"
    for name in ("Host", "Guest"):
        gs.add_player(name, _ws())
        gs.get_player(name).connected = True
    gs.get_player("Host").is_admin = True
    assert await gs.start_round() is True
    return gs


def _guess(gs, name: str, years_off: int) -> None:
    player = gs.get_player(name)
    player.submitted = True
    player.current_guess = gs.current_song["year"] - years_off
    player.submission_time = gs.round_start_time


async def _reveal(gs, years_off: int = 3) -> None:
    _guess(gs, "Host", years_off)
    _guess(gs, "Guest", years_off)
    await gs.end_round()
    assert gs.phase == GamePhase.REVEAL


def _handler(gs) -> BeatifyWebSocketHandler:
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(hass)
    handler.broadcast_state = AsyncMock()
    return handler


async def _send(handler, ws, **fields) -> None:
    await handler._handle_message(
        ws, {"type": "admin", "action": "set_round_settings", **fields}
    )


def _errors(ws) -> list[dict]:
    return [
        c.args[0]
        for c in ws.send_json.await_args_list
        if c.args and isinstance(c.args[0], dict) and c.args[0].get("type") == "error"
    ]


async def _host(gs):
    """The handler plus the socket of the host who plays along."""
    return _handler(gs), gs.get_player("Host").ws


class TestHandler:
    async def test_accepted_in_reveal_and_broadcast(self):
        gs = await _playing_game()
        await _reveal(gs)
        handler, host = await _host(gs)

        await _send(handler, host, timer=30, difficulty="hard")

        assert _errors(host) == []
        assert gs.next_round_settings() == {
            "round_duration": 30,
            "difficulty": "hard",
        }
        handler.broadcast_state.assert_awaited_once()

    async def test_each_chip_sends_one_field(self):
        gs = await _playing_game()
        await _reveal(gs)
        handler, host = await _host(gs)

        await _send(handler, host, timer=60)
        await _send(handler, host, difficulty="easy")

        assert gs.next_round_settings() == {
            "round_duration": 60,
            "difficulty": "easy",
        }

    @pytest.mark.parametrize(
        "phase", [GamePhase.LOBBY, GamePhase.PLAYING, GamePhase.PAUSED, GamePhase.END]
    )
    async def test_rejected_outside_reveal(self, phase):
        gs = await _playing_game()
        handler, host = await _host(gs)
        gs.phase = phase

        await _send(handler, host, timer=30)

        assert [e["code"] for e in _errors(host)] == [ERR_INVALID_ACTION]
        assert _errors(host)[0]["message_key"] == "ROUND_SETTINGS_REVEAL_ONLY"
        assert gs._pending_round_settings == {}
        handler.broadcast_state.assert_not_awaited()

    async def test_rejected_on_the_last_reveal(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.last_round = True
        handler, host = await _host(gs)

        await _send(handler, host, timer=30)

        assert _errors(host)[0]["message_key"] == "ROUND_SETTINGS_REVEAL_ONLY"
        assert gs.next_round_settings() is None

    @pytest.mark.parametrize(
        "fields",
        [
            {},
            {"timer": 15},
            {"timer": "30"},
            {"timer": 30.0},
            {"timer": True},
            {"timer": [30]},
            {"difficulty": "brutal"},
            {"difficulty": ["hard"]},
            {"difficulty": {"hard": 1}},
            {"timer": 30, "difficulty": "brutal"},
        ],
    )
    async def test_invalid_values_change_nothing(self, fields):
        gs = await _playing_game()
        await _reveal(gs)
        handler, host = await _host(gs)

        await _send(handler, host, **fields)

        assert _errors(host)[0]["message_key"] == "INVALID_ROUND_SETTINGS"
        assert gs._pending_round_settings == {}
        handler.broadcast_state.assert_not_awaited()

    async def test_non_admin_is_rejected(self):
        gs = await _playing_game()
        await _reveal(gs)
        handler = _handler(gs)
        guest = gs.get_player("Guest").ws

        await _send(handler, guest, timer=30, difficulty="hard")

        assert [e["code"] for e in _errors(guest)] == [ERR_NOT_ADMIN]
        assert gs._pending_round_settings == {}

    async def test_title_artist_has_no_difficulty_to_change(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.title_artist_mode = True
        handler, host = await _host(gs)

        await _send(handler, host, difficulty="hard")
        assert _errors(host)[0]["message_key"] == "INVALID_ROUND_SETTINGS"

        host.send_json.reset_mock()
        await _send(handler, host, timer=30)
        assert _errors(host) == []


class TestScoring:
    async def test_revealed_round_keeps_its_scores_next_round_uses_the_new_ones(self):
        gs = await _playing_game()
        await _reveal(gs, years_off=3)  # Normal pays for 3 years off.
        scored = gs.get_player("Guest").score
        assert scored > 0
        breakdown = gs.get_player("Guest").round_score
        handler, host = await _host(gs)

        await _send(handler, host, timer=30, difficulty="hard")

        # The round on screen is still the round that was played.
        assert gs.get_player("Guest").score == scored
        assert gs.get_player("Guest").round_score == breakdown
        assert gs.difficulty == "normal"
        assert gs.round_duration == 45

        assert await gs.start_round() is True
        assert gs.difficulty == "hard"
        assert gs.round_duration == 30
        deadline_seconds = (gs.deadline - int(gs._now() * 1000)) / 1000
        assert deadline_seconds <= 30

        await _reveal(gs, years_off=3)  # Hard pays nothing for 3 years off.
        assert gs.get_player("Guest").round_score == 0
        assert gs.get_player("Guest").score == scored

    async def test_vote_window_scores_with_the_settings_of_the_revealed_round(self):
        """The deferred title/artist pass runs after the host may have tapped."""
        gs = await _playing_game()
        await _reveal(gs)
        seen = {}

        def _spy(correct_year, all_players):
            seen["difficulty"] = gs.difficulty
            seen["round_duration"] = gs.round_duration

        gs._score_all_players = _spy
        gs._challenge_manager.resolve_title_artist = MagicMock()
        gs._title_artist_voting_open = True
        handler, host = await _host(gs)

        await _send(handler, host, timer=30, difficulty="hard")
        await gs._finalize_title_artist_window()

        assert seen == {"difficulty": "normal", "round_duration": 45}

    async def test_bet_payout_on_the_reveal_stays_until_the_round_lands(self):
        gs = await _playing_game(
            options=GameOptions(difficulty_bet_scaling_enabled=True)
        )
        await _reveal(gs)
        before = GameStateSerializer.serialize(gs)["bet_win_multiplier"]
        gs.set_round_settings(difficulty="hard")

        assert GameStateSerializer.serialize(gs)["bet_win_multiplier"] == before

        assert await gs.start_round() is True
        assert GameStateSerializer.serialize(gs)["bet_win_multiplier"] == 5

    async def test_a_failed_round_start_keeps_the_picks_parked(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30)
        gs._media_player_service.play_song = AsyncMock(return_value=False)

        await gs.start_round()

        assert gs.round_duration == 45
        assert gs._pending_round_settings == {"round_duration": 30}


class TestNotice:
    async def _notice_after(self, **fields):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(**fields)
        assert await gs.start_round() is True
        return gs, GameStateSerializer.serialize(gs)["round_settings_notice"]

    async def test_shows_for_exactly_one_round(self):
        gs, notice = await self._notice_after(timer=30, difficulty="hard")
        assert notice == {
            "round_duration": 30,
            "difficulty": "hard",
            "close_points": 3,
            "close_range": 2,
        }

        await _reveal(gs)
        assert "round_settings_notice" not in GameStateSerializer.serialize(gs)

        assert await gs.start_round() is True
        assert GameStateSerializer.serialize(gs)["round_settings_notice"] is None

    async def test_timer_only_does_not_mention_difficulty(self):
        _, notice = await self._notice_after(timer=30)
        assert notice == {"round_duration": 30}

    async def test_difficulty_only_does_not_mention_the_timer(self):
        _, notice = await self._notice_after(difficulty="easy")
        assert notice == {"difficulty": "easy", "close_points": 5, "close_range": 7}

    async def test_no_op_shows_nothing(self):
        _, notice = await self._notice_after(timer=45, difficulty="normal")
        assert notice is None

    async def test_there_and_back_on_one_reveal_shows_nothing(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30, difficulty="hard")
        gs.set_round_settings(timer=45, difficulty="normal")
        assert await gs.start_round() is True
        assert gs.round_settings_notice is None

    async def test_swapping_the_song_keeps_the_notice(self):
        gs, notice = await self._notice_after(timer=30)
        assert notice is not None

        assert await gs.skip_song() is None

        assert GameStateSerializer.serialize(gs)["round_settings_notice"] == notice
        assert gs.round_duration == 30


class TestGameBoundaries:
    async def test_rematch_keeps_what_landed_and_drops_what_did_not(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30)
        assert await gs.start_round() is True
        await _reveal(gs)
        gs.set_round_settings(difficulty="hard")
        gs.phase = GamePhase.END

        gs.rematch_game()

        assert gs.round_duration == 30
        assert gs.difficulty == "normal"
        assert gs._pending_round_settings == {}
        assert gs.round_settings_notice is None

    async def test_new_game_starts_clean(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30)
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(4),
            media_player="media_player.x",
            base_url="http://h",
        )
        assert gs._pending_round_settings == {}

    async def test_sample_as_long_as_the_new_timer_means_the_whole_round(self):
        gs = await _playing_game(options=GameOptions(sample_duration=30))
        await _reveal(gs)
        gs.set_round_settings(timer=30)
        assert await gs.start_round() is True
        assert gs._round_manager.sample_playback_seconds() is None


class TestWhoSeesWhat:
    def test_keys_are_classified(self):
        assert "round_settings_notice" in PLAYER_VISIBLE_KEYS
        assert "next_round_settings" in ADMIN_ONLY_KEYS
        assert "next_round_settings" in HOST_PLAYER_KEYS
        assert HOST_PLAYER_KEYS <= ADMIN_ONLY_KEYS

    async def test_guests_do_not_see_a_pending_change(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30)

        state = {"type": "state", **GameStateSerializer.serialize(gs)}

        assert state["next_round_settings"]["round_duration"] == 30
        guest = redact_state_for_player(state)
        assert "next_round_settings" not in guest
        # The host's phone is a player socket and gets it on top of that copy.
        host = state_for_host_player(state, guest)
        assert host["next_round_settings"]["round_duration"] == 30
        assert "admin_song" not in host

    async def test_guests_do_see_the_notice(self):
        gs = await _playing_game()
        await _reveal(gs)
        gs.set_round_settings(timer=30)
        assert await gs.start_round() is True

        state = {"type": "state", **GameStateSerializer.serialize(gs)}

        assert redact_state_for_player(state)["round_settings_notice"] == {
            "round_duration": 30
        }
