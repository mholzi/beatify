"""Tests for the Title & Artist RACE-mode WS handler (live buzzer variant).

Drives the real ``handle_title_artist_race_guess`` and asserts the behaviour
that separates it from the single-shot title/artist handler:

- players are NEVER marked ``submitted`` (unlimited attempts),
- the first correct guesser of each field claims it (a later correct guess does
  not steal it), title and artist raced independently,
- the round completes (early reveal) once BOTH fields are solved — even when
  different players solved them — and the winners are scored.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import (
    ARTIST_RACE_POINTS,
    DOMAIN,
    TITLE_RACE_POINTS,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.services.playback import BrowserClientRegistry
from tests.conftest import make_game_state, make_songs

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)


def _ta_songs(n: int = 3) -> list[dict]:
    songs = make_songs(n)
    for i, s in enumerate(songs):
        s["title"] = f"Real Title {i}"
        s["artist"] = f"Real Artist {i}"
    return songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.stop = AsyncMock()
    svc.get_playback_state = MagicMock(return_value="playing")
    return svc


class _Clock:
    """Injected game clock so tests can step past the race-attempt throttle."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _make_handler_game(clock: _Clock | None = None):
    mock_hass = MagicMock()
    gs = make_game_state(time_fn=clock)
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_race_mode=True,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(
        mock_hass, browser_clients=BrowserClientRegistry()
    )
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    return handler, gs


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


async def _race_guess(handler, ws, title="", artist=""):
    await handler._handle_message(
        ws,
        {"type": "title_artist_race_guess", "title": title, "artist": artist},
    )


class TestRaceHandler:
    async def test_race_mode_is_configured(self):
        _, gs = _make_handler_game()
        assert gs.title_artist_race_mode is True
        assert gs.title_artist_mode is True

    async def test_guess_does_not_mark_submitted(self):
        """Race players keep guessing — the handler must not lock them in."""
        clock = _Clock()
        handler, gs = _make_handler_game(clock)
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        assert gs.phase == GamePhase.PLAYING

        # A wrong guess, then the same player guesses again — no "already
        # submitted" error, and never marked submitted.
        await _race_guess(handler, ws, title="nope")
        clock.now += 1
        await _race_guess(handler, ws, title="still nope")
        player = gs.get_player("Alice")
        assert player.submitted is False
        assert len(gs.title_artist_challenge.feed) == 2
        ack = ws.send_json.call_args_list[-1].args[0]
        assert ack["type"] == "title_artist_race_guess_ack"
        assert gs.phase == GamePhase.PLAYING

        gs._cancel_auto_advance()

    async def test_first_correct_wins_and_ack(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        title = gs.current_song["title"]

        await _race_guess(handler, ws, title=title)
        assert gs.title_artist_challenge.title_winner == "Alice"

        ack = ws.send_json.call_args_list[-1].args[0]
        assert ack["type"] == "title_artist_race_guess_ack"
        assert ack["won_title"] is True

        gs._cancel_auto_advance()

    async def test_both_solved_by_different_players_ends_round(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = _ws(), _ws()
        gs.add_player("Alice", alice_ws)
        gs.add_player("Bob", bob_ws)
        for p in gs.players.values():
            p.connected = True
        await gs.start_round()
        title = gs.current_song["title"]
        artist = gs.current_song["artist"]

        # Alice solves the title; round not yet complete.
        await _race_guess(handler, alice_ws, title=title)
        assert gs.phase == GamePhase.PLAYING
        assert gs.check_all_guesses_complete() is False

        # Bob solves the artist; both fields settled -> early reveal.
        await _race_guess(handler, bob_ws, artist=artist)
        assert gs.title_artist_challenge.artist_winner == "Bob"
        assert gs.phase == GamePhase.REVEAL

        # Winners are scored; each banks their one field.
        assert gs.get_player("Alice").round_score == TITLE_RACE_POINTS
        assert gs.get_player("Bob").round_score == ARTIST_RACE_POINTS

        gs._cancel_auto_advance()

    async def test_later_correct_guess_does_not_steal(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = _ws(), _ws()
        gs.add_player("Alice", alice_ws)
        gs.add_player("Bob", bob_ws)
        for p in gs.players.values():
            p.connected = True
        await gs.start_round()
        title = gs.current_song["title"]

        await _race_guess(handler, alice_ws, title=title)
        await _race_guess(handler, bob_ws, title=title)
        assert gs.title_artist_challenge.title_winner == "Alice"

        gs._cancel_auto_advance()

    async def test_empty_guess_rejected(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        await _race_guess(handler, ws, title="   ", artist="")
        ack = ws.send_json.call_args_list[-1].args[0]
        assert ack["type"] == "error"

        gs._cancel_auto_advance()


class TestRaceHandlerHardening:
    """#3557: the race message follows the rules of the other guess handlers."""

    async def test_rapid_second_attempt_is_throttled(self):
        clock = _Clock()
        handler, gs = _make_handler_game(clock)
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        await _race_guess(handler, ws, title="nope")
        await _race_guess(handler, ws, title="Real Title 0")
        ack = ws.send_json.call_args_list[-1].args[0]
        assert ack["type"] == "error"
        assert ack["code"] == "GUESS_TOO_FAST"
        assert len(gs.title_artist_challenge.feed) == 1
        assert gs.title_artist_challenge.title_winner is None

        gs._cancel_auto_advance()

    async def test_unknown_socket_is_rejected(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        stranger = _ws()
        title = gs.current_song["title"]
        # A client-sent name is ignored: identity comes from the socket only.
        await handler._handle_message(
            stranger,
            {"type": "title_artist_race_guess", "title": title, "name": "Alice"},
        )
        err = stranger.send_json.call_args_list[-1].args[0]
        assert err["type"] == "error"
        assert gs.title_artist_challenge.title_winner is None

        gs._cancel_auto_advance()

    async def test_eliminated_player_is_rejected(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        gs.get_player("Alice").eliminated = True

        await _race_guess(handler, ws, title=gs.current_song["title"])
        err = ws.send_json.call_args_list[-1].args[0]
        assert err["type"] == "error"
        assert gs.title_artist_challenge.title_winner is None

        gs._cancel_auto_advance()

    async def test_race_guess_outside_race_mode_is_rejected(self):
        mock_hass = MagicMock()
        gs = make_game_state()
        gs.create_game(
            playlists=["t.json"],
            songs=_ta_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            title_artist_mode=True,
        )
        gs._media_player_service = _stub_media_service()
        gs.platform = "music_assistant"
        mock_hass.data = {DOMAIN: {"game": gs}}
        handler = BeatifyWebSocketHandler(
            mock_hass, browser_clients=BrowserClientRegistry()
        )
        handler.debounced_broadcast_state = AsyncMock()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        await _race_guess(handler, ws, title=gs.current_song["title"])
        err = ws.send_json.call_args_list[-1].args[0]
        assert err["type"] == "error"
        assert err["code"] == "NO_TITLE_ARTIST_CHALLENGE"

        gs._cancel_auto_advance()

    async def test_single_shot_guess_is_refused_in_race_mode(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        await handler._handle_message(
            ws,
            {
                "type": "title_artist_guess",
                "title": gs.current_song["title"],
                "artist": "",
            },
        )
        err = ws.send_json.call_args_list[-1].args[0]
        assert err["type"] == "error"
        assert gs.get_player("Alice").submitted is False

        gs._cancel_auto_advance()

    async def test_ack_never_says_near_miss(self):
        """Unlimited attempts + a "close" signal would let a guesser home in."""
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        title = gs.current_song["title"]

        await _race_guess(handler, ws, title=title[:-1])  # one letter short
        ack = ws.send_json.call_args_list[-1].args[0]
        assert ack["type"] == "title_artist_race_guess_ack"
        assert ack["title_status"] in ("wrong", "correct")
        assert ack["title_status"] != "near_miss"
        assert ack["artist_status"] == "skipped"

        gs._cancel_auto_advance()

    async def test_ack_never_carries_the_answer(self):
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()

        await _race_guess(handler, ws, title="nope")
        ack = ws.send_json.call_args_list[-1].args[0]
        assert gs.current_song["title"] not in str(ack)
        assert gs.current_song["artist"] not in str(ack)

        gs._cancel_auto_advance()
