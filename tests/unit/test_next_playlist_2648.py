"""#2648 — "now the 90s!" without emptying the room.

After ten rounds of 80s somebody shouts for the next decade. Until this issue
the end screen had two answers and both were wrong: *Rematch* replayed the same
playlist, and *New Game* sent the host to the admin page and told every guest to
scan the QR code again — at the exact moment the party was at its best.

Variant B of the design gate makes the end screen the start screen: a grid of
playlists, and a rematch that may bring different music with it. What these
tests hold in place is the part that can silently rot:

1. **Which playlists get a tile** is a mechanical rule, not a judgement call —
   the one just played, then most recently played, then the catalogue. It lives
   in ``build_next_playlist_tiles`` so it can be read and tested as one rule.
2. **A swap changes the music and nothing else.** Players keep their seats and
   their names, and every setting the host configured carries over. That is the
   decision the PR states: a playlist swap is a content change, not a rules
   change.
3. **A swap that cannot be played changes nothing at all.** The check runs
   before anything is mutated, so a refused playlist leaves the finished game
   standing and the host still looking at the end screen.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    ERR_NO_PLAYABLE_SONGS,
    PROVIDER_APPLE_MUSIC,
)
from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.playlist import (
    build_next_playlist_tiles,
    playlist_rel_path,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.game.state_setup import NoPlayableSongsError
from custom_components.beatify.server.ws_handlers import admin_rematch_game
from tests.conftest import make_songs
from tests.unit.test_websocket import _make_handler_and_game, _make_ws

# ---------------------------------------------------------------------------
# 1. The rule behind the six tiles
# ---------------------------------------------------------------------------

PLAYLIST_DIR = Path("/config/beatify/playlists")


def meta(rel: str, name: str, song_count: int = 50) -> dict:
    """One discovery meta, as ``async_discover_playlists`` reports it."""
    return {
        "path": str(PLAYLIST_DIR / rel),
        "filename": Path(rel).name,
        "name": name,
        "song_count": song_count,
        "source": "bundled",
    }


CATALOGUE = [
    meta("apple.json", "Apple Anthems"),
    meta("community/disco.json", "Disco & Funk", 92),
    meta("eighties.json", "80s Hits", 120),
    meta("empty.json", "Broken Playlist", 0),
    meta("nineties.json", "90s Hits", 100),
    meta("zebra.json", "Zebra Party"),
]


class TestTheTilesAreAMechanicalRule:
    def test_the_playlist_just_played_comes_first_and_says_so(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE, PLAYLIST_DIR, ["eighties.json"], []
        )

        assert tiles[0]["paths"] == ["eighties.json"]
        assert tiles[0]["reason"] == "current"
        assert tiles[0]["name"] == "80s Hits"
        assert tiles[0]["song_count"] == 120

    def test_recently_played_follows_newest_first(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE,
            PLAYLIST_DIR,
            ["eighties.json"],
            ["nineties", "disco", "zebra"],
        )

        assert [t["paths"][0] for t in tiles[1:4]] == [
            "nineties.json",
            "community/disco.json",
            "zebra.json",
        ]
        assert {t["reason"] for t in tiles[1:4]} == {"recent"}

    def test_the_playlist_just_played_is_not_offered_twice(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE,
            PLAYLIST_DIR,
            ["eighties.json"],
            ["eighties", "nineties"],
        )

        paths = [t["paths"][0] for t in tiles]
        assert paths.count("eighties.json") == 1
        assert paths[1] == "nineties.json"

    def test_a_fresh_install_still_gets_a_full_grid(self):
        # No history at all — the third pass fills from the catalogue in its
        # own (path-sorted) order, so the host never faces two tiles and a
        # search box on their first party.
        tiles = build_next_playlist_tiles(CATALOGUE, PLAYLIST_DIR, [], [])

        assert len(tiles) == 5
        assert [t["reason"] for t in tiles] == ["catalog"] * 5
        assert [t["paths"][0] for t in tiles] == [
            "apple.json",
            "community/disco.json",
            "eighties.json",
            "nineties.json",
            "zebra.json",
        ]

    def test_a_playlist_with_nothing_in_it_is_never_offered(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE, PLAYLIST_DIR, [], ["empty", "nineties"]
        )

        assert "empty.json" not in [t["paths"][0] for t in tiles]
        assert tiles[0]["paths"] == ["nineties.json"]

    def test_a_multi_playlist_game_collapses_into_one_again_tile(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE,
            PLAYLIST_DIR,
            ["eighties.json", "community/disco.json"],
            [],
        )

        assert tiles[0]["paths"] == ["eighties.json", "community/disco.json"]
        assert tiles[0]["extra"] == 1
        assert tiles[0]["song_count"] == 212
        # …and neither half of it shows up again on its own.
        assert [t["paths"][0] for t in tiles[1:]].count("eighties.json") == 0

    def test_the_grid_stops_at_five_so_the_sixth_slot_stays_search(self):
        big = [meta(f"p{i}.json", f"Party {i}") for i in range(40)]
        assert len(build_next_playlist_tiles(big, PLAYLIST_DIR, [], [])) == 5

    def test_a_history_entry_with_no_playlist_left_on_disk_is_skipped(self):
        tiles = build_next_playlist_tiles(
            CATALOGUE, PLAYLIST_DIR, [], ["deleted-last-week", "nineties"]
        )
        assert tiles[0]["paths"] == ["nineties.json"]

    def test_rel_path_falls_back_to_the_filename_rather_than_raising(self):
        stray = {"path": "/somewhere/else/x.json", "filename": "x.json"}
        assert playlist_rel_path(PLAYLIST_DIR, stray) == "x.json"


# ---------------------------------------------------------------------------
# 2. The swap changes the music and nothing else
# ---------------------------------------------------------------------------


def _game_at_end(**create_kwargs):
    handler, game_state, ws = _make_handler_and_game(**create_kwargs)
    game_state.add_player("Markus", ws)
    game_state.set_admin("Markus")
    game_state.add_player("Ana", _make_ws())
    game_state.phase = GamePhase.END
    handler.cleanup_game_tasks = AsyncMock()
    game_state.announce_rematch = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    return handler, game_state, ws


def _nineties_songs(n: int = 4) -> list[dict]:
    return [
        {
            "year": 1990 + i,
            "title": f"90s Song {i}",
            "artist": f"90s Artist {i}",
            "uri": f"spotify:track:nineties{i:014d}",
            "_playlist_source": "nineties.json",
        }
        for i in range(n)
    ]


class TestTheSwapItself:
    def test_the_new_playlist_replaces_the_songs_and_the_selection(self):
        _handler, game_state, _ws = _game_at_end()
        assert game_state.playlists == ["test.json"]

        game_state.rematch_game(songs=_nineties_songs(), playlists=["nineties.json"])

        assert game_state.playlists == ["nineties.json"]
        assert [s["title"] for s in game_state.songs] == [
            "90s Song 0",
            "90s Song 1",
            "90s Song 2",
            "90s Song 3",
        ]
        # #1377: the round count comes off the playable pool, not the raw list.
        assert game_state.total_rounds == 4

    def test_every_guest_keeps_their_seat_and_their_name(self):
        _handler, game_state, _ws = _game_at_end()

        game_state.rematch_game(songs=_nineties_songs(), playlists=["nineties.json"])

        assert sorted(p.name for p in game_state.players.values()) == [
            "Ana",
            "Markus",
        ]
        assert game_state.phase == GamePhase.LOBBY
        assert all(p.score == 0 for p in game_state.players.values())

    def test_the_settings_the_host_chose_carry_over(self):
        # The decision this PR records: a playlist swap is a content change,
        # not a rules change. Every GameOptions field must read back unchanged.
        _handler, game_state, _ws = _game_at_end()
        game_state.sudden_death_mode = True
        game_state.closest_wins_mode = True
        game_state.max_rounds = 12
        before = GameOptions.capture(game_state)

        game_state.rematch_game(songs=_nineties_songs(20), playlists=["nineties.json"])

        assert GameOptions.capture(game_state) == before
        assert game_state.sudden_death_mode is True
        assert game_state.max_rounds == 12

    def test_the_speaker_and_the_language_come_along(self):
        _handler, game_state, _ws = _game_at_end()
        game_state.language = "de"

        game_state.rematch_game(songs=_nineties_songs(), playlists=["nineties.json"])

        assert game_state.media_player == "media_player.test"
        assert game_state.language == "de"

    def test_no_playlist_given_is_still_the_old_same_music_rematch(self):
        _handler, game_state, _ws = _game_at_end()
        titles_before = [s["title"] for s in game_state.songs]

        game_state.rematch_game()

        assert game_state.playlists == ["test.json"]
        assert [s["title"] for s in game_state.songs] == titles_before

    def test_a_playlist_the_provider_cannot_play_leaves_the_game_alone(self):
        # Apple Music selected, an Apple-Music-less playlist offered: the swap
        # must be refused BEFORE the rebuild, or the host loses the finished
        # game as well as the playlist they wanted.
        _handler, game_state, _ws = _game_at_end(
            options=GameOptions(provider=PROVIDER_APPLE_MUSIC),
            songs=[
                dict(s, uri_apple_music="applemusic://track/1") for s in make_songs(3)
            ],
        )
        game_id_before = game_state.game_id

        with pytest.raises(NoPlayableSongsError):
            game_state.rematch_game(
                songs=[{"year": 1994, "title": "No URI", "artist": "Nobody"}],
                playlists=["nineties.json"],
            )

        assert game_state.phase == GamePhase.END
        assert game_state.game_id == game_id_before
        assert game_state.playlists == ["test.json"]


# ---------------------------------------------------------------------------
# 3. The request that carries it
# ---------------------------------------------------------------------------


def _errors(ws) -> list[dict]:
    return [
        call.args[0]
        for call in ws.send_json.call_args_list
        if call.args and call.args[0].get("type") == "error"
    ]


class TestTheRematchMessage:
    async def test_a_playlist_in_the_message_reaches_the_game(self, monkeypatch):
        handler, game_state, ws = _game_at_end()

        async def _load(_hass, paths):
            assert paths == ["nineties.json"]
            return _nineties_songs(), []

        monkeypatch.setattr(
            "custom_components.beatify.server.ws_handlers.admin"
            ".async_load_songs_from_paths",
            _load,
        )

        await admin_rematch_game(
            handler,
            ws,
            {"action": "rematch_game", "playlists": ["nineties.json"]},
            game_state,
        )

        assert game_state.playlists == ["nineties.json"]
        assert game_state.phase == GamePhase.LOBBY
        assert sorted(p.name for p in game_state.players.values()) == [
            "Ana",
            "Markus",
        ]

    async def test_a_message_without_playlists_replays_the_same_music(self):
        handler, game_state, ws = _game_at_end()

        await admin_rematch_game(handler, ws, {"action": "rematch_game"}, game_state)

        assert game_state.playlists == ["test.json"]
        assert game_state.phase == GamePhase.LOBBY

    async def test_a_playlist_with_no_usable_song_is_refused_not_played(
        self, monkeypatch
    ):
        handler, game_state, ws = _game_at_end()

        async def _load(_hass, _paths):
            return [], ["Invalid song in nineties.json: missing year or uri"]

        monkeypatch.setattr(
            "custom_components.beatify.server.ws_handlers.admin"
            ".async_load_songs_from_paths",
            _load,
        )

        await admin_rematch_game(
            handler,
            ws,
            {"action": "rematch_game", "playlists": ["nineties.json"]},
            game_state,
        )

        assert [e["code"] for e in _errors(ws)] == [ERR_NO_PLAYABLE_SONGS]
        # The finished game is untouched: the host can pick something else.
        assert game_state.phase == GamePhase.END
        assert game_state.playlists == ["test.json"]
        handler.broadcast.assert_not_awaited()
        # #2648: the grace timer must survive a refused swap, because the game
        # it belongs to is still running.
        handler.cleanup_game_tasks.assert_not_awaited()

    async def test_a_malformed_playlists_field_is_rejected(self):
        handler, game_state, ws = _game_at_end()

        await admin_rematch_game(
            handler,
            ws,
            {"action": "rematch_game", "playlists": "nineties.json"},
            game_state,
        )

        assert _errors(ws)
        assert game_state.phase == GamePhase.END


# ---------------------------------------------------------------------------
# 4. What the end screen fetches
# ---------------------------------------------------------------------------


class TestNextPlaylistsView:
    async def _payload(self, tmp_path, *, with_analytics=True):
        from custom_components.beatify.const import DOMAIN
        from custom_components.beatify.server.playlist_views import NextPlaylistsView

        playlist_dir = tmp_path / "beatify" / "playlists"
        playlist_dir.mkdir(parents=True)
        for rel, name in (
            ("eighties.json", "80s Hits"),
            ("nineties.json", "90s Hits"),
            ("disco.json", "Disco & Funk"),
        ):
            (playlist_dir / rel).write_text(
                json.dumps(
                    {
                        "name": name,
                        "songs": [
                            {
                                "year": 1985,
                                "title": f"{name} track",
                                "artist": "Someone",
                                "uri": "spotify:track:0000000000000000000001",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

        game_state = MagicMock()
        game_state.playlists = ["eighties.json"]

        hass = MagicMock()
        hass.config.path.return_value = str(playlist_dir)
        domain_data = {"game": game_state}
        if with_analytics:
            analytics = MagicMock()
            analytics.get_recent_playlists.return_value = [
                {"name": "nineties"},
                {"name": "eighties"},
            ]
            domain_data["analytics"] = analytics
        hass.data = {DOMAIN: domain_data}

        resp = await NextPlaylistsView(hass).get(MagicMock())
        assert resp.status == 200
        return json.loads(resp.body)

    async def test_it_answers_with_the_grid_and_the_whole_catalogue(self, tmp_path):
        body = await self._payload(tmp_path)

        assert body["current"] == ["eighties.json"]
        assert body["suggested"][0]["reason"] == "current"
        assert body["suggested"][0]["name"] == "80s Hits"
        assert body["suggested"][1]["paths"] == ["nineties.json"]
        assert body["total"] == 3
        assert {entry["path"] for entry in body["all"]} == {
            "eighties.json",
            "nineties.json",
            "disco.json",
        }

    async def test_a_host_without_analytics_still_gets_a_grid(self, tmp_path):
        body = await self._payload(tmp_path, with_analytics=False)

        assert body["suggested"][0]["reason"] == "current"
        assert len(body["suggested"]) == 3
