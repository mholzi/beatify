"""start-game must answer NO_PLAYABLE_SONGS, not a bare 500 (#2530).

Picking a playlist that has no URI for the chosen provider used to escape
``StartGameView.post`` as an uncaught ``ValueError``, which aiohttp turned into
``500 Internal Server Error`` — a response carrying no ``code`` at all. That
defeats #2294 (every create-game rejection gets its own code so the client can
say WHICH one fired) and leaves the ``errors.<CODE>`` i18n lookup with nothing
to look up, so the host saw a crash page instead of "this playlist has nothing
playable on that provider".

Every assertion here checks the **status code and the error code together**. A
test that only asserts "not 200" would have passed on the broken build — a 500
is also not 200.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from custom_components.beatify.const import DOMAIN, ERR_NO_PLAYABLE_SONGS
from custom_components.beatify.game.state_setup import NoPlayableSongsError

from .conftest import make_start_game_request


def _apple_capable():
    """Let the speaker-capability gate pass for Apple Music.

    The shared fixture stubs ``get_platform_capabilities`` with
    ``{"supported": True}`` only, which the earlier per-provider gate
    (``game_views.py``, PROVIDER_NOT_SUPPORTED) rejects before ``create_game``
    is ever reached. Without this the test would assert the wrong rejection and
    pass on a build that still 500s.
    """
    return patch(
        "custom_components.beatify.server.game_views.get_platform_capabilities",
        return_value={"supported": True, "apple_music": True},
    )


class TestNoPlayableSongsResponse:
    """The provider-with-no-URIs rejection reaches the client as a 400 + code."""

    async def test_provider_without_uris_returns_400_no_playable_songs(
        self, start_game_env
    ):
        # The fixture's playlist carries Spotify URIs only. Asking for Apple
        # Music is exactly the real-world case from the v4.4.1-rc1 live test:
        # songs load, none of them is playable on the chosen provider.
        view, hass, body = start_game_env
        body["provider"] = "apple_music"

        with _apple_capable():
            resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 400, (
            f"expected 400, got {resp.status} — a 500 here is the #2530 regression"
        )
        payload = json.loads(resp.body)
        assert payload["code"] == ERR_NO_PLAYABLE_SONGS
        # The message must still name the provider; it is what tells the host
        # which of their two choices to change.
        assert "apple_music" in payload["message"]

    async def test_the_game_is_not_left_half_created(self, start_game_env):
        # #1378 validates before mutating. The new except-arm must not undo
        # that: after a rejection the state has to be as untouched as before.
        view, hass, body = start_game_env
        body["provider"] = "apple_music"

        with _apple_capable():
            await view.post(make_start_game_request(hass, body))

        game_state = hass.data[DOMAIN]["game"]
        assert game_state.game_id is None
        assert game_state.players == {}

    async def test_a_playable_provider_still_starts(self, start_game_env):
        # Guard against over-catching: the happy path must be untouched.
        view, hass, body = start_game_env
        body["provider"] = "spotify"

        resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 200
        assert hass.data[DOMAIN]["game"].game_id is not None


class TestOtherValueErrorsKeepTheirOwnCode:
    """A different rejection must not borrow NO_PLAYABLE_SONGS."""

    async def test_unrelated_value_error_maps_to_invalid_request(self, start_game_env):
        # A wrong code is worse than a generic one: the client renders it as a
        # specific sentence, so mapping every ValueError onto NO_PLAYABLE_SONGS
        # would tell the host to change their playlist over an unrelated fault.
        view, hass, body = start_game_env
        game_state = hass.data[DOMAIN]["game"]

        with patch.object(
            game_state,
            "create_game",
            side_effect=ValueError("Round duration must be between 15 and 60 seconds"),
        ):
            resp = await view.post(make_start_game_request(hass, body))

        assert resp.status == 400
        payload = json.loads(resp.body)
        assert payload["code"] == "INVALID_REQUEST"
        assert payload["code"] != ERR_NO_PLAYABLE_SONGS


class TestExceptionContract:
    """The new exception narrows the signal without changing the contract."""

    def test_is_a_value_error(self):
        # Subclassing ValueError is what keeps every existing caller and test
        # that expects `pytest.raises(ValueError)` from create_game working.
        assert issubclass(NoPlayableSongsError, ValueError)

    def test_create_game_still_raises_for_a_dead_provider(self):
        from custom_components.beatify.game.state import GameState

        game_state = GameState()
        songs = [
            {
                "year": 1985,
                "title": "Song One",
                "artist": "Artist One",
                "uri": "spotify:track:0000000000000000000001",
            }
        ]
        with pytest.raises(NoPlayableSongsError):
            game_state.create_game(
                playlists=["test.json"],
                songs=songs,
                media_player="media_player.test",
                base_url="http://localhost:8123",
                provider="apple_music",
            )

    def test_caller_catching_plain_value_error_still_sees_it(self):
        from custom_components.beatify.game.state import GameState

        game_state = GameState()
        songs = [
            {
                "year": 1985,
                "title": "Song One",
                "artist": "Artist One",
                "uri": "spotify:track:0000000000000000000001",
            }
        ]
        with pytest.raises(ValueError):  # noqa: PT011
            game_state.create_game(
                playlists=["test.json"],
                songs=songs,
                media_player="media_player.test",
                base_url="http://localhost:8123",
                provider="apple_music",
            )
