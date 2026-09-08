"""#2718 — the ``kick_player`` contract the host's lobby now depends on again.

``admin_kick_player`` has been registered since #659 (April), but PR #1613
(26 June) deleted the only UI that ever sent it, along with the flat lobby the
button lived in. Nothing has exercised the handler from a client since. #2718
puts a Remove button back on the host's lobby, so these tests pin the four
rules the new client assumes when it decides who gets one at all:

* lobby phase only,
* the admin can never be removed,
* a *connected* player can never be removed,
* an away player is removed for good — name index, session map and player
  record — and the room is told.

The client mirrors the middle two by listing only away, non-host guests
(``buildHomeAwayList``). If a rule here changes, that rendering is wrong in the
same commit.

``TestTheAwayClock`` at the bottom covers the other half of the design gate's
answer: the **duration** each row carries. It is a server fact on purpose — a
timer the host's browser started would restart at every reload and report
"just now" for a guest who left before dinner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_INVALID_ACTION
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


def _handler_and_game() -> tuple[BeatifyWebSocketHandler, GameState]:
    mock_hass = MagicMock()
    game_state = make_game_state()
    game_state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    mock_hass.data = {DOMAIN: {"game": game_state}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.debounced_broadcast_state = AsyncMock()
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    return handler, game_state


def _seat_host(handler: BeatifyWebSocketHandler, game_state: GameState) -> AsyncMock:
    """Seat the host and register their socket as the admin spectator WS."""
    ws = _ws()
    game_state.add_player("Markus", ws)
    game_state.set_admin("Markus")
    handler.admin_ws = ws
    return ws


def _seat_guest(game_state: GameState, name: str, *, away: bool = False) -> AsyncMock:
    ws = _ws()
    game_state.add_player(name, ws)
    if away:
        # Exactly what BeatifyWebSocketHandler._handle_disconnect does: the
        # session stays in the lobby with connected=False. That flag is what
        # the state broadcast ships as ``connected`` and what the host's tile
        # grid paints as "away".
        player = game_state.get_player(name)
        player.set_connected(False)
        player.ws = None
    return ws


async def _kick(handler, admin_ws, name):
    await handler._handle_message(
        admin_ws, {"type": "admin", "action": "kick_player", "player_name": name}
    )


def _last_error(ws: AsyncMock) -> dict | None:
    for call in reversed(ws.send_json.call_args_list):
        msg = call[0][0]
        if msg.get("type") == "error":
            return msg
    return None


class TestKickRemovesAnAwayGuest:
    async def test_away_guest_is_gone_and_the_room_is_told(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)
        assert game_state.get_player("Kirsten") is not None

        await _kick(handler, admin_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is None
        assert "Kirsten" not in [p.name for p in game_state.players.values()]
        # The slot is genuinely free: the freed seat is what #2718 is about.
        handler.broadcast_state.assert_awaited()
        assert _last_error(admin_ws) is None

    async def test_the_name_is_matched_case_insensitively(self):
        # The client sends back the display name it rendered; F6 made every
        # registry lookup case-insensitive, so a tile is not name-fragile.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "kirsten")

        assert game_state.get_player("Kirsten") is None

    async def test_the_freed_name_can_join_again(self):
        # "They can scan the QR code again any time" is in the confirm modal,
        # so it had better be true.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "Kirsten")
        game_state.add_player("Kirsten", _ws())

        rejoined = game_state.get_player("Kirsten")
        assert rejoined is not None
        assert rejoined.connected is True
        assert rejoined.is_admin is False


class TestKickIsRefused:
    async def test_a_connected_guest_is_removed_too(self):
        # Changed on 2026-09-08 by the #2746 design gate (option B). The old
        # refusal was the reason the button only appeared on away tiles, and it
        # was also why the case that started #2746 — a guest who has to leave
        # mid-party, phone in their pocket and connected — had no answer at
        # all. In the lobby nothing has been played, so removal still deletes.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Jonas")

        await _kick(handler, admin_ws, "Jonas")

        assert game_state.get_player("Jonas") is None
        assert _last_error(admin_ws) is None

    async def test_the_admin_is_refused_even_when_away(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        host = game_state.get_player("Markus")
        host.connected = False
        host.ws = None

        await _kick(handler, admin_ws, "Markus")

        assert game_state.get_player("Markus") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_an_unknown_name_is_refused_without_touching_anybody(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "Nobody")

        assert game_state.get_player("Kirsten") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_an_empty_name_is_a_no_op(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "")

        assert game_state.get_player("Kirsten") is not None
        assert _last_error(admin_ws) is None

    async def test_outside_the_lobby_the_guest_is_sat_out_not_deleted(self):
        # Changed on 2026-09-08 by the #2746 design gate (option B). The phase
        # refusal is gone, but what replaces it is NOT the lobby's behaviour:
        # mid-game the session survives and only `sat_out_by_host` is set, so
        # the score stays, the rank stays, and the guest can tap their way back
        # in. That recoverability is the guard now — deleting here would make a
        # mis-tap in a dark room unrecoverable, which is what lost option D the
        # gate.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)
        kirsten = game_state.get_player("Kirsten")
        kirsten.score = 980
        game_state.phase = GamePhase.PLAYING

        await _kick(handler, admin_ws, "Kirsten")

        assert _last_error(admin_ws) is None
        still_there = game_state.get_player("Kirsten")
        assert still_there is not None
        assert still_there.sat_out_by_host is True
        assert still_there.out_of_play is True
        assert still_there.score == 980

    async def test_a_guest_cannot_kick_another_guest(self):
        handler, game_state = _handler_and_game()
        _seat_host(handler, game_state)
        guest_ws = _seat_guest(game_state, "Jonas")
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, guest_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is not None
        err = _last_error(guest_ws)
        assert err is not None
        assert err["code"] != ERR_INVALID_ACTION  # NOT_ADMIN, refused earlier


class TestTheAwayClock:
    """#2718 — where the "4 min" / "12 min" on each away row comes from.

    The design gate picked the list *because* of this number: without it the
    host is told only "not currently connected" and asked for a decision that
    cannot be made from that. So the stamp, its transitions and the fact that
    it is server-owned are pinned here, not left to the renderer.
    """

    def _lobby_with_clock(self):
        clock = {"t": 1_000.0}
        game_state = make_game_state(time_fn=lambda: clock["t"])
        game_state.create_game(
            playlists=["test.json"],
            songs=make_songs(5),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        return game_state, clock

    def _row(self, game_state, name):
        return next(p for p in game_state.get_players_state() if p["name"] == name)

    def test_a_connected_player_has_no_stamp_and_no_duration(self):
        game_state, _clock = self._lobby_with_clock()
        game_state.add_player("Jonas", _ws())

        assert game_state.get_player("Jonas").disconnected_at is None
        assert self._row(game_state, "Jonas")["away_seconds"] is None

    def test_going_away_stamps_the_clock_and_the_duration_grows_with_it(self):
        game_state, clock = self._lobby_with_clock()
        game_state.add_player("Kirsten", _ws())

        game_state.get_player("Kirsten").set_connected(False, now=clock["t"])
        assert self._row(game_state, "Kirsten")["away_seconds"] == 0

        clock["t"] += 240
        assert self._row(game_state, "Kirsten")["away_seconds"] == 240
        clock["t"] += 505
        assert self._row(game_state, "Kirsten")["away_seconds"] == 745

    def test_the_duration_survives_a_host_reload(self):
        # The host pressing F5 re-fetches /beatify/api/status, which serialises
        # the same PlayerSession through the same registry. Nothing in the
        # browser contributes to the number, so a second read of a twelve-
        # minute absence still says twelve minutes — the failure mode a
        # client-side timer would have had.
        game_state, clock = self._lobby_with_clock()
        game_state.add_player("Kira", _ws())
        game_state.get_player("Kira").set_connected(False, now=clock["t"])
        clock["t"] += 720

        first = self._row(game_state, "Kira")["away_seconds"]
        reloaded = self._row(game_state, "Kira")["away_seconds"]

        assert first == 720
        assert reloaded == 720

    def test_coming_back_clears_the_stamp(self):
        game_state, clock = self._lobby_with_clock()
        game_state.add_player("Kirsten", _ws())
        player = game_state.get_player("Kirsten")
        player.set_connected(False, now=clock["t"])
        clock["t"] += 300

        player.set_connected(True, now=clock["t"])

        assert player.disconnected_at is None
        assert self._row(game_state, "Kirsten")["away_seconds"] is None

    def test_a_repeated_going_away_does_not_restart_the_clock(self):
        # ``_undo_admin_claim`` reverts a rejected reconnect by setting
        # connected=False on somebody who was already away. Restarting their
        # clock there would hand the host a fresh "just now" for a guest who
        # has been gone twenty minutes — the exact lie this field exists to
        # prevent.
        game_state, clock = self._lobby_with_clock()
        game_state.add_player("Tim", _ws())
        player = game_state.get_player("Tim")
        player.set_connected(False, now=clock["t"])
        clock["t"] += 1_200

        player.set_connected(False, now=clock["t"])

        assert self._row(game_state, "Tim")["away_seconds"] == 1_200

    def test_an_away_player_without_a_stamp_reports_no_duration(self):
        # A record that predates the stamp. Reporting 0 would say "just now"
        # about someone who may have left an hour ago; the row then shows no
        # duration at all instead.
        game_state, clock = self._lobby_with_clock()
        game_state.add_player("Nina", _ws())
        player = game_state.get_player("Nina")
        player.connected = False
        player.disconnected_at = None

        assert self._row(game_state, "Nina")["away_seconds"] is None

    async def test_a_disconnect_through_the_real_handler_starts_the_clock(self):
        # The stamp is only worth anything if THE disconnect path sets it —
        # everything above would still pass with a field nobody ever writes.
        handler, game_state = _handler_and_game()
        _seat_host(handler, game_state)
        guest_ws = _ws()
        game_state.add_player("Kirsten", guest_ws)

        await handler._handle_disconnect(guest_ws)

        player = game_state.get_player("Kirsten")
        assert player.connected is False
        assert player.disconnected_at is not None
        # And it reaches the host's lobby as a number, not as a raw epoch.
        row = next(p for p in game_state.get_players_state() if p["name"] == "Kirsten")
        assert row["away_seconds"] is not None
        assert row["away_seconds"] >= 0

    async def test_the_guest_appears_immediately_with_no_grace_period(self):
        # Deliberate (design gate, 05.09.2026): the duration IS the grace
        # period, judged by a human standing in the room. A machine one on top
        # would duplicate that judgement and delay exactly the case the feature
        # exists for. So a guest is listable the moment they drop.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        guest_ws = _ws()
        game_state.add_player("Kirsten", guest_ws)

        await handler._handle_disconnect(guest_ws)
        await _kick(handler, admin_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is None
        assert _last_error(admin_ws) is None
