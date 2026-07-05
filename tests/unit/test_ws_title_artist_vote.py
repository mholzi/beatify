"""Tests for title/artist vote + override WS handlers (P4, #1180)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_INVALID_ACTION, ERR_NOT_ADMIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _ta_songs(n: int = 3) -> list[dict]:
    songs = make_songs(n)
    for i, s in enumerate(songs):
        s["title"] = f"Real Title {i}"
        s["artist"] = f"Real Artist {i}"
    return songs


def _stub_media_service() -> MagicMock:
    """A fake MediaPlayerService that reports a healthy, playing speaker.

    Injected so _ensure_media_player_service skips constructing a real
    (hass-less) service — tests stub the dependency instead of branching
    production code on a None hass.
    """
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
    # Inject a truthy stub service so the lazy _ensure_media_player_service is a
    # no-op and real (hass-less) playback never runs during start_round. Must be
    # after create_game, which nulls _media_player_service for a fresh game (#1526).
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


async def _setup_reveal_with_near_miss(handler, gs):
    """Drive to REVEAL with an open vote window: Alice title near-miss."""
    alice_ws, bob_ws = _ws(), _ws()
    gs.add_player("Alice", alice_ws)
    gs.add_player("Bob", bob_ws)
    for p in gs.players.values():
        p.connected = True
    gs.set_admin("Bob")
    await gs.start_round()
    gs._challenge_manager.submit_title_artist_guess(
        "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
    )
    gs._challenge_manager.submit_title_artist_guess(
        "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
    )
    for p in gs.players.values():
        p.submitted = True
    await gs.end_round()
    return alice_ws, bob_ws


class TestVoteHandler:
    async def test_vote_recorded(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        assert gs.phase == GamePhase.REVEAL
        await handler._handle_message(
            bob_ws,
            {"type": "title_artist_vote", "nearmiss_id": "Alice:title", "accept": True},
        )
        assert gs.get_near_misses()[0]["votes_yes"] == 1
        # #1763: vote tallies are coalesced through the debounced broadcast.
        handler.debounced_broadcast_state.assert_awaited()
        gs._cancel_auto_advance()

    async def test_self_vote_rejected(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        await handler._handle_message(
            alice_ws,  # Alice owns Alice:title -> self-vote
            {"type": "title_artist_vote", "nearmiss_id": "Alice:title", "accept": True},
        )
        assert gs.get_near_misses()[0]["votes_yes"] == 0
        sent = [c.args[0] for c in alice_ws.send_json.await_args_list]
        assert any(m.get("code") == ERR_INVALID_ACTION for m in sent)
        gs._cancel_auto_advance()

    async def test_vote_rejected_outside_reveal(self):
        handler, gs = _make_handler_game()
        bob_ws = _ws()
        gs.add_player("Bob", bob_ws)
        gs.get_player("Bob").connected = True
        # phase is LOBBY
        await handler._handle_message(
            bob_ws,
            {"type": "title_artist_vote", "nearmiss_id": "Alice:title", "accept": True},
        )
        sent = [c.args[0] for c in bob_ws.send_json.await_args_list]
        assert any(m.get("code") == ERR_INVALID_ACTION for m in sent)

    async def test_vote_rejected_for_unknown_nearmiss_id(self):
        # #1180: a fabricated nearmiss_id must not create a votes entry — this
        # is the DoS guard against flooding the dict with arbitrary ids.
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        ta = gs._challenge_manager.title_artist_challenge
        await handler._handle_message(
            bob_ws,
            {
                "type": "title_artist_vote",
                "nearmiss_id": "Ghost:title",  # no such near-miss
                "accept": True,
            },
        )
        assert "Ghost:title" not in ta.votes
        sent = [c.args[0] for c in bob_ws.send_json.await_args_list]
        assert any(m.get("code") == ERR_INVALID_ACTION for m in sent)
        gs._cancel_auto_advance()


class TestOverrideHandler:
    async def test_override_recorded_by_admin(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        await handler._handle_message(
            bob_ws,  # Bob is admin
            {
                "type": "title_artist_override",
                "nearmiss_id": "Alice:title",
                "accept": True,
            },
        )
        assert (
            gs._challenge_manager.title_artist_challenge.overrides["Alice:title"]
            is True
        )
        # #1763: override updates are coalesced through the debounced broadcast.
        handler.debounced_broadcast_state.assert_awaited()
        gs._cancel_auto_advance()

    async def test_override_rejected_for_non_admin(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        await handler._handle_message(
            alice_ws,  # Alice is not admin
            {
                "type": "title_artist_override",
                "nearmiss_id": "Alice:title",
                "accept": True,
            },
        )
        assert (
            "Alice:title" not in gs._challenge_manager.title_artist_challenge.overrides
        )
        sent = [c.args[0] for c in alice_ws.send_json.await_args_list]
        assert any(m.get("code") == ERR_NOT_ADMIN for m in sent)
        gs._cancel_auto_advance()

    async def test_override_rejected_for_unknown_nearmiss_id(self):
        # #1180: admin overrides are allowlisted to real near-misses too, so a
        # fabricated id can't grow the overrides dict.
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        ta = gs._challenge_manager.title_artist_challenge
        await handler._handle_message(
            bob_ws,  # Bob is admin
            {
                "type": "title_artist_override",
                "nearmiss_id": "Ghost:title",  # no such near-miss
                "accept": True,
            },
        )
        assert "Ghost:title" not in ta.overrides
        sent = [c.args[0] for c in bob_ws.send_json.await_args_list]
        assert any(m.get("code") == ERR_INVALID_ACTION for m in sent)
        gs._cancel_auto_advance()


class TestHostAdvanceResolves:
    async def test_next_round_resolves_window_first(self):
        handler, gs = _make_handler_game()
        alice_ws, bob_ws = await _setup_reveal_with_near_miss(handler, gs)
        # Capture the round's open challenge before advancing — admin_next_round
        # replaces it with a fresh challenge for the next round.
        ta = gs._challenge_manager.title_artist_challenge
        assert ta is not None and ta.resolved is False
        # Host accepts Alice's title, then advances.
        gs.set_title_artist_override("Alice:title", True)
        await handler._handle_message(bob_ws, {"type": "admin", "action": "next_round"})
        # The challenge from the (now finished) round was resolved before advance
        # (host override applied + rescored), and the vote window is closed.
        assert gs.is_title_artist_voting_open() is False
        assert ta.resolved is True
        # Alice's accepted near-miss banked partial title (5) + exact artist (5).
        assert gs.get_player("Alice").score == 10
