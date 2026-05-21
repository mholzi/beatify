"""Tests for BeatifyAuthCallbackView — server-side OAuth code exchange (rc15).

The browser arrives here via /auth/authorize's redirect carrying ?code= and
?state=. The view exchanges the code over loopback HTTP and sets the
beatify_access (JS-readable JSON) + beatify_refresh (HttpOnly) cookies
before redirecting to /beatify/admin with state echoed for CSRF validation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from custom_components.beatify.server.views import BeatifyAuthCallbackView


def _request(query: dict, *, headers: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.query = query
    request.headers = headers or {"Host": "ha.local:8123"}
    request.scheme = "http"
    request.host = "ha.local:8123"
    return request


def _hass(server_port: int = 8123, ssl_certificate: str | None = None) -> MagicMock:
    hass = MagicMock()
    hass.http.server_port = server_port
    hass.http.ssl_certificate = ssl_certificate
    return hass


class _MockResponseCtx:
    """Async context manager that yields a stubbed aiohttp response."""

    def __init__(self, *, status: int, text: str):
        self._status = status
        self._text = text

    async def __aenter__(self):
        resp = MagicMock()
        resp.status = self._status
        resp.text = AsyncMock(return_value=self._text)
        return resp

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestBeatifyAuthCallbackView:
    def test_endpoint_is_unauthenticated(self):
        # This view IS the auth entry point — the browser hits it before
        # any session exists, so it must accept unauthenticated requests.
        assert BeatifyAuthCallbackView.requires_auth is False
        assert BeatifyAuthCallbackView.url == "/beatify/auth/callback"

    @pytest.mark.asyncio
    async def test_missing_code_redirects_with_error(self):
        view = BeatifyAuthCallbackView(_hass())
        resp = await view.get(_request({}))
        # 302 redirect to admin with error param so the frontend can
        # surface a clean message instead of silently looping.
        assert resp.status == 302
        assert "auth_error=missing_code" in resp.headers["Location"]

    @pytest.mark.asyncio
    async def test_successful_exchange_sets_cookies_and_redirects(self):
        view = BeatifyAuthCallbackView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=200,
                text=(
                    '{"access_token":"new-access","refresh_token":"new-refresh",'
                    '"expires_in":1800,"token_type":"Bearer"}'
                ),
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request({"code": "abc", "state": "xyz"}))

        assert resp.status == 302
        location = resp.headers["Location"]
        assert location.startswith("/beatify/admin")
        # State must be echoed back so the frontend can CSRF-validate.
        assert "auth_state=xyz" in location
        # auth_error must NOT be present on success.
        assert "auth_error" not in location

        # Verify both cookies were set. aiohttp Response.cookies is a
        # SimpleCookie-like mapping.
        assert "beatify_access" in resp.cookies
        assert "beatify_refresh" in resp.cookies

        access_morsel = resp.cookies["beatify_access"]
        # JS reads this — must NOT be HttpOnly.
        assert access_morsel["httponly"] in (False, "")
        # Scoped to /beatify to avoid leaking to the wider HA app.
        assert access_morsel["path"] == "/beatify"
        # The cookie body is the URL-encoded JSON. aiohttp leaves the
        # raw value alone, so we can just check for the access token.
        assert "new-access" in access_morsel.value

        refresh_morsel = resp.cookies["beatify_refresh"]
        # Refresh token MUST be HttpOnly — JS must never see it.
        assert refresh_morsel["httponly"] is True
        assert refresh_morsel["path"] == "/beatify"
        assert refresh_morsel.value == "new-refresh"

    @pytest.mark.asyncio
    async def test_ha_rejection_redirects_with_exchange_error(self):
        # HA rejected the code (expired, mismatched redirect_uri, etc.).
        # We redirect to admin with auth_error so the frontend can
        # decide to re-login instead of just trusting the cookie.
        view = BeatifyAuthCallbackView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(status=400, text='{"error":"invalid_grant"}')
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request({"code": "expired", "state": "xyz"}))

        assert resp.status == 302
        assert "auth_error=exchange_failed" in resp.headers["Location"]
        # No cookies set on failure.
        assert "beatify_access" not in resp.cookies
        assert "beatify_refresh" not in resp.cookies

    @pytest.mark.asyncio
    async def test_loopback_connection_failure_redirects_with_error(self):
        view = BeatifyAuthCallbackView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=ClientError("connection refused"))

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request({"code": "abc", "state": "xyz"}))

        assert resp.status == 302
        assert "auth_error=exchange_failed" in resp.headers["Location"]

    @pytest.mark.asyncio
    async def test_forwarded_proto_drives_secure_cookie_flag(self):
        # Nabu Casa terminates TLS upstream and proxies plain HTTP to HA.
        # request.scheme says "http" but the browser sees HTTPS — the
        # cookie's Secure flag must follow what the browser sees so the
        # cookie isn't dropped.
        view = BeatifyAuthCallbackView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=200,
                text=('{"access_token":"a","refresh_token":"r","expires_in":1800}'),
            )
        )

        forwarded_request = _request(
            {"code": "abc", "state": "xyz"},
            headers={
                "Host": "ha.local:8123",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "xxx.ui.nabu.casa",
            },
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(forwarded_request)

        assert resp.cookies["beatify_access"]["secure"] is True
        assert resp.cookies["beatify_refresh"]["secure"] is True

        # And client_id / redirect_uri in the exchange body must use the
        # public origin the browser saw, not the internal HTTP host.
        call_body = mock_session.post.call_args.kwargs["data"]
        assert "https%3A%2F%2Fxxx.ui.nabu.casa%2Fbeatify%2F" in call_body
        assert (
            "redirect_uri=https%3A%2F%2Fxxx.ui.nabu.casa%2Fbeatify%2Fauth%2Fcallback"
            in call_body
        )

    @pytest.mark.asyncio
    async def test_uses_loopback_https_when_ha_has_ssl_cert(self):
        # When HA is on HTTPS-only, the local listener is HTTPS — must use
        # https://127.0.0.1 with SSL verification disabled (loopback cert
        # almost certainly doesn't SAN 127.0.0.1).
        view = BeatifyAuthCallbackView(
            _hass(server_port=443, ssl_certificate="/etc/ha/cert.pem")
        )
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=200,
                text='{"access_token":"a","refresh_token":"r","expires_in":1800}',
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            await view.get(_request({"code": "abc", "state": "xyz"}))

        call_args = mock_session.post.call_args
        assert call_args.args[0] == "https://127.0.0.1:443/auth/token"
        assert call_args.kwargs["ssl"] is False
