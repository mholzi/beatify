"""Tests for AlbumArtView — the same-origin album-art proxy (#933, SSRF-hardened #1356)."""

from __future__ import annotations

import asyncio
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


class TestAlbumArtSharedFetch:
    """One cover, one upstream fetch — however many guests are in the room (#2709)."""

    URL = "http://192.168.1.9:8095/imageproxy?item=round1"

    def _hass(self):
        """A hass whose DNS resolution is countable as well as allowed."""
        hass = MagicMock()
        hass.dns_calls = 0

        async def _resolve(_fn, *_a):
            hass.dns_calls += 1
            await asyncio.sleep(0)
            return [(2, 1, 6, "", ("192.168.1.9", 0))]

        hass.async_add_executor_job = AsyncMock(side_effect=_resolve)
        return hass

    def _counting_session(self, responses):
        """A session that hands out ``responses`` in order and counts its GETs."""
        session = MagicMock()
        session.upstream = 0
        queue = list(responses)

        def _get(*_a, **_k):
            session.upstream += 1
            return queue.pop(0) if len(queue) > 1 else queue[0]

        session.get = _get
        return session

    async def test_twenty_two_clients_are_one_upstream_fetch(self):
        """Twenty guests, the TV and the host, all at the same instant."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session(
            [_FakeResponse(content_type="image/jpeg", chunks=(b"COVER",))]
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            responses = await asyncio.gather(
                *(view.get(_request(_signed_query(self.URL))) for _ in range(22))
            )

        assert session.upstream == 1
        assert hass.dns_calls == 1
        assert all(r.status == 200 for r in responses)
        assert all(r.body == b"COVER" for r in responses)

    async def test_a_later_request_is_served_from_cache(self):
        """A phone that joins mid-round costs nothing upstream."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session(
            [_FakeResponse(content_type="image/png", chunks=(b"PNGDATA",))]
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            first = await view.get(_request(_signed_query(self.URL)))
            second = await view.get(_request(_signed_query(self.URL)))

        assert session.upstream == 1
        assert first.body == second.body == b"PNGDATA"

    async def test_the_next_round_refetches(self):
        """A new cover means a new signed URL, and the cache holds only one."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session(
            [
                _FakeResponse(chunks=(b"ROUND1",)),
                _FakeResponse(chunks=(b"ROUND2",)),
            ]
        )
        next_url = "http://192.168.1.9:8095/imageproxy?item=round2"

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            first = await view.get(_request(_signed_query(self.URL)))
            second = await view.get(_request(_signed_query(next_url)))
            again = await view.get(_request(_signed_query(next_url)))

        assert session.upstream == 2
        assert first.body == b"ROUND1"
        assert second.body == again.body == b"ROUND2"
        assert view._cached_url == next_url

    async def test_a_stale_entry_is_not_served(self):
        """Past the TTL the cover is fetched again rather than replayed."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session(
            [_FakeResponse(chunks=(b"OLD",)), _FakeResponse(chunks=(b"NEW",))]
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            first = await view.get(_request(_signed_query(self.URL)))
            view._cached_at -= view._CACHE_TTL + 1
            second = await view.get(_request(_signed_query(self.URL)))

        assert session.upstream == 2
        assert first.body == b"OLD"
        assert second.body == b"NEW"

    async def test_a_failed_fetch_is_not_cached(self):
        """A momentary upstream hiccup must not stick for the whole TTL."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session(
            [_FakeResponse(status=500), _FakeResponse(chunks=(b"COVER",))]
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            first = await view.get(_request(_signed_query(self.URL)))
            second = await view.get(_request(_signed_query(self.URL)))

        assert first.status == 502
        assert second.status == 200
        assert second.body == b"COVER"

    async def test_every_waiter_sees_the_shared_error(self):
        """A shared failure reaches all of them, not just the one who asked first."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session([_FakeResponse(content_type="text/html")])

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            responses = await asyncio.gather(
                *(view.get(_request(_signed_query(self.URL))) for _ in range(5))
            )

        assert session.upstream == 1
        assert [r.status for r in responses] == [415] * 5

    async def test_the_cache_is_behind_the_signature_gate(self):
        """A cached cover is not a way to skip the HMAC check."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session([_FakeResponse(chunks=(b"COVER",))])

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            await view.get(_request(_signed_query(self.URL)))
            forged = await view.get(_request({"url": self.URL, "sig": "deadbeef"}))

        assert forged.status == 403

    async def test_a_disconnecting_guest_does_not_cancel_the_shared_fetch(self):
        """The first phone closing its browser must not strand the other twenty."""
        hass = self._hass()
        view = AlbumArtView(hass)
        session = self._counting_session([_FakeResponse(chunks=(b"COVER",))])

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=session,
        ):
            leaver = asyncio.ensure_future(view.get(_request(_signed_query(self.URL))))
            await asyncio.sleep(0)  # let it start the shared fetch
            stayer = asyncio.ensure_future(view.get(_request(_signed_query(self.URL))))
            await asyncio.sleep(0)
            leaver.cancel()
            result = await stayer

        assert session.upstream == 1
        assert result.status == 200
        assert result.body == b"COVER"
