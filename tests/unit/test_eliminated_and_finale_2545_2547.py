"""#2545 and #2547 — two ways an eliminated player stalled the endgame.

* #2545: the early-reveal follow-up checks waited for eliminated players, who
  are refused by the guess handlers and can never satisfy them.
* #2547: with a round cap the playable pool is sampled down to exactly
  ``max_rounds``, so the finale tiebreaker's "unplayed songs remain" guard was
  never true in the actual last round.
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


def _make_game(names, *, songs=5, **create_kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        **create_kwargs,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for n in names:
        ws = MagicMock()
        ws.closed = False
        gs.add_player(n, ws)
        gs.get_player(n).connected = True
    return gs


# ---------------------------------------------------------------------------
# #2545 — eliminated players must not hold the early reveal open
# ---------------------------------------------------------------------------


class TestEliminatedDoNotBlockEarlyReveal:
    def test_title_artist_mode_ignores_the_eliminated(self):
        gs = _make_game(["Alice", "Bob"])
        gs.title_artist_mode = True
        gs.title_artist_challenge = MagicMock()

        for p in gs.players.values():
            p.submitted = True
        gs.get_player("Alice").has_title_artist_guess = True
        bob = gs.get_player("Bob")
        bob.has_title_artist_guess = False
        bob.eliminated = True

        assert gs.check_all_guesses_complete() is True

    def test_an_active_player_still_holds_it_open(self):
        gs = _make_game(["Alice", "Bob"])
        gs.title_artist_mode = True
        gs.title_artist_challenge = MagicMock()

        for p in gs.players.values():
            p.submitted = True
        gs.get_player("Alice").has_title_artist_guess = True
        gs.get_player("Bob").has_title_artist_guess = False

        assert gs.check_all_guesses_complete() is False

    def test_artist_challenge_ignores_the_eliminated(self):
        gs = _make_game(["Alice", "Bob"])
        gs.artist_challenge_enabled = True
        gs.artist_challenge = MagicMock(winner=None)

        for p in gs.players.values():
            p.submitted = True
        gs.get_player("Alice").has_artist_guess = True
        bob = gs.get_player("Bob")
        bob.has_artist_guess = False
        bob.eliminated = True

        assert gs.check_all_guesses_complete() is True

    def test_movie_quiz_ignores_the_eliminated(self):
        gs = _make_game(["Alice", "Bob"])
        gs.movie_quiz_enabled = True
        gs.movie_challenge = MagicMock(correct_guesses=[])

        for p in gs.players.values():
            p.submitted = True
        gs.get_player("Alice").has_movie_guess = True
        bob = gs.get_player("Bob")
        bob.has_movie_guess = False
        bob.eliminated = True

        assert gs.check_all_guesses_complete() is True


# ---------------------------------------------------------------------------
# #2547 — the round cap must not lock the finale tiebreaker out
# ---------------------------------------------------------------------------


class TestCappedPoolKeepsAPlayoffReserve:
    def test_capped_songs_are_held_in_reserve(self):
        gs = _make_game(["Alice"], songs=50, max_rounds=10)
        pm = gs._playlist_manager
        assert pm.get_total_count() == 10
        assert len(pm._reserve_songs) == 40

    def test_release_puts_one_song_back_into_play(self):
        gs = _make_game(["Alice"], songs=50, max_rounds=10)
        pm = gs._playlist_manager
        before = pm.get_remaining_count()

        assert pm.reserve_songs_for_playoff(1) == 1
        assert pm.get_remaining_count() == before + 1
        assert len(pm._reserve_songs) == 39

    def test_release_is_a_noop_without_a_cap(self):
        gs = _make_game(["Alice"], songs=5)
        assert gs._playlist_manager.reserve_songs_for_playoff(1) == 0

    async def test_tie_in_the_last_capped_round_starts_a_playoff(self):
        # A capped game played to its last round: the pool is sampled down to
        # max_rounds, so every song in it has been played.
        gs = _make_game(["Alice", "Bob"], songs=50, max_rounds=10)
        gs.finale_tiebreaker_enabled = True
        await gs.start_round()
        pm = gs._playlist_manager
        for song in list(pm._songs):
            pm.mark_played(song["_precomputed_uri"])
        gs.phase = GamePhase.REVEAL
        gs.get_player("Alice").score = 10
        gs.get_player("Bob").score = 10
        assert gs.songs_remaining == 0

        assert await gs.maybe_start_finale_playoff() is True

    async def test_a_genuinely_exhausted_playlist_still_shares_the_win(self):
        gs = _make_game(["Alice", "Bob"], songs=1)
        gs.finale_tiebreaker_enabled = True
        await gs.start_round()
        gs.phase = GamePhase.REVEAL
        gs.get_player("Alice").score = 10
        gs.get_player("Bob").score = 10
        assert gs.songs_remaining == 0

        assert await gs.maybe_start_finale_playoff() is False
        assert gs.get_player("Alice").eliminated is False
