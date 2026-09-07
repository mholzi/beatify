"""#2294 — the create-game rejections a host can act on carry their own code.

Twelve rejections used to share ``INVALID_REQUEST``, which the client renders as
one generic sentence ("this request was invalid, check your setup"). On
2026-08-21 that cost an evening: Music Assistant had been down for five days, so
every speaker was unavailable, and the screen never said so.

Three of the twelve are things a host can actually fix. They now have codes.

#2701: the three call sites used to be checked by reading ``game_views.py`` and
asserting ``"code=ERR_NO_PLAYLISTS_SELECTED" in src``. That is green for a call
site that passes the code positionally and red for one that spreads a kwargs
dict — neither of which a host would notice either way. ``StartGameView.post``
is driven for real below, once per rejection, and the code is read off the
response body the client actually receives.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.const import (
    ERR_MEDIA_PLAYER_UNAVAILABLE,
    ERR_NO_PLAYABLE_SONGS,
    ERR_NO_PLAYLISTS_SELECTED,
)

from .conftest import make_start_game_request


class TestDistinctErrorCodes:
    def test_codes_are_distinct_from_each_other(self):
        codes = {
            ERR_MEDIA_PLAYER_UNAVAILABLE,
            ERR_NO_PLAYLISTS_SELECTED,
            ERR_NO_PLAYABLE_SONGS,
        }
        assert len(codes) == 3

    def test_none_of_them_is_the_generic_code(self):
        # The whole point: these three must never collapse back into the code
        # that made them indistinguishable.
        for code in (
            ERR_MEDIA_PLAYER_UNAVAILABLE,
            ERR_NO_PLAYLISTS_SELECTED,
            ERR_NO_PLAYABLE_SONGS,
        ):
            assert code != "INVALID_REQUEST"

    def test_media_player_code_is_the_one_the_websocket_path_already_used(self):
        # ws_handlers/admin.py has emitted this code since #949, and admin/api.js
        # routes it to the speaker banner with a "Select Speaker" action (#2269).
        # Reusing it means the REST path inherits that affordance instead of
        # growing a second, parallel code for the same situation.
        assert ERR_MEDIA_PLAYER_UNAVAILABLE == "MEDIA_PLAYER_UNAVAILABLE"


class TestCreateGameEmitsTheNewCodes:
    """Each rejection is provoked and the response is read back.

    Status and code are asserted together, for the reason spelled out in
    ``test_no_playable_songs_500_2530.py``: a test that only checks "not 200"
    passes on a 500, which is the response with no code at all.
    """

    @staticmethod
    def _rejection(resp) -> tuple[int, str]:
        body = json.loads(resp.body)
        # Both keys are populated by ``_json_error``; ``code`` is what the
        # client reads for its ``errors.<CODE>`` lookup.
        assert body["code"] == body["error"]
        return resp.status, body["code"]

    async def test_no_playlists_selected(self, start_game_env):
        view, hass, body = start_game_env
        body["playlists"] = []

        resp = await view.post(make_start_game_request(hass, body))
        assert self._rejection(resp) == (400, ERR_NO_PLAYLISTS_SELECTED)

    async def test_media_player_unavailable(self, start_game_env):
        # The 2026-08-21 evening exactly: Music Assistant down, every speaker
        # entity reporting `unavailable`.
        view, hass, body = start_game_env
        hass.states.get.return_value = MagicMock(state="unavailable")

        resp = await view.post(make_start_game_request(hass, body))
        status, code = self._rejection(resp)
        assert (status, code) == (400, ERR_MEDIA_PLAYER_UNAVAILABLE)
        # #2269: the speaker banner needs to know WHICH entity to offer.
        assert json.loads(resp.body)["entity_id"] == "media_player.test"

    async def test_no_playable_songs(self, start_game_env):
        # The fixture's playlist carries Spotify URIs only; asking for Apple
        # Music loads songs of which none is playable on the chosen provider.
        view, hass, body = start_game_env
        body["provider"] = "apple_music"

        with patch(
            "custom_components.beatify.server.game_views.get_platform_capabilities",
            return_value={"supported": True, "apple_music": True},
        ):
            resp = await view.post(make_start_game_request(hass, body))
        assert self._rejection(resp) == (400, ERR_NO_PLAYABLE_SONGS)

    async def test_the_three_rejections_stay_told_apart(self, start_game_env):
        """The regression this issue is about, in one assertion.

        Before #2294 all three answered ``INVALID_REQUEST`` and the host saw the
        same sentence for a missing playlist, a dead speaker and an unplayable
        provider. Collapsing any two of them back together fails here.
        """
        view, hass, body = start_game_env

        async def code_for(payload) -> str:
            resp = await view.post(make_start_game_request(hass, payload))
            return json.loads(resp.body)["code"]

        seen = [await code_for(dict(body, playlists=[]))]

        hass.states.get.return_value = MagicMock(state="unavailable")
        seen.append(await code_for(body))

        hass.states.get.return_value = MagicMock(state="playing")
        with patch(
            "custom_components.beatify.server.game_views.get_platform_capabilities",
            return_value={"supported": True, "apple_music": True},
        ):
            seen.append(await code_for(dict(body, provider="apple_music")))

        assert len(set(seen)) == 3, f"two rejections share a code: {seen}"
        assert "INVALID_REQUEST" not in seen


class TestTranslations:
    def test_every_locale_has_a_string_for_each_new_code(self):
        from pathlib import Path

        for path in sorted(Path("custom_components/beatify/www/i18n").glob("*.json")):
            errors = json.loads(path.read_text())["errors"]
            for code in (ERR_NO_PLAYLISTS_SELECTED, ERR_NO_PLAYABLE_SONGS):
                assert code in errors, f"{path.name} is missing errors.{code}"
                assert errors[code].strip(), f"{path.name} has an empty errors.{code}"

    def test_new_strings_carry_no_unfilled_placeholders(self):
        # getErrorMessage rejects a translation still holding {placeholder} and
        # falls back to the English backend message — which would silently undo
        # the translation work.
        import re
        from pathlib import Path

        for path in sorted(Path("custom_components/beatify/www/i18n").glob("*.json")):
            errors = json.loads(path.read_text())["errors"]
            for code in (ERR_NO_PLAYLISTS_SELECTED, ERR_NO_PLAYABLE_SONGS):
                assert not re.search(r"\{[a-z_]+\}", errors[code], re.I)


@pytest.mark.parametrize(
    "code",
    [ERR_MEDIA_PLAYER_UNAVAILABLE, ERR_NO_PLAYLISTS_SELECTED, ERR_NO_PLAYABLE_SONGS],
)
def test_every_code_is_a_stable_screaming_snake_identifier(code):
    # The codes are the client's contract; a lowercase or spaced one would miss
    # the `errors.<CODE>` lookup and fall back to the English server message.
    assert code == code.upper()
    assert " " not in code
