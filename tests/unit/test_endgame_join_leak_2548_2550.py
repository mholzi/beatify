"""#2548, #2549 and #2550 — three end-of-game / join-time mismatches.

* #2548: the speaker crowned the highest scorer while the screen crowned the
  sudden-death survivor.
* #2549: the join screen turned guests away during PAUSED, although
  ``add_player`` would have accepted them.
* #2550: an active artist challenge shipped the answer to every player socket.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import (
    REDACTED_PLACEHOLDER,
    build_game_status_response,
    redact_state_for_player,
)
from tests.conftest import make_game_state, make_songs


def _make_game(names, *, songs=5, **create_kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        **create_kwargs,
    )
    for n in names:
        ws = MagicMock()
        ws.closed = False
        gs.add_player(n, ws)
        gs.get_player(n).connected = True
    return gs


# ---------------------------------------------------------------------------
# #2548 — the speaker must agree with the screen
# ---------------------------------------------------------------------------


def _tts_game():
    gs = _make_game(["Alice", "Bob"])
    gs._tts_service = "tts.google"
    gs._tts_announce_winner = True
    gs._tts_announce_podium = True
    gs._tts_announce = AsyncMock()
    return gs


class TestSuddenDeathAnnouncements:
    async def test_winner_is_the_survivor_not_the_high_scorer(self):
        gs = _tts_game()
        gs.sudden_death_mode = True
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        alice.score = 120
        alice.eliminated = True
        alice.eliminated_round = 8
        bob.score = 95

        await gs.announce_winner()

        spoken = gs._tts_announce.await_args.args[0]
        assert "Bob" in spoken
        assert "Alice" not in spoken

    async def test_podium_follows_the_leaderboard_order(self):
        gs = _tts_game()
        gs.sudden_death_mode = True
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        alice.score = 120
        alice.eliminated = True
        alice.eliminated_round = 8
        bob.score = 95

        await gs.announce_podium()

        spoken = gs._tts_announce.await_args.args[0]
        # Bottom-up: 2nd is read first, 1st last.
        assert spoken.index("Bob") > spoken.index("Alice")

    async def test_normal_game_still_crowns_the_high_scorer(self):
        gs = _tts_game()
        gs.get_player("Alice").score = 120
        gs.get_player("Bob").score = 95

        await gs.announce_winner()

        assert "Alice" in gs._tts_announce.await_args.args[0]


# ---------------------------------------------------------------------------
# #2549 — a paused game still accepts joins
# ---------------------------------------------------------------------------


class TestJoinWhilePaused:
    def test_paused_can_join(self):
        gs = _make_game(["Alice"])
        gs.phase = GamePhase.PAUSED

        payload = build_game_status_response(gs, gs.game_id)

        assert payload["can_join"] is True

    def test_ended_still_cannot_join(self):
        gs = _make_game(["Alice"])
        gs.phase = GamePhase.END

        payload = build_game_status_response(gs, gs.game_id)

        assert payload["can_join"] is False


# ---------------------------------------------------------------------------
# #2550 — the artist challenge answer must not reach players
# ---------------------------------------------------------------------------


class TestArtistChallengeRedaction:
    def test_artist_is_redacted_during_the_challenge(self):
        message = {
            "type": "state",
            "phase": "PLAYING",
            "artist_challenge": {"options": ["Queen", "Abba"]},
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody", "album_art": "x"},
        }

        out = redact_state_for_player(message)

        assert out["song"]["artist"] == REDACTED_PLACEHOLDER
        assert out["song"]["title"] == "Bohemian Rhapsody"
        assert out["song"]["album_art"] == "x"
        assert message["song"]["artist"] == "Queen", "input must not be mutated"

    def test_reveal_is_untouched(self):
        message = {
            "type": "state",
            "phase": "REVEAL",
            "artist_challenge": {"options": ["Queen"]},
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody"},
        }

        assert redact_state_for_player(message)["song"]["artist"] == "Queen"

    def test_no_challenge_leaves_the_artist_alone(self):
        message = {
            "type": "state",
            "phase": "PLAYING",
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody"},
        }

        assert redact_state_for_player(message)["song"]["artist"] == "Queen"

    def test_title_artist_mode_still_redacts_both(self):
        message = {
            "type": "state",
            "phase": "PLAYING",
            "title_artist_mode": True,
            "artist_challenge": {"options": ["Queen"]},
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody"},
        }

        out = redact_state_for_player(message)

        assert out["song"]["artist"] == REDACTED_PLACEHOLDER
        assert out["song"]["title"] == REDACTED_PLACEHOLDER
