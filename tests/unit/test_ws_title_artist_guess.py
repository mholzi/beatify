"""Tests for the title/artist guess WS handler (#1180).

Regression guard: the handler must mark the player as *submitted* (not just
set ``has_title_artist_guess``) so the scoring path (which gates on
``player.submitted``) banks the title+artist points and early-reveal can fire.
These drive the real ``handle_title_artist_guess`` and never set
``submitted`` by hand — the handler must do it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import (
    ARTIST_POINTS,
    DOMAIN,
    TITLE_POINTS,
)
from custom_components.beatify.game.state import GamePhase
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
    return svc


def _make_handler_game():
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
    )
    # After create_game, which nulls _media_player_service for a fresh game (#1526).
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"  # skip the verify_responsive branch
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
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


class TestTitleArtistGuessMarksSubmitted:
    async def test_exact_guess_marks_submitted_and_scores_full_points(self):
        """A correct title+artist guess via the real handler must:

        - set ``player.submitted is True`` (handler responsibility, not test),
        - set ``player.has_title_artist_guess is True``,
        - make ``check_all_guesses_complete()`` true once the only player has
          guessed (early-reveal precondition), and
        - bank the full title+artist points (NOT 0) when the round is scored
          via the same entry point the game uses (``_score_all_players``).
        """
        handler, gs = _make_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.players["Alice"].connected = True
        await gs.start_round()
        assert gs.phase == GamePhase.PLAYING

        truth_title = gs.current_song["title"]
        truth_artist = gs.current_song["artist"]

        # Drive the real handler with an exact-correct title + artist.
        await handler._handle_message(
            ws,
            {
                "type": "title_artist_guess",
                "title": truth_title,
                "artist": truth_artist,
            },
        )

        player = gs.players["Alice"]
        assert player.has_title_artist_guess is True
        # The bug: the handler never set these, so scoring + early reveal break.
        assert player.submitted is True
        assert player.submission_time is not None

        # Early-reveal precondition: the only active player has guessed.
        assert gs.check_all_guesses_complete() is True
        assert gs.all_submitted() is True

        # Score the round via the same loop the game uses.
        gs._score_all_players(None, list(gs.players.values()))
        assert player.round_score == TITLE_POINTS + ARTIST_POINTS
        assert player.round_score != 0

        gs._cancel_auto_advance()

    async def test_two_players_complete_triggers_all_submitted(self):
        """Early reveal needs *every* active player marked submitted."""
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = _ws(), _ws()
        gs.add_player("Alice", alice_ws)
        gs.add_player("Bob", bob_ws)
        for p in gs.players.values():
            p.connected = True
        await gs.start_round()

        truth_title = gs.current_song["title"]
        truth_artist = gs.current_song["artist"]

        await handler._handle_message(
            alice_ws,
            {
                "type": "title_artist_guess",
                "title": truth_title,
                "artist": truth_artist,
            },
        )
        # Only one of two players has guessed yet.
        assert gs.check_all_guesses_complete() is False

        await handler._handle_message(
            bob_ws,
            {
                "type": "title_artist_guess",
                "title": truth_title,
                "artist": truth_artist,
            },
        )
        assert gs.players["Alice"].submitted is True
        assert gs.players["Bob"].submitted is True
        assert gs.check_all_guesses_complete() is True

        gs._cancel_auto_advance()
