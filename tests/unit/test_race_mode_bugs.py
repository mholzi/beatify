"""Regression tests for the Race-mode bug batch (idle-halt banner, duplicate
players on the leaderboard).

Covers:
  * Bug 1 — the REVEAL "Game idle — nobody played" banner (``idle_halt``) fired
    every round in Race mode because players are never marked ``submitted``.
    ``round_had_engagement`` / the serializer must read the live race feed
    instead.
  * Bug 2 root — a name resubmitted in a different Unicode normalization form
    (iOS NFD vs NFC) spawned a duplicate player session, so the same visible
    name appeared multiple times on the dashboard leaderboard.
"""

from __future__ import annotations

import unicodedata
from unittest.mock import MagicMock

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _race_game():
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        title_artist_race_mode=True,
    )
    return gs


def _ws(closed: bool = False):
    m = MagicMock()
    m.closed = closed
    return m


# ---------------------------------------------------------------------------
# Bug 1 — idle-halt must respect race engagement, not p.submitted
# ---------------------------------------------------------------------------


class TestIdleHaltRaceEngagement:
    def test_round_had_engagement_false_before_any_guess(self):
        gs = _race_game()
        gs.phase = GamePhase.PLAYING
        gs.current_song = {"title": "Stronger", "artist": "Kanye West"}
        gs._challenge_manager.init_round(gs.current_song)
        assert gs.round_had_engagement() is False

    def test_round_had_engagement_true_after_race_guess(self):
        gs = _race_game()
        gs.phase = GamePhase.PLAYING
        gs.current_song = {"title": "Stronger", "artist": "Kanye West"}
        gs._challenge_manager.init_round(gs.current_song)
        # A guess lands on the live feed even though nobody is "submitted".
        gs.submit_race_guess("Schlieri", "Stronger", "", 1.0)
        assert not any(p.submitted for p in gs.players.values())
        assert gs.round_had_engagement() is True

    def test_serializer_no_idle_halt_when_race_was_played(self):
        gs = _race_game()
        gs.add_player("Schlieri", _ws())
        gs.phase = GamePhase.PLAYING
        gs.current_song = {"title": "Stronger", "artist": "Kanye West"}
        gs._challenge_manager.init_round(gs.current_song)
        gs.submit_race_guess("Schlieri", "Stronger", "Kanye West", 1.0)
        gs.phase = GamePhase.REVEAL
        state = GameStateSerializer.serialize(gs)
        # The banner must NOT show — the room raced this round.
        assert state.get("idle_halt") is not True

    def test_serializer_idle_halt_when_nobody_raced(self):
        gs = _race_game()
        gs.add_player("Schlieri", _ws())
        gs.phase = GamePhase.PLAYING
        gs.current_song = {"title": "Stronger", "artist": "Kanye West"}
        gs._challenge_manager.init_round(gs.current_song)
        # No guesses at all → genuinely idle.
        gs.phase = GamePhase.REVEAL
        state = GameStateSerializer.serialize(gs)
        assert state.get("idle_halt") is True


# ---------------------------------------------------------------------------
# Bug 2 root — Unicode normalization must not spawn duplicate sessions
# ---------------------------------------------------------------------------


class TestNameNormalizationDedup:
    def test_nfc_and_nfd_resolve_to_one_player(self):
        nfc = unicodedata.normalize("NFC", "Joäni")  # ä = U+00E4
        nfd = unicodedata.normalize("NFD", "Joäni")  # a + U+0308
        assert nfc != nfd  # byte-distinct on the wire

        gs = make_game_state()
        gs.phase = GamePhase.LOBBY
        ok1, _ = gs.add_player(nfc, _ws())
        # Second join arrives in the other form while the first is disconnected.
        gs.get_player(nfc).connected = False
        ok2, _ = gs.add_player(nfd, _ws())
        assert ok1 is True
        assert ok2 is True  # reconnect, not a fresh (rejected) join

        # Exactly one session, one leaderboard row.
        assert len(gs.players) == 1
        lb = gs.get_leaderboard()
        assert len(lb) == 1

    def test_lookup_matches_across_forms(self):
        nfc = unicodedata.normalize("NFC", "Müller")
        nfd = unicodedata.normalize("NFD", "Müller")
        gs = make_game_state()
        gs.phase = GamePhase.LOBBY
        gs.add_player(nfc, _ws())
        # get_player must find the same session regardless of the query's form.
        assert gs.get_player(nfd) is not None
        assert gs.get_player(nfc) is gs.get_player(nfd)

    def test_stored_name_is_nfc(self):
        nfd = unicodedata.normalize("NFD", "Joäni")
        gs = make_game_state()
        gs.phase = GamePhase.LOBBY
        gs.add_player(nfd, _ws())
        stored = next(iter(gs.players.values())).name
        assert stored == unicodedata.normalize("NFC", stored)

    def test_leaderboard_has_no_duplicate_names_after_reconnects(self):
        """End-to-end: two players, each rejoining in a mixed Unicode form,
        yield a leaderboard with each name exactly once."""
        gs = make_game_state()
        gs.phase = GamePhase.LOBBY
        for name in ("Joäni", "Schlieri"):
            gs.add_player(unicodedata.normalize("NFC", name), _ws())
        # Simulate several rejoins alternating normalization forms.
        for _ in range(3):
            for name in ("Joäni", "Schlieri"):
                p = gs.get_player(name)
                p.connected = False
                form = "NFD" if _ % 2 else "NFC"
                gs.add_player(unicodedata.normalize(form, name), _ws())

        names = [e["name"] for e in gs.get_leaderboard()]
        assert len(names) == len(set(names)) == 2


# ---------------------------------------------------------------------------
# #3557: the REVEAL announcement in a race. Nobody is marked submitted, so the
# one-shot rules ("name everyone who got both") would never say anything.
# ---------------------------------------------------------------------------


def _race_tts_state(*, title_winner=None, artist_winner=None, feed=None):
    from unittest.mock import AsyncMock

    from custom_components.beatify.game.challenges import TitleArtistChallenge
    from custom_components.beatify.game.player import PlayerSession

    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.title_artist_mode = True
    state.title_artist_challenge = TitleArtistChallenge(
        correct_title="Take On Me",
        correct_artist="a-ha",
        race_mode=True,
        title_winner=title_winner,
        artist_winner=artist_winner,
        feed=list(feed or []),
    )
    state.players = {"Marco": PlayerSession(name="Marco", ws=None)}
    return state


def _spoken(state):
    if not state._tts_announce.await_args_list:
        return None
    return state._tts_announce.await_args.args[0]


class TestRaceRevealAnnouncement:
    async def test_names_a_player_who_won_both_fields(self):
        state = _race_tts_state(title_winner="Marco", artist_winner="Marco")
        await state._announce_reveal(1985)
        spoken = _spoken(state)
        assert spoken.startswith("The answer was Take On Me by a-ha.")
        assert "Marco" in spoken

    async def test_nobody_line_when_the_room_guessed_but_nothing_fell(self):
        state = _race_tts_state(
            feed=[{"player": "Marco", "field": "title", "guess": "x", "correct": False}]
        )
        await state._announce_reveal(1985)
        assert "Nobody got it" in _spoken(state)

    async def test_no_nobody_line_when_one_field_was_won(self):
        state = _race_tts_state(title_winner="Marco", feed=[{"correct": True}])
        await state._announce_reveal(1985)
        assert "Nobody got it" not in _spoken(state)
