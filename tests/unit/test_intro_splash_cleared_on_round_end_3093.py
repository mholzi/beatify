"""#3093 - a pending intro splash must not leak into the REVEAL phase.

``end_round`` cancelled the intro timer but left ``_intro_splash_pending`` set,
so when the host skipped an intro round before confirming its splash, every
REVEAL frame still carried ``intro_splash_pending: true`` (and a pause taken
there could hand the round back to ``confirm_intro_splash`` on resume).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state

SONG = {"year": 1984, "title": "Two Hearts", "artist": "Phil Collins"}


def _intro_round_with_pending_splash():
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.add_player("Host", MagicMock())
    state.set_admin("Host")
    state.phase = GamePhase.PLAYING
    state.current_song = dict(SONG)
    rm = state._round_manager
    rm.is_intro_round = True
    rm._intro_splash_pending = True
    rm._intro_splash_deferred_song = dict(SONG)
    return state


async def test_end_round_clears_pending_splash():
    state = _intro_round_with_pending_splash()
    assert state.get_state()["intro_splash_pending"] is True

    await state.end_round()

    assert state.phase == GamePhase.REVEAL
    assert state.intro_splash_pending is False
    assert state.get_state()["intro_splash_pending"] is False
    assert state._round_manager._intro_splash_deferred_song is None


async def test_pending_splash_survives_until_the_round_ends():
    """Pausing during PLAYING keeps the splash so resume can bring it back."""
    state = _intro_round_with_pending_splash()

    await state.pause_game(reason="admin")

    assert state.phase == GamePhase.PAUSED
    assert state.intro_splash_pending is True
