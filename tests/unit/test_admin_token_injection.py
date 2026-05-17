"""Tests for AdminView's admin-token injection (#935 follow-up).

The admin token is otherwise handed back only once — in the start-game
response. An admin page that reconnects to an existing game had no token, so
token-gated REST calls (start-gameplay etc.) 403'd. AdminView now embeds the
active game's token into the served HTML.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server.views import AdminView

_HTML = (
    "<html><head>\n"
    '    <meta name="beatify-version" content="3.3.6-rc5">\n'
    "</head><body></body></html>"
)


def _view(game: object | None) -> AdminView:
    """An AdminView whose hass holds (or doesn't hold) an active game."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": game} if game is not None else {}}
    return AdminView(hass)


class TestAdminTokenInjection:
    """AdminView._inject_admin_token — embed the token only when a game is live."""

    def test_token_injected_when_game_active(self):
        game = MagicMock()
        game.admin_token = "secret-token-abc"
        game.game_id = "GAME123"
        out = _view(game)._inject_admin_token(_HTML)
        assert '<meta name="beatify-admin-token" content="secret-token-abc">' in out
        # Injected inside <head>, before the version meta.
        assert out.index("beatify-admin-token") < out.index("beatify-version")

    def test_no_active_game_leaves_html_untouched(self):
        out = _view(None)._inject_admin_token(_HTML)
        assert out == _HTML
        assert "beatify-admin-token" not in out

    def test_game_without_token_leaves_html_untouched(self):
        game = MagicMock()
        game.admin_token = None
        game.game_id = "GAME123"
        assert "beatify-admin-token" not in _view(game)._inject_admin_token(_HTML)

    def test_token_is_html_escaped(self):
        # A token never contains these chars, but the attribute must be safe.
        game = MagicMock()
        game.admin_token = 'a"b<c'
        game.game_id = "GAME123"
        out = _view(game)._inject_admin_token(_HTML)
        assert 'content="a"b<c"' not in out
        assert "&quot;" in out and "&lt;" in out
