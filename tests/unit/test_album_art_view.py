"""Tests for AlbumArtView — the same-origin album-art proxy (#933, SSRF-hardened #1356)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.server.views import AlbumArtView
from custom_components.beatify.services.media_player import (
    _album_art_signature,
    album_art_signature_is_valid,
    proxy_album_art,
)


def _request(query: dict) -> MagicMock:
    """Build a mock aiohttp request with the given query params."""
    request = MagicMock()
    request.query = query
    return request


def _signed_query(url: str) -> dict:
    """A query dict carrying a valid signature for ``url`` (#1356)."""
    return {"url": url, "sig": _album_art_signature(url)}


def _hass_resolving_to(addr: str) -> MagicMock:
    """A mock hass whose executor resolves any host to ``addr``."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(return_value=[(2, 1, 6, "", (addr, 0))])
    return hass


async def _aiter(chunks):
    for c in chunks:
        yield c


class _FakeResponse:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(
        self, status=200, content_type="image/jpeg", chunks=(b"img",), headers=None
    ):
        self.status = status
        self.headers = {"Content-Type": content_type}
        if headers:
            self.headers.update(headers)
        self.content = MagicMock()
        self.content.iter_chunked = lambda _n: _aiter(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


def _session_returning(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.get = MagicMock(return_value=resp)
    return session


class TestAlbumArtSignature:
    """The HMAC signature is what stops the proxy being an open SSRF relay."""

    def test_proxy_album_art_appends_valid_signature(self):
        wrapped = proxy_album_art("http://192.168.1.9:8095/imageproxy?x=1")
        assert wrapped.startswith("/beatify/api/albumart?url=")
        assert "&sig=" in wrapped

    def test_relative_urls_pass_through_unsigned(self):
        assert (
            proxy_album_art("/beatify/static/img/no-artwork.svg")
            == "/beatify/static/img/no-artwork.svg"
        )

    def test_empty_signature_is_rejected(self):
        assert album_art_signature_is_valid("http://x/y", "") is False

    def test_signature_is_url_specific(self):
        sig = _album_art_signature("http://a/1")
        assert album_art_signature_is_valid("http://a/1", sig) is True
        assert album_art_signature_is_valid("http://a/2", sig) is False


class TestAlbumArtView:
    """Input validation + SSRF defences for the proxy endpoint."""

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

    async def test_unsigned_url_returns_403(self):
        # Without our signature the URL is attacker-controlled → refuse.
        view = AlbumArtView(MagicMock())
        resp = await view.get(
            _request({"url": "http://169.254.169.254/latest/meta-data/"})
        )
        assert resp.status == 403

    async def test_forged_signature_returns_403(self):
        view = AlbumArtView(MagicMock())
        resp = await view.get(
            _request({"url": "http://evil.example/x", "sig": "deadbeef"})
        )
        assert resp.status == 403

    async def test_signed_but_loopback_host_returns_403(self):
        # Valid signature, but the host resolves to loopback → still refused.
        url = "http://127.0.0.1:8095/imageproxy"
        hass = _hass_resolving_to("127.0.0.1")
        view = AlbumArtView(hass)
        resp = await view.get(_request(_signed_query(url)))
        assert resp.status == 403
        # Proves we got past the signature gate to the host check.
        hass.async_add_executor_job.assert_awaited()

    async def test_signed_metadata_endpoint_returns_403(self):
        url = "http://169.254.169.254/latest/meta-data/"
        hass = _hass_resolving_to("169.254.169.254")
        view = AlbumArtView(hass)
        resp = await view.get(_request(_signed_query(url)))
        assert resp.status == 403

    async def test_signed_private_host_is_fetched(self):
        # RFC1918 is the legitimate Music Assistant LAN target (#933).
        url = "http://192.168.1.9:8095/imageproxy?x=1"
        hass = _hass_resolving_to("192.168.1.9")
        view = AlbumArtView(hass)
        resp = _FakeResponse(status=200, content_type="image/png", chunks=(b"PNGDATA",))
        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=_session_returning(resp),
        ):
            out = await view.get(_request(_signed_query(url)))
        assert out.status == 200
        assert out.body == b"PNGDATA"

    async def test_non_image_content_type_returns_415(self):
        url = "http://192.168.1.9/page.html"
        hass = _hass_resolving_to("192.168.1.9")
        view = AlbumArtView(hass)
        resp = _FakeResponse(status=200, content_type="text/html", chunks=(b"<html>",))
        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=_session_returning(resp),
        ):
            out = await view.get(_request(_signed_query(url)))
        assert out.status == 415

    async def test_oversize_content_length_returns_413(self):
        url = "http://192.168.1.9/huge.jpg"
        hass = _hass_resolving_to("192.168.1.9")
        view = AlbumArtView(hass)
        resp = _FakeResponse(
            status=200,
            content_type="image/jpeg",
            chunks=(b"x",),
            headers={"Content-Length": str(50 * 1024 * 1024)},
        )
        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=_session_returning(resp),
        ):
            out = await view.get(_request(_signed_query(url)))
        assert out.status == 413

    async def test_streamed_body_over_cap_returns_413(self):
        url = "http://192.168.1.9/huge.jpg"
        hass = _hass_resolving_to("192.168.1.9")
        view = AlbumArtView(hass)
        big = b"x" * (3 * 1024 * 1024)
        resp = _FakeResponse(status=200, content_type="image/jpeg", chunks=(big, big))
        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=_session_returning(resp),
        ):
            out = await view.get(_request(_signed_query(url)))
        assert out.status == 413
