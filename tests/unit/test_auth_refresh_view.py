"""Tests for BeatifyAuthRefreshView — silent server-side refresh (rc15).

The frontend calls ``GET /beatify/auth/refresh`` when its access cookie is
about to expire. The view reads the HttpOnly ``beatify_refresh`` cookie,
posts the refresh grant to HA over loopback, updates the access cookie,
and returns JSON so ha-auth.js can immediately use the new token.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.server.views import BeatifyAuthRefreshView


def _request(
    *,
    refresh_cookie: str | None = "stored-refresh",
    headers: dict | None = None,
) -> MagicMock:
    request = MagicMock()
    request.cookies = {"beatify_refresh": refresh_cookie} if refresh_cookie else {}
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


class TestBeatifyAuthRefreshView:
    def test_endpoint_is_unauthenticated(self):
        # Called by ha-auth.js without a Bearer (it's recovering the
        # session); auth is via the HttpOnly refresh cookie.
        assert BeatifyAuthRefreshView.requires_auth is False
        assert BeatifyAuthRefreshView.url == "/beatify/auth/refresh"

    @pytest.mark.asyncio
    async def test_missing_refresh_cookie_returns_401_and_clears(self):
        view = BeatifyAuthRefreshView(_hass())
        resp = await view.get(_request(refresh_cookie=None))
        assert resp.status == 401
        # Even with no incoming cookies, send Max-Age=0 wipes so any
        # stale browser-side access cookie is dropped too.
        assert "beatify_access" in resp.cookies
        assert resp.cookies["beatify_access"]["max-age"] == "0"
        assert "beatify_refresh" in resp.cookies
        assert resp.cookies["beatify_refresh"]["max-age"] == "0"

    @pytest.mark.asyncio
    async def test_successful_refresh_returns_json_and_updates_access_cookie(self):
        view = BeatifyAuthRefreshView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=200,
                text=(
                    '{"access_token":"refreshed-access","expires_in":1800,'
                    '"token_type":"Bearer"}'
                ),
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request())

        assert resp.status == 200
        body = json.loads(resp.body)
        assert body["access_token"] == "refreshed-access"
        assert body["expires_in"] == 1800
        # Browser caches MUST NOT keep an auth response around.
        assert resp.headers.get("Cache-Control") == "no-store"

        # Access cookie reissued.
        access = resp.cookies["beatify_access"]
        assert "refreshed-access" in access.value
        assert access["path"] == "/beatify"
        # Crucially, the refresh cookie is NOT touched — HA's refresh
        # grant doesn't return a new refresh_token, so we leave the
        # existing long-lived one in place.
        assert "beatify_refresh" not in resp.cookies

    @pytest.mark.asyncio
    async def test_ha_rejects_refresh_token_clears_cookies_returns_401(self):
        # HA wiped the refresh token (user logged out, HA restart with
        # session loss, refresh token explicitly revoked). The frontend
        # needs to start a fresh OAuth flow — so we wipe both cookies.
        view = BeatifyAuthRefreshView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=400, text='{"error":"invalid_grant"}'
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request())

        assert resp.status == 401
        assert resp.cookies["beatify_access"]["max-age"] == "0"
        assert resp.cookies["beatify_refresh"]["max-age"] == "0"

    @pytest.mark.asyncio
    async def test_refresh_body_includes_grant_type_and_client_id(self):
        view = BeatifyAuthRefreshView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(
                status=200, text='{"access_token":"x","expires_in":1800}'
            )
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            await view.get(_request())

        body = mock_session.post.call_args.kwargs["data"]
        assert "grant_type=refresh_token" in body
        assert "refresh_token=stored-refresh" in body
        # client_id must match what the frontend used at /auth/authorize —
        # origin + "/beatify/". For this test request, origin is the host.
        assert "client_id=http%3A%2F%2Fha.local%3A8123%2Fbeatify%2F" in body
