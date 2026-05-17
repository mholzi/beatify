"""Tests for AlbumArtView — the same-origin album-art proxy (#933)."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.server.views import AlbumArtView


def _request(query: dict) -> MagicMock:
    """Build a mock aiohttp request with the given query params."""
    request = MagicMock()
    request.query = query
    return request


class TestAlbumArtView:
    """Input validation for the album-art proxy endpoint."""

    def test_endpoint_is_unauthenticated(self):
        # Player browsers join unauthenticated — the proxy must be reachable.
        assert AlbumArtView.requires_auth is False
        assert AlbumArtView.url == "/beatify/api/albumart"

    async def test_missing_url_returns_400(self):
        view = AlbumArtView(MagicMock())
        resp = await view.get(_request({}))
        assert resp.status == 400

    async def test_non_http_scheme_returns_400(self):
        # A file:// URL must never be fetched server-side.
        view = AlbumArtView(MagicMock())
        resp = await view.get(_request({"url": "file:///etc/passwd"}))
        assert resp.status == 400
