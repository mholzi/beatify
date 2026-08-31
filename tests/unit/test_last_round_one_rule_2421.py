"""One rule decides whether a round is the last one (#2421).

Two rules used to answer that question. `last_round` counted what was left in
the pool (`get_remaining_count() <= 1`); the TTS announcement re-derived it
from `round >= total_rounds`. They agree in a clean game and part ways as soon
as a song is dropped: the playback-failure path marks a song played **without
committing a round**, so `round` falls behind `total_rounds` while the
remaining count keeps pace with reality.

Measured before the fix, on a five-song game with one song dropped after round
one: round 4 really was the last, the flag said so — and the spoken cue never
came. It failed in the quietest possible direction. Nothing looked wrong; a
cue was simply missing, and only in games where a song happened to be
unavailable.

The `total_rounds > 1` guard moved onto the flag, so a one-song game now stays
quiet on the banner as well, not only on the speaker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _make_game(songs: int = 5):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    ws = MagicMock()
    ws.closed = False
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True
    return gs


def _drop_one_song(gs) -> None:
    """Simulate the playback-failure path: a song is marked played, no round."""
    pm = gs._playlist_manager
    unplayed = [s for s in pm._songs if s["_precomputed_uri"] not in pm._played_uris]
    pm.mark_played(unplayed[0]["_precomputed_uri"])


async def _play(gs, *, drop_after: int | None = None) -> list[tuple[int, bool]]:
    """Run the game out; return (round number, flag) for each round played."""
    seen: list[tuple[int, bool]] = []
    while await gs.start_round():
        seen.append((gs.round, gs.last_round))
        if drop_after is not None and len(seen) == drop_after:
            _drop_one_song(gs)
        if len(seen) > 50:  # pragma: no cover — runaway guard
            raise AssertionError("game never ended")
    return seen


class TestTheFlagFollowsTheGame:
    @pytest.mark.asyncio
    async def test_clean_game_flags_only_the_final_round(self):
        gs = _make_game(5)
        assert await _play(gs) == [
            (1, False),
            (2, False),
            (3, False),
            (4, False),
            (5, True),
        ]

    @pytest.mark.asyncio
    async def test_a_dropped_song_moves_the_last_round_forward(self):
        # The case that exposed the second rule. Five songs, one dropped after
        # round 1 → the game really ends after four rounds, and round 4 is the
        # one to announce.
        gs = _make_game(5)
        seen = await _play(gs, drop_after=1)
        assert seen == [(1, False), (2, False), (3, False), (4, True)]

    @pytest.mark.asyncio
    async def test_the_old_rule_would_have_missed_it(self):
        # `round >= total_rounds` — the condition the announcement used to
        # re-derive — is false on every round of that game. Kept as a test so
        # the reason for the change cannot quietly stop being true.
        gs = _make_game(5)
        seen = await _play(gs, drop_after=1)
        assert gs.total_rounds == 5
        assert all(rnd < gs.total_rounds for rnd, _ in seen)
        assert any(flag for _, flag in seen)

    @pytest.mark.asyncio
    async def test_a_one_song_game_stays_quiet(self):
        # The guard moved from the announcement onto the flag, so the banner
        # follows the same judgement the speaker always did.
        gs = _make_game(1)
        assert await _play(gs) == [(1, False)]


class TestTheAnnouncementAndTheFlagAgree:
    @pytest.mark.asyncio
    async def test_the_cue_fires_exactly_on_the_flagged_round(self):
        gs = _make_game(5)
        fired: list[int] = []

        async def _record():
            fired.append(gs.round)

        gs.announce_last_round = _record  # type: ignore[method-assign]
        seen = await _play(gs, drop_after=1)

        flagged = [rnd for rnd, flag in seen if flag]
        assert fired == flagged == [4]

    @pytest.mark.asyncio
    async def test_the_cue_stays_silent_in_a_one_song_game(self):
        gs = _make_game(1)
        fired: list[int] = []

        async def _record():
            fired.append(gs.round)

        gs.announce_last_round = _record  # type: ignore[method-assign]
        await _play(gs)
        assert fired == []
