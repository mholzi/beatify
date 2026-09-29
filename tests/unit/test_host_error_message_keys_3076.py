"""#3076 - the host phone shows the SPECIFIC server message, not the generic code text.

#3057 mapped every error frame to ``errors.<CODE>``. Several codes are shared by
many refusals (INVALID_ACTION alone covers twenty), and some are plainly less
precise than the server text: "Need at least 2 players to start" became "Game has
not started". The server now tags each message with a stable ``message_key`` and
the frontend resolves it under ``errors.host.<message_key>``.

These tests pin the server half: the refusals carry the key and its parameters,
and every key the Python code can send exists in all six locales with the same
placeholders as the English text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN, MIN_PLAYERS
from custom_components.beatify.server.game_views import StartGameplayView
from custom_components.beatify.server.ws_handlers.admin import admin_start_game

from tests.conftest import make_game_state, make_songs

CC = Path(__file__).parents[2] / "custom_components" / "beatify"
I18N = CC / "www" / "i18n"
LOCALES = ("en", "de", "es", "fr", "nl", "it")


def _lobby_with(players: int):
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    for i in range(players):
        ws = AsyncMock()
        ws.closed = False
        state.add_player(f"P{i}", ws)
        state.get_player(f"P{i}").connected = True
    return state


async def test_ws_start_with_one_player_sends_the_specific_key():
    ws = AsyncMock()
    handler = MagicMock()
    await admin_start_game(handler, ws, {}, _lobby_with(1))
    frame = ws.send_json.call_args.args[0]
    assert frame["code"] == "GAME_NOT_STARTED"  # unchanged, still the fallback
    assert frame["message_key"] == "NEED_PLAYERS"
    assert frame["min_players"] == MIN_PLAYERS


@patch(
    "custom_components.beatify.server.game_views.is_authorized_http",
    return_value=True,
)
async def test_rest_start_with_one_player_sends_the_specific_key(_auth):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": _lobby_with(1), "ws_handler": MagicMock()}}
    resp = await StartGameplayView(hass).post(MagicMock())
    body = json.loads(resp.body)
    assert resp.status == 409
    assert body["message_key"] == "NEED_PLAYERS"
    assert body["min_players"] == MIN_PLAYERS


def _sent_keys() -> set[str]:
    keys: set[str] = set()
    for path in (
        CC / "server" / "ws_handlers" / "admin.py",
        CC / "server" / "ws_handlers" / "lifecycle.py",
        CC / "server" / "game_views.py",
    ):
        text = path.read_text(encoding="utf-8")
        keys |= set(re.findall(r'message_key\s*=\s*"([A-Z_]+)"', text))
        keys |= set(re.findall(r'"message_key":\s*"([A-Z_]+)"', text))
        # keys carried in a variable: error_key = "X" and (text, "KEY") tuples
        keys |= set(re.findall(r'error_key\s*=\s*"([A-Z_]+)"', text))
        keys |= set(re.findall(r'"[^"\n]+",\s*"(JOIN_[A-Z_]+)"', text))
        keys |= set(re.findall(r'^\s*"(JOIN_[A-Z_]+)",?$', text, re.M))
    return keys


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{([a-z_]+)\}", text))


def test_the_scan_finds_the_keys():
    keys = _sent_keys()
    assert {"NEED_PLAYERS", "JOIN_NAME_TAKEN", "JOIN_FAILED", "NO_ACTIVE_GAME"} <= keys
    assert len(keys) >= 55


@pytest.mark.parametrize("locale", LOCALES)
def test_every_sent_key_exists_in_every_locale(locale):
    host = json.loads((I18N / f"{locale}.json").read_text(encoding="utf-8"))["errors"][
        "host"
    ]
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))["errors"]["host"]
    missing = _sent_keys() - set(host)
    assert not missing, f"{locale}: {sorted(missing)}"
    for key in _sent_keys():
        assert host[key].strip(), f"{locale}.{key} is empty"
        assert _placeholders(host[key]) == _placeholders(en[key]), f"{locale}.{key}"
    # No orphans: a key nobody sends is dead weight in six files.
    assert set(host) == set(en)


def test_every_english_text_matches_what_the_server_sends():
    """Same meaning as the server text: the English locale is that text."""
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))["errors"]["host"]
    assert en["NEED_PLAYERS"] == "Need at least {min_players} players to start"
    assert en["ALREADY_STARTED"] == "Game already started"
    assert en["NO_ACTIVE_GAME"] == "No active game"
