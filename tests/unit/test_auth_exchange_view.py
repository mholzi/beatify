"""Tests for BeatifyAuthExchangeView — Safari 18 /auth/token workaround (rc14).

Safari 18 + Nabu Casa rejects browser POSTs to /auth/token with "access
control checks" errors. This view forwards the OAuth code/refresh
exchange to HA's local /auth/token over loopback HTTP so the response
the browser sees never crosses the SniTun relay.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientError

from custom_components.beatify.server.views import BeatifyAuthExchangeView


def _request(
    body: bytes = b"grant_type=authorization_code&code=abc",
    content_type: str = "application/x-www-form-urlencoded",
) -> MagicMock:
    request = MagicMock()
    request.read = AsyncMock(return_value=body)
    request.headers = {"Content-Type": content_type}
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


class TestBeatifyAuthExchangeView:
    def test_endpoint_is_unauthenticated(self):
        # /auth/token itself is unauthed by design — the proxy must mirror.
        assert BeatifyAuthExchangeView.requires_auth is False
        assert BeatifyAuthExchangeView.url == "/beatify/auth/exchange"

    @pytest.mark.asyncio
    async def test_forwards_body_to_loopback_auth_token_http(self):
        view = BeatifyAuthExchangeView(_hass(ssl_certificate=None))
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(status=200, text='{"access_token":"new"}')
        )

        body = b"grant_type=authorization_code&code=abc"
        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.post(_request(body=body))

        # Forwarded over loopback HTTP (no ssl_certificate → no https).
        call_args = mock_session.post.call_args
        assert call_args.args[0] == "http://127.0.0.1:8123/auth/token"
        assert call_args.kwargs["data"] == body
        assert (
            call_args.kwargs["headers"]["Content-Type"]
            == "application/x-www-form-urlencoded"
        )
        # ssl kwarg not present when scheme is http.
        assert "ssl" not in call_args.kwargs

        assert resp.status == 200
        assert resp.body == b'{"access_token":"new"}'
        # Beatify-issued no-store header so browsers never cache an auth response.
        assert resp.headers["Cache-Control"] == "no-store"

    @pytest.mark.asyncio
    async def test_uses_loopback_https_when_ha_has_ssl_cert(self):
        # When HA is configured with ssl_certificate, the local listener
        # is HTTPS only — must use https://127.0.0.1 and disable cert verify.
        view = BeatifyAuthExchangeView(
            _hass(server_port=443, ssl_certificate="/etc/ha/cert.pem")
        )
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(status=200, text="{}")
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            await view.post(_request())

        call_args = mock_session.post.call_args
        assert call_args.args[0] == "https://127.0.0.1:443/auth/token"
        # Loopback cert can't be verified (it isn't issued for 127.0.0.1).
        assert call_args.kwargs["ssl"] is False

    @pytest.mark.asyncio
    async def test_relays_status_code_and_body_on_ha_rejection(self):
        # When HA rejects the exchange (e.g. invalid_grant), the proxy
        # MUST surface the same status + body so the frontend sees a real
        # auth failure, not a 200.
        view = BeatifyAuthExchangeView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=400,
                text='{"error":"invalid_grant"}',
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.post(_request())

        assert resp.status == 400
        assert resp.body == b'{"error":"invalid_grant"}'

    @pytest.mark.asyncio
    async def test_returns_502_on_loopback_connection_failure(self):
        # If the loopback POST itself errors (HA shutting down, port mismatch),
        # surface a real 5xx so the frontend can distinguish "HA said no" from
        # "the proxy is broken."
        view = BeatifyAuthExchangeView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=ClientError("connection refused"))

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.post(_request())

        assert resp.status == 502
        # JSON body so the frontend can distinguish proxy failures from
        # HA's own error responses (which also have a body).
        assert b"proxy_failed" in resp.body
