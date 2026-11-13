"""#3491 - a single player can start a game, and the game copes with it.

The floor is one *connected* player. Steal and sabotage are duels, so a solo
game never gets a token; a near-miss with nobody allowed to vote is accepted at
once instead of after a 30 s window; and solo games stay out of party averages.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.const import DOMAIN, STEAL_UNLOCK_STREAK
from custom_components.beatify.game.scoring import ScoringService
from custom_components.beatify.game.start_gameplay import (
    REFUSE_NOT_ENOUGH_PLAYERS,
    refusal_to_start,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.game_views import StartGameplayView
from custom_components.beatify.server.ws_handlers.admin import admin_start_game

from tests.conftest import make_game_state, make_player, make_songs


def _lobby(players: int = 0, *, connected: bool = True, **kwargs):
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )
    for i in range(players):
        ws = AsyncMock()
        ws.closed = False
        state.add_player(f"P{i}", ws)
        state.get_player(f"P{i}").connected = connected
    state.start_round = AsyncMock(return_value=True)
    return state


def _handler() -> MagicMock:
    handler = MagicMock()
    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    handler.broadcast_metadata_update = AsyncMock()
    return handler


@patch(
    "custom_components.beatify.server.game_views.is_authorized_http",
    return_value=True,
)
async def _rest_start(state, _auth):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": _handler()}}
    return await StartGameplayView(hass).post(MagicMock())


class TestStartFloor:
    async def test_one_player_starts_over_rest(self):
        state = _lobby(1)
        resp = await _rest_start(state)
        assert resp.status == 200
        state.start_round.assert_awaited_once()

    async def test_one_player_starts_over_websocket(self):
        state = _lobby(1)
        ws = AsyncMock()
        await admin_start_game(_handler(), ws, {}, state)
        state.start_round.assert_awaited_once()

    def test_zero_players_are_refused(self):
        assert refusal_to_start(_lobby(0)) == REFUSE_NOT_ENOUGH_PLAYERS

    async def test_disconnected_only_lobby_is_refused_on_both_paths(self):
        state = _lobby(2, connected=False)
        assert refusal_to_start(state) == REFUSE_NOT_ENOUGH_PLAYERS

        resp = await _rest_start(state)
        assert resp.status == 409
        assert json.loads(resp.body)["code"] == "NOT_ENOUGH_PLAYERS"

        ws = AsyncMock()
        await admin_start_game(_handler(), ws, {}, state)
        assert ws.send_json.call_args.args[0]["message_key"] == "NEED_PLAYERS"
        state.start_round.assert_not_awaited()
        assert state.phase == GamePhase.LOBBY

    def test_one_connected_among_ghosts_may_start(self):
        state = _lobby(2, connected=False)
        state.get_player("P0").connected = True
        assert refusal_to_start(state) is None


class TestNoDuelTokensWhenSolo:
    def test_no_sabotage_token_for_a_lone_player(self):
        state = _lobby(1, sabotage_enabled=True)
        state._grant_sabotage_tokens()
        assert state.get_player("P0").sabotage_available is False

    def test_sabotage_token_still_granted_with_two_players(self):
        state = _lobby(2, sabotage_enabled=True)
        state._grant_sabotage_tokens()
        assert state.get_player("P0").sabotage_available is True

    @staticmethod
    def _streak_to_unlock(players):
        player = players[0]
        for _ in range(STEAL_UNLOCK_STREAK):
            player.submitted = True
            player.current_guess = 1980
            player.submission_time = 1.0
            ScoringService.score_player_round(
                player,
                correct_year=1980,
                round_start_time=0.0,
                round_duration=30.0,
                difficulty="normal",
                artist_challenge=None,
                movie_challenge=None,
                is_intro_round=False,
                intro_round_start_time=None,
                all_players=players,
                streak_achievements={},
                bet_tracking={},
            )
        return player

    def test_no_steal_unlock_for_a_lone_player(self):
        player = self._streak_to_unlock([make_player("Solo")])
        assert player.streak == STEAL_UNLOCK_STREAK
        assert player.steal_available is False

    def test_steal_still_unlocks_with_two_players(self):
        players = [make_player("A"), make_player("B")]
        player = self._streak_to_unlock(players)
        assert player.steal_available is True


class TestVoteWindowSkippedWhenSolo:
    async def _reveal(self, names):
        songs = make_songs(3)
        for i, song in enumerate(songs):
            song["title"] = f"Real Title {i}"
            song["artist"] = f"Real Artist {i}"
        state = make_game_state()
        state.create_game(
            playlists=["t.json"],
            songs=songs,
            media_player="media_player.x",
            base_url="http://h",
            title_artist_mode=True,
        )
        state.platform = "music_assistant"
        for name in names:
            state.add_player(name, MagicMock())
            state.get_player(name).connected = True
        await state.start_round()
        state._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", state.current_song["artist"], 1.0
        )
        for name in names[1:]:
            state._challenge_manager.submit_title_artist_guess(
                name, state.current_song["title"], state.current_song["artist"], 1.0
            )
        for p in state.players.values():
            p.submitted = True
        await state.end_round()
        return state

    async def test_solo_near_miss_is_accepted_at_once(self):
        state = await self._reveal(["Alice"])
        assert state.phase == GamePhase.REVEAL
        assert state.is_title_artist_voting_open() is False
        assert state.title_artist_challenge.resolved is True
        assert (
            state.title_artist_challenge.guesses["Alice"]["title_status"]
            == "near_miss_accepted"
        )

    async def test_window_still_opens_when_someone_can_vote(self):
        state = await self._reveal(["Alice", "Bob"])
        assert state.is_title_artist_voting_open() is True
        state._cancel_auto_advance()


class TestSoloAnalytics:
    def test_finalize_game_flags_a_solo_game(self):
        assert _lobby(1).finalize_game()["solo"] is True
        assert _lobby(2).finalize_game()["solo"] is False

    def test_party_averages_ignore_solo_games(self):
        from custom_components.beatify.analytics import AnalyticsStorage

        def rec(gid, players, solo=False):
            r = {
                "game_id": gid,
                "started_at": 1_000_000,
                "ended_at": 1_000_100,
                "duration_seconds": 100,
                "player_count": players,
                "playlist_names": ["p"],
                "rounds_played": 5,
                "average_score": 10.0,
                "difficulty": "normal",
                "error_count": 0,
                "streak_3_count": 0,
                "streak_5_count": 0,
                "streak_10_count": 0,
                "total_bets": 0,
                "bets_won": 0,
            }
            if solo:
                r["solo"] = True
            return r

        store = AnalyticsStorage.__new__(AnalyticsStorage)
        store._data = store._empty_data()
        store._metrics_cache = {}
        store._games_since_prune = 0
        store._playlist_display_names = {}
        games = [rec("a", 4), rec("b", 6), rec("c", 1, solo=True), rec("old", 1)]
        store._data["games"] = games
        with patch(
            "custom_components.beatify.analytics.time.time", return_value=1_000_200
        ):
            m = store.compute_metrics("all")
        # "old" has no solo flag: pre-#3491 history reads as a party game.
        assert m["total_games"] == 4
        assert m["peak_players"] == 6
        assert m["avg_players_per_game"] == round((4 + 6 + 1) / 3, 1)

    async def test_stats_service_keeps_solo_out_of_all_time(self):
        from custom_components.beatify.services.stats import StatsService

        hass = MagicMock()
        hass.config.path = lambda *a: "/tmp/x"
        svc = StatsService.__new__(StatsService)
        svc.__init__(hass)
        svc.async_flush = AsyncMock()
        svc._analytics = None
        base = {"playlist": "p", "rounds": 5, "winner": "A", "winner_score": 50}
        await svc.record_game({**base, "player_count": 2, "total_points": 100})
        before = svc.all_time_avg
        await svc.record_game(
            {**base, "player_count": 1, "total_points": 500, "solo": True}
        )
        assert svc.games_played == 1
        assert svc.all_time_avg == before
