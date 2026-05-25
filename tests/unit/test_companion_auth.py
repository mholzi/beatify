"""Tests for the HA Android Companion auth-bypass (#1131)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.server.companion_auth import (
    extract_request_meta,
    is_authorized_http,
    is_companion_trusted_meta,
    is_companion_trusted_request,
    is_companion_ua,
    is_local_remote,
)


# ---------------------------------------------------------------------------
# UA / IP primitives
# ---------------------------------------------------------------------------


class TestCompanionUA:
    def test_matches_canonical_home_assistant_android_ua(self):
        ua = "Home Assistant/2026.5.4-12345 (Android 14) Mozilla/5.0"
        assert is_companion_ua(ua) is True

    def test_matches_hacompanion_variant(self):
        ua = "Mozilla/5.0 (Linux; Android 13) HACompanion/2026.4.1"
        assert is_companion_ua(ua) is True

    def test_matches_hass_variant(self):
        ua = "Mozilla/5.0 (Android 12) Hass/2026.3"
        assert is_companion_ua(ua) is True

    def test_rejects_desktop_chrome(self):
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/123"
        assert is_companion_ua(ua) is False

    def test_rejects_ios_companion(self):
        ua = "Home Assistant/2026.5.4 (iOS 17.5)"
        assert is_companion_ua(ua) is False  # no "Android" — different bridge

    def test_rejects_curl_user_agent(self):
        assert is_companion_ua("curl/8.4.0") is False

    def test_handles_missing_ua(self):
        assert is_companion_ua(None) is False
        assert is_companion_ua("") is False


class TestLocalRemote:
    @pytest.mark.parametrize(
        "ip",
        [
            "192.168.1.5",
            "192.168.255.255",
            "10.0.0.1",
            "10.255.255.255",
            "172.16.0.1",
            "172.31.255.254",
            "127.0.0.1",
            "::1",
            "fc00::1",
            "fd12:3456:789a::1",
        ],
    )
    def test_accepts_private_and_loopback(self, ip):
        assert is_local_remote(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "172.32.0.1",  # outside 172.16/12
            "11.0.0.1",
            "2001:db8::1",
        ],
    )
    def test_rejects_public_internet(self, ip):
        assert is_local_remote(ip) is False

    def test_handles_ipv6_mapped_ipv4(self):
        # aiohttp can hand us "::ffff:192.168.1.5"; range check the v4 inside.
        assert is_local_remote("::ffff:192.168.1.5") is True
        assert is_local_remote("::ffff:8.8.8.8") is False

    def test_handles_missing_or_invalid(self):
        assert is_local_remote(None) is False
        assert is_local_remote("") is False
        assert is_local_remote("not-an-ip") is False


# ---------------------------------------------------------------------------
# Composite trust decision
# ---------------------------------------------------------------------------


def _request(ua: str | None, remote: str | None, auth: str | None = None) -> MagicMock:
    headers = {}
    if ua is not None:
        headers["User-Agent"] = ua
    if auth is not None:
        headers["Authorization"] = auth
    request = MagicMock()
    request.headers = headers
    request.remote = remote
    return request


class TestIsCompanionTrustedRequest:
    def test_companion_ua_plus_local_net_is_trusted(self):
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_companion_trusted_request(req) is True

    def test_companion_ua_but_public_remote_is_not_trusted(self):
        # UA-spoof from the public internet must not gain admin access.
        req = _request("Home Assistant/2026 (Android 14)", "8.8.8.8")
        assert is_companion_trusted_request(req) is False

    def test_desktop_ua_on_local_net_is_not_trusted(self):
        # Local-net alone isn't enough — must look like Companion.
        req = _request(
            "Mozilla/5.0 (Macintosh) Safari/17", "192.168.1.5"
        )
        assert is_companion_trusted_request(req) is False

    def test_missing_ua_is_not_trusted(self):
        req = _request(None, "192.168.1.5")
        assert is_companion_trusted_request(req) is False


class TestIsCompanionTrustedMeta:
    def test_accepts_stashed_meta_with_companion_signature(self):
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "192.168.1.5"}
        assert is_companion_trusted_meta(meta) is True

    def test_rejects_public_remote(self):
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "8.8.8.8"}
        assert is_companion_trusted_meta(meta) is False

    def test_rejects_empty_meta(self):
        assert is_companion_trusted_meta(None) is False
        assert is_companion_trusted_meta({}) is False


# ---------------------------------------------------------------------------
# Full HTTP authorization path
# ---------------------------------------------------------------------------


def _hass_with_token(valid_token: str | None) -> MagicMock:
    hass = MagicMock()

    def _validate(token):
        if valid_token is not None and token == valid_token:
            return MagicMock()  # represents a RefreshToken
        return None

    hass.auth.async_validate_access_token.side_effect = _validate
    return hass


class TestIsAuthorizedHttp:
    async def test_valid_bearer_authorizes_any_origin(self):
        # Path 1 (Bearer) does not depend on UA / remote — same behavior as
        # HA's own requires_auth=True middleware.
        req = _request(
            "Mozilla/5.0 (Macintosh) Safari/17",
            "203.0.113.5",  # public IP — doesn't matter for Bearer path
            auth="Bearer good-token",
        )
        hass = _hass_with_token("good-token")
        assert await is_authorized_http(req, hass) is True

    async def test_invalid_bearer_falls_through_to_companion_path(self):
        # Bearer is well-formed but HA auth manager rejects it. Companion
        # signature should still rescue the request when valid.
        req = _request(
            "Home Assistant/2026 (Android 14)",
            "192.168.1.5",
            auth="Bearer not-a-real-token",
        )
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is True

    async def test_invalid_bearer_and_no_companion_returns_false(self):
        req = _request(
            "Mozilla/5.0 (Macintosh) Safari/17",
            "192.168.1.5",
            auth="Bearer not-a-real-token",
        )
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is False

    async def test_no_bearer_companion_local_authorizes(self):
        # The #1131 happy path — Companion fails to attach a token, server
        # picks up the request via UA + RFC1918.
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is True

    async def test_no_bearer_companion_public_remote_rejects(self):
        # An attacker spoofing UA from the internet must NOT get access.
        req = _request("Home Assistant/2026 (Android 14)", "8.8.8.8")
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is False

    async def test_no_bearer_desktop_local_rejects(self):
        # Desktop user without a token stays 401 — no Companion-UA, no bypass.
        req = _request("Mozilla/5.0 (Macintosh) Safari/17", "192.168.1.5")
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is False

    async def test_no_bearer_no_ua_no_remote_rejects(self):
        req = _request(None, None)
        hass = _hass_with_token(None)
        assert await is_authorized_http(req, hass) is False


class TestExtractRequestMeta:
    def test_captures_ua_and_remote(self):
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        meta = extract_request_meta(req)
        assert meta == {"ua": "Home Assistant/2026 (Android 14)", "remote": "192.168.1.5"}

    def test_handles_missing_ua_header(self):
        req = _request(None, "192.168.1.5")
        meta = extract_request_meta(req)
        assert meta["ua"] is None
        assert meta["remote"] == "192.168.1.5"
