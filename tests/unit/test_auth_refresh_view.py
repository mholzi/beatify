"""Tests for BeatifyAuthRefreshView — silent server-side refresh (rc15).

The frontend calls ``GET /beatify/auth/refresh`` when its in-memory access
token is about to expire (and once on every page load to bootstrap it). The
view reads the HttpOnly ``beatify_refresh`` cookie, posts the refresh grant
to HA over loopback, and returns the fresh access token in the JSON body so
ha-auth.js can hold it in memory. Per #1369 the access token is never put
back into a JS-readable cookie.
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
        # #1369: the JSON body is the SOLE carrier of the access token —
        # the frontend caches it in memory, never in a cookie.
        assert body["access_token"] == "refreshed-access"
        assert body["expires_in"] == 1800
        # Browser caches MUST NOT keep an auth response around.
        assert resp.headers.get("Cache-Control") == "no-store"

        # The access token must NOT be reissued in a live JS-readable cookie.
        # del_cookie may emit a beatify_access morsel, but it must be an
        # expiry (max-age=0), never a token-bearing value.
        access = resp.cookies.get("beatify_access")
        if access is not None:
            assert "refreshed-access" not in access.value
            assert str(access["max-age"]) == "0"
        # #1932: the refresh cookie IS re-issued — same value (HA's refresh
        # grant mints no new refresh_token), fresh Max-Age. Before this the
        # cookie kept the expiry it got at first login, so an active user was
        # still thrown back into the full OAuth flow on day 30.
        refresh = resp.cookies.get("beatify_refresh")
        assert refresh is not None
        assert refresh.value == "stored-refresh"
        assert refresh["max-age"] == str(30 * 24 * 60 * 60)

    @pytest.mark.asyncio
    async def test_ha_rejects_refresh_token_clears_cookies_returns_401(self):
        # HA wiped the refresh token (user logged out, HA restart with
        # session loss, refresh token explicitly revoked). The frontend
        # needs to start a fresh OAuth flow — so we wipe both cookies.
        view = BeatifyAuthRefreshView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(status=400, text='{"error":"invalid_grant"}')
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

    @pytest.mark.asyncio
    async def test_rolled_cookie_keeps_security_attributes(self):
        """#1932: rolling must not quietly downgrade the cookie.

        The re-issued cookie has to keep HttpOnly, Path=/beatify and
        SameSite=Lax — the attributes that stop JS from reading it and stop it
        from riding along on non-Beatify requests.
        """
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
            resp = await view.get(_request())

        refresh = resp.cookies["beatify_refresh"]
        assert refresh["httponly"]
        assert refresh["path"] == "/beatify"
        assert refresh["samesite"] == "Lax"

    @pytest.mark.asyncio
    async def test_rolled_cookie_is_secure_only_over_https(self):
        """#1932: the roll must follow the same Secure rule as the callback —
        Secure on an HTTPS origin (Nabu Casa), not on plain-HTTP LAN access
        where the browser would then refuse to store it at all.
        """
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
            plain = await view.get(_request())
            tls = await view.get(
                _request(
                    headers={
                        "Host": "abc.ui.nabu.casa",
                        "X-Forwarded-Proto": "https",
                        "X-Forwarded-Host": "abc.ui.nabu.casa",
                    }
                )
            )

        assert not plain.cookies["beatify_refresh"]["secure"]
        assert tls.cookies["beatify_refresh"]["secure"]

    @pytest.mark.asyncio
    async def test_failed_refresh_still_wipes_instead_of_rolling(self):
        """A rejected refresh token must be cleared, never re-issued with a
        fresh 30 days — otherwise a dead session would be kept alive on disk.
        """
        view = BeatifyAuthRefreshView(_hass())
        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=_MockResponseCtx(status=400, text='{"error":"invalid_grant"}')
        )

        with patch(
            "custom_components.beatify.server.views.async_get_clientsession",
            return_value=mock_session,
        ):
            resp = await view.get(_request())

        assert resp.status == 401
        assert resp.cookies["beatify_refresh"]["max-age"] == "0"
        assert resp.cookies["beatify_refresh"].value != "stored-refresh"
