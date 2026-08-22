"""#2294 — the create-game rejections a host can act on carry their own code.

Twelve rejections used to share ``INVALID_REQUEST``, which the client renders as
one generic sentence ("this request was invalid, check your setup"). On
2026-08-21 that cost an evening: Music Assistant had been down for five days, so
every speaker was unavailable, and the screen never said so.

Three of the twelve are things a host can actually fix. They now have codes.
"""

from __future__ import annotations

from custom_components.beatify.const import (
    ERR_MEDIA_PLAYER_UNAVAILABLE,
    ERR_NO_PLAYABLE_SONGS,
    ERR_NO_PLAYLISTS_SELECTED,
)


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

    def test_create_game_emits_the_new_codes(self):
        # Structural guard: the three call sites in the create path must use the
        # constants. A literal "INVALID_REQUEST" creeping back would be invisible
        # to a behavioural test that only checks the constants themselves.
        from pathlib import Path

        src = Path("custom_components/beatify/server/game_views.py").read_text()
        assert "code=ERR_NO_PLAYLISTS_SELECTED" in src
        assert "code=ERR_MEDIA_PLAYER_UNAVAILABLE" in src
        assert "code=ERR_NO_PLAYABLE_SONGS" in src


class TestTranslations:
    def test_every_locale_has_a_string_for_each_new_code(self):
        import json
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
        import json
        import re
        from pathlib import Path

        for path in sorted(Path("custom_components/beatify/www/i18n").glob("*.json")):
            errors = json.loads(path.read_text())["errors"]
            for code in (ERR_NO_PLAYLISTS_SELECTED, ERR_NO_PLAYABLE_SONGS):
                assert not re.search(r"\{[a-z_]+\}", errors[code], re.I)
