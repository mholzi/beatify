"""#2646 — the host drops a bad song without scoring the round.

Round 5, the song is a cover version, or Music Assistant plays twenty seconds
of silence. The host taps Next and the game *scores* the round: everyone who
had not answered counts as having missed, every streak resets, and in Sudden
Death somebody is eliminated because a non-submitter counts as the slowest
player of all. There was no way out of PLAYING that did not score.

These tests cover the second exit (``void_round``) and the numbers the host's
card shows before they decide (``preview_round_end``). Behaviour, not wording:
the assertions are about scores, streaks, eliminations, phase and the recorded
report, so a re-worded card or a moved DOM node does not touch them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


def _add_live_player(gs, name: str) -> None:
    ws = MagicMock()
    ws.closed = False
    gs.add_player(name, ws)
    gs.get_player(name).connected = True


async def _start_game(gs, names, *, sudden_death=False, rounds=4):
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(rounds),
        media_player="media_player.x",
        base_url="http://h",
        sudden_death_mode=sudden_death,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for name in names:
        _add_live_player(gs, name)
    await gs.start_round()


# ---------------------------------------------------------------------------
# The round is not scored
# ---------------------------------------------------------------------------


class TestVoidRoundScoresNobody:
    async def test_scores_and_streaks_survive_a_voided_round(self):
        """Nobody gains, nobody loses — including the players who answered.

        The failure this replaces: ``end_round`` marks every non-submitter as
        having missed and resets their streak (``game/scoring.py``). Alice has
        a live 4-streak and has not answered; before #2646 the host's tap took
        it away.
        """
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        alice, bob = gs.get_player("Alice"), gs.get_player("Bob")
        alice.streak, alice.score = 4, 40
        bob.streak, bob.score = 2, 25
        # Bob answered, Alice did not — the exact split the issue describes.
        bob.submit_guess(1999, 3.0)

        assert await gs.void_round("cover") is True

        assert (alice.score, alice.streak) == (40, 4)
        assert (bob.score, bob.streak) == (25, 2)
        # The guess itself is gone: no half-credit for a song whose data is
        # the thing in doubt.
        assert bob.submitted is False
        assert bob.current_guess is None
        assert bob.round_score == 0

    async def test_a_held_streak_shield_is_not_spent(self):
        """#1666's shield is a per-game token; a voided round must not eat it."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        alice = gs.get_player("Alice")
        alice.streak, alice.streak_shield = 3, True

        await gs.void_round(None)

        assert alice.streak_shield is True
        assert alice.streak == 3

    async def test_end_round_still_scores_the_same_setup(self):
        """The control: the normal exit does everything the void one does not.

        Without this the two tests above could pass because the fixture never
        put a streak at risk in the first place.
        """
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        alice = gs.get_player("Alice")
        alice.streak = 4

        await gs.end_round()

        assert alice.streak == 0


# ---------------------------------------------------------------------------
# Nobody is eliminated
# ---------------------------------------------------------------------------


class TestVoidRoundEliminatesNobody:
    async def _sudden_death_round_two(self):
        """Three players in Sudden Death, round 2, with Carol not answering."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"], sudden_death=True)
        await gs.end_round()  # round 1 never eliminates
        await gs.start_round()
        assert gs.round == 2
        gs.get_player("Alice").submit_guess(1980, 1.0)
        gs.get_player("Bob").submit_guess(1981, 2.0)
        return gs

    async def test_voiding_eliminates_nobody(self):
        gs = await self._sudden_death_round_two()

        await gs.void_round("silence")

        assert [p.name for p in gs.players.values() if p.eliminated] == []

    async def test_scoring_the_same_round_eliminates_the_non_submitter(self):
        """The control, and the bug in one line: Carol is out for a bad song."""
        gs = await self._sudden_death_round_two()

        await gs.end_round()

        assert [p.name for p in gs.players.values() if p.eliminated] == ["Carol"]


# ---------------------------------------------------------------------------
# Phase, round bookkeeping and the recorded report
# ---------------------------------------------------------------------------


class TestVoidRoundBookkeeping:
    async def test_lands_on_reveal_and_flags_the_round(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])

        await gs.void_round("wrong_year")

        assert gs.phase == GamePhase.REVEAL
        assert gs.round_voided is True
        assert gs.void_reason == "wrong_year"

    async def test_the_flag_does_not_survive_into_the_next_round(self):
        """A stale flag would put "does not count" on a good round's reveal."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        await gs.void_round("cover")

        await gs.start_round()

        assert gs.round_voided is False
        assert gs.void_reason is None

    async def test_the_round_number_does_not_rewind(self):
        """A voided round costs its slot; round 6 follows a voided round 5.

        ``total_rounds`` is the size of the playable song pool (#2647), so
        there is no spare song to replay the round with, and rewinding would
        make ``last_round`` lie about where the game is.
        """
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        assert gs.round == 1

        await gs.void_round(None)
        await gs.start_round()

        assert gs.round == 2

    async def test_the_report_is_recorded_with_the_song(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        title = gs.current_song["title"]

        await gs.void_round("cover")

        assert len(gs.voided_rounds) == 1
        report = gs.voided_rounds[0]
        assert report["reason"] == "cover"
        assert report["round"] == 1
        assert report["title"] == title

    async def test_a_round_without_a_reason_is_still_recorded(self):
        """The chips are optional; skipping them must not skip the record."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])

        await gs.void_round(None)

        assert len(gs.voided_rounds) == 1
        assert gs.voided_rounds[0]["reason"] is None

    async def test_voiding_outside_playing_is_refused(self):
        """The timer may have fired and scored the round while the host read."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        await gs.end_round()

        assert await gs.void_round("cover") is False
        assert gs.round_voided is False
        assert gs.voided_rounds == []

    async def test_playback_is_stopped(self):
        """The thing coming out of the speaker is why the host reached for it."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])

        await gs.void_round("silence")

        gs._media_player_service.stop.assert_awaited()


# ---------------------------------------------------------------------------
# The consequence preview
# ---------------------------------------------------------------------------


class TestRoundEndPreview:
    async def test_counts_the_players_a_premature_end_would_punish(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"])
        gs.get_player("Alice").submit_guess(1980, 1.0)
        # Bob has a streak to lose, Carol does not.
        gs.get_player("Bob").streak = 3

        preview = gs.preview_round_end()

        assert preview["player_count"] == 3
        assert preview["submitted_count"] == 1
        assert preview["counting_wrong"] == 2
        assert preview["streaks_breaking"] == 1

    async def test_a_shielded_streak_is_not_counted_as_breaking(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        bob = gs.get_player("Bob")
        bob.streak, bob.streak_shield = 3, True

        assert gs.preview_round_end()["streaks_breaking"] == 0

    async def test_names_the_player_sudden_death_would_cut(self):
        """The line whose absence is the whole issue: "Tom is eliminated".

        And it has to be the player the real elimination picks — so the test
        runs the real one afterwards and compares.
        """
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"], sudden_death=True)
        await gs.end_round()
        await gs.start_round()
        gs.get_player("Alice").submit_guess(1980, 1.0)
        gs.get_player("Bob").submit_guess(1981, 2.0)

        predicted = gs.preview_round_end()["eliminated"]
        await gs.end_round()

        assert predicted == "Carol"
        assert [p.name for p in gs.players.values() if p.eliminated] == [predicted]

    async def test_says_nobody_when_sudden_death_is_off(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"])

        preview = gs.preview_round_end()

        assert preview["eliminated"] is None
        assert preview["elimination_possible"] is False

    async def test_says_nobody_in_round_one(self):
        """Round 1 never eliminates, so the card must not threaten that it will."""
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"], sudden_death=True)

        preview = gs.preview_round_end()

        assert preview["eliminated"] is None
        assert preview["elimination_possible"] is False

    async def test_names_nobody_once_everybody_has_answered(self):
        """Then it really does depend on the scoring pass — say so, honestly.

        ``elimination_possible`` stays True, so the card falls back to "in
        Sudden Death somebody is eliminated" instead of inventing a name.
        """
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob", "Carol"], sudden_death=True)
        await gs.end_round()
        await gs.start_round()
        for i, name in enumerate(["Alice", "Bob", "Carol"]):
            gs.get_player(name).submit_guess(1980, float(i + 1))

        preview = gs.preview_round_end()

        assert preview["eliminated"] is None
        assert preview["elimination_possible"] is True


# ---------------------------------------------------------------------------
# What reaches the screens
# ---------------------------------------------------------------------------


class TestVoidRoundSerialization:
    async def test_reveal_payload_carries_the_flag(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        await gs.void_round("cover")

        state = gs.get_state()

        assert state["round_voided"] is True
        assert state["void_reason"] == "cover"

    async def test_playing_payload_carries_the_preview(self):
        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])

        state = gs.get_state()

        assert state["admin_round_end_preview"]["counting_wrong"] == 2

    async def test_the_preview_never_reaches_a_player_socket(self):
        """ "Tom is eliminated" on Tom's phone would be worse than useless."""
        from custom_components.beatify.server.serializers import (
            redact_state_for_player,
        )

        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        message = dict(gs.get_state(), type="state")

        redacted = redact_state_for_player(message)

        assert "admin_round_end_preview" not in redacted
        assert "void_reason" not in redacted

    async def test_a_guest_is_told_the_round_does_not_count(self):
        """They answered and got no points — without this it reads as a bug."""
        from custom_components.beatify.server.serializers import (
            redact_state_for_player,
        )

        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        await gs.void_round("cover")
        message = dict(gs.get_state(), type="state")

        assert redact_state_for_player(message)["round_voided"] is True


# ---------------------------------------------------------------------------
# The WebSocket action
# ---------------------------------------------------------------------------


class TestVoidRoundAction:
    def _admin_ws(self):
        ws = MagicMock()
        ws.closed = False
        ws.send_json = AsyncMock()
        return ws

    async def _handler_for(self, gs, ws):
        from custom_components.beatify.const import DOMAIN
        from custom_components.beatify.server.websocket import (
            BeatifyWebSocketHandler,
        )

        hass = MagicMock()
        hass.data = {DOMAIN: {"game": gs}}
        handler = BeatifyWebSocketHandler(hass)
        handler.admin_ws = ws
        handler.broadcast_state = AsyncMock()
        handler.broadcast = AsyncMock()
        handler.debounced_broadcast_state = AsyncMock()
        return handler

    async def test_the_action_voids_the_round(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        ws = self._admin_ws()
        handler = await self._handler_for(gs, ws)

        await handle_admin(
            handler, ws, {"action": "void_round", "reason": "silence"}, gs
        )

        assert gs.phase == GamePhase.REVEAL
        assert gs.round_voided is True
        assert gs.void_reason == "silence"

    async def test_an_unknown_reason_is_dropped_not_refused(self):
        """Failing the drop over a decoration would leave the bad song playing."""
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        ws = self._admin_ws()
        handler = await self._handler_for(gs, ws)

        await handle_admin(
            handler, ws, {"action": "void_round", "reason": "sabotage"}, gs
        )

        assert gs.round_voided is True
        assert gs.void_reason is None

    async def test_the_action_is_refused_outside_playing(self):
        from custom_components.beatify.server.ws_handlers.admin import handle_admin

        gs = make_game_state()
        await _start_game(gs, ["Alice", "Bob"])
        await gs.end_round()
        ws = self._admin_ws()
        handler = await self._handler_for(gs, ws)

        await handle_admin(handler, ws, {"action": "void_round"}, gs)

        sent = [c.args[0] for c in ws.send_json.await_args_list]
        assert any(msg.get("type") == "error" for msg in sent)
        assert gs.round_voided is False
