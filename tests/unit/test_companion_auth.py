"""Tests for the HA Android Companion auth-bypass (#1131, hardened in #1357)."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from custom_components.beatify.const import DOMAIN
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
            "fc00::1",
            "fd12:3456:789a::1",
        ],
    )
    def test_accepts_private(self, ip):
        assert is_local_remote(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "8.8.8.8",
            "1.1.1.1",
            "172.32.0.1",  # outside 172.16/12
            "11.0.0.1",
            "2001:db8::1",
            # #1357: loopback is NO LONGER trusted — only proxies/tunnels
            # (snitun, reverse proxies) connect from loopback, never a real
            # Companion WebView.
            "127.0.0.1",
            "::1",
        ],
    )
    def test_rejects_public_and_loopback(self, ip):
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
# hass helpers (#1357 — bypass is gated on hass.data live flag)
# ---------------------------------------------------------------------------


def _hass(*, bypass_enabled: bool = True, valid_token: str | None = None) -> MagicMock:
    """Build a hass mock with the #1357 bypass flag set in hass.data."""
    hass = MagicMock()
    hass.data = {DOMAIN: {"companion_auth_bypass_enabled": bypass_enabled}}

    def _validate(token):
        if valid_token is not None and token == valid_token:
            return MagicMock()  # represents a RefreshToken
        return None

    hass.auth.async_validate_access_token.side_effect = _validate
    return hass


@pytest.fixture
def _fake_cloud_not_connected():
    """Inject a fake homeassistant.components.cloud whose is_cloud_connection -> False.

    ``homeassistant.components.cloud`` is NOT stubbed in conftest.py, so the
    lazy import in companion_auth would otherwise raise (caught by the
    except-pass). For the "trusted" cases we inject a benign module so the
    cloud check runs and returns False (request is not cloud-tunnelled).
    """
    mod = ModuleType("homeassistant.components.cloud")
    mod.is_cloud_connection = lambda hass: False  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.cloud"] = mod
    try:
        yield
    finally:
        sys.modules.pop("homeassistant.components.cloud", None)


@pytest.fixture
def _fake_cloud_connected():
    """Inject a fake homeassistant.components.cloud whose is_cloud_connection -> True."""
    mod = ModuleType("homeassistant.components.cloud")
    mod.is_cloud_connection = lambda hass: True  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.cloud"] = mod
    try:
        yield
    finally:
        sys.modules.pop("homeassistant.components.cloud", None)


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
    def test_companion_ua_plus_local_net_is_trusted(self, _fake_cloud_not_connected):
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_companion_trusted_request(req, _hass()) is True

    def test_companion_ua_but_public_remote_is_not_trusted(
        self, _fake_cloud_not_connected
    ):
        # UA-spoof from the public internet must not gain admin access.
        req = _request("Home Assistant/2026 (Android 14)", "8.8.8.8")
        assert is_companion_trusted_request(req, _hass()) is False

    def test_desktop_ua_on_local_net_is_not_trusted(self, _fake_cloud_not_connected):
        # Local-net alone isn't enough — must look like Companion.
        req = _request("Mozilla/5.0 (Macintosh) Safari/17", "192.168.1.5")
        assert is_companion_trusted_request(req, _hass()) is False

    def test_missing_ua_is_not_trusted(self, _fake_cloud_not_connected):
        req = _request(None, "192.168.1.5")
        assert is_companion_trusted_request(req, _hass()) is False

    def test_loopback_remote_is_not_trusted(self, _fake_cloud_not_connected):
        # #1357: a request arriving from 127.0.0.1 (snitun / reverse proxy)
        # with a perfect Companion UA must NOT be trusted.
        req = _request("Home Assistant/2026 (Android 14)", "127.0.0.1")
        assert is_companion_trusted_request(req, _hass()) is False

    def test_bypass_disabled_rejects_perfect_companion(self):
        # #1357: with the opt-in flag OFF (default), even a perfect Companion
        # UA + LAN IP is rejected. No cloud module is injected — the disabled
        # gate short-circuits before the lazy import is reached.
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_companion_trusted_request(req, _hass(bypass_enabled=False)) is False

    def test_bypass_enabled_but_cloud_connection_rejected(self, _fake_cloud_connected):
        # #1357: bypass on, perfect Companion signature, but the request is a
        # Nabu Casa cloud-tunnelled request -> refuse.
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_companion_trusted_request(req, _hass()) is False

    def test_cloud_import_unavailable_falls_through(self):
        # #1357: when homeassistant.components.cloud is not importable (the
        # default test env), the except-pass lets the UA + IP check proceed.
        assert "homeassistant.components.cloud" not in sys.modules
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_companion_trusted_request(req, _hass()) is True


class TestIsCompanionTrustedMeta:
    def test_accepts_stashed_meta_with_companion_signature(self):
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "192.168.1.5"}
        assert is_companion_trusted_meta(meta, _hass()) is True

    def test_rejects_public_remote(self):
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "8.8.8.8"}
        assert is_companion_trusted_meta(meta, _hass()) is False

    def test_rejects_loopback_remote(self):
        # #1357: loopback no longer trusted on the WS path either.
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "127.0.0.1"}
        assert is_companion_trusted_meta(meta, _hass()) is False

    def test_rejects_empty_meta(self):
        assert is_companion_trusted_meta(None, _hass()) is False
        assert is_companion_trusted_meta({}, _hass()) is False

    def test_bypass_disabled_rejects_perfect_companion(self):
        # #1357: opt-in gate also guards the WS path.
        meta = {"ua": "Home Assistant/2026 (Android 14)", "remote": "192.168.1.5"}
        assert is_companion_trusted_meta(meta, _hass(bypass_enabled=False)) is False


# ---------------------------------------------------------------------------
# Full HTTP authorization path
# ---------------------------------------------------------------------------


class TestIsAuthorizedHttp:
    async def test_valid_bearer_authorizes_any_origin(self):
        # Path 1 (Bearer) does not depend on UA / remote — same behavior as
        # HA's own requires_auth=True middleware. Does not consult the bypass,
        # so no cloud module / bypass flag is needed.
        req = _request(
            "Mozilla/5.0 (Macintosh) Safari/17",
            "203.0.113.5",  # public IP — doesn't matter for Bearer path
            auth="Bearer good-token",
        )
        hass = _hass(bypass_enabled=False, valid_token="good-token")
        assert is_authorized_http(req, hass) is True

    async def test_invalid_bearer_falls_through_to_companion_path(
        self, _fake_cloud_not_connected
    ):
        # Bearer is well-formed but HA auth manager rejects it. Companion
        # signature should still rescue the request when the bypass is enabled.
        req = _request(
            "Home Assistant/2026 (Android 14)",
            "192.168.1.5",
            auth="Bearer not-a-real-token",
        )
        assert is_authorized_http(req, _hass()) is True

    async def test_invalid_bearer_and_no_companion_returns_false(
        self, _fake_cloud_not_connected
    ):
        req = _request(
            "Mozilla/5.0 (Macintosh) Safari/17",
            "192.168.1.5",
            auth="Bearer not-a-real-token",
        )
        assert is_authorized_http(req, _hass()) is False

    async def test_no_bearer_companion_local_authorizes(
        self, _fake_cloud_not_connected
    ):
        # The #1131 happy path — Companion fails to attach a token, server
        # picks up the request via UA + RFC1918 (bypass enabled).
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_authorized_http(req, _hass()) is True

    async def test_no_bearer_companion_public_remote_rejects(
        self, _fake_cloud_not_connected
    ):
        # An attacker spoofing UA from the internet must NOT get access.
        req = _request("Home Assistant/2026 (Android 14)", "8.8.8.8")
        assert is_authorized_http(req, _hass()) is False

    async def test_no_bearer_desktop_local_rejects(self, _fake_cloud_not_connected):
        # Desktop user without a token stays 401 — no Companion-UA, no bypass.
        req = _request("Mozilla/5.0 (Macintosh) Safari/17", "192.168.1.5")
        assert is_authorized_http(req, _hass()) is False

    async def test_no_bearer_no_ua_no_remote_rejects(self, _fake_cloud_not_connected):
        req = _request(None, None)
        assert is_authorized_http(req, _hass()) is False

    async def test_bypass_disabled_rejects_companion(self):
        # #1357: with the opt-in flag OFF, the Companion fallback is dead.
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        assert is_authorized_http(req, _hass(bypass_enabled=False)) is False


class TestExtractRequestMeta:
    def test_captures_ua_and_remote(self):
        req = _request("Home Assistant/2026 (Android 14)", "192.168.1.5")
        meta = extract_request_meta(req)
        assert meta == {
            "ua": "Home Assistant/2026 (Android 14)",
            "remote": "192.168.1.5",
        }

    def test_handles_missing_ua_header(self):
        req = _request(None, "192.168.1.5")
        meta = extract_request_meta(req)
        assert meta["ua"] is None
        assert meta["remote"] == "192.168.1.5"
