"""#3512: loopback /auth/token calls must carry the browser's Host header.

HA's IndieAuth ``verify_client_id`` accepts a client_id on a private IP
(RFC 1918, loopback, link-local) or a domain name unconditionally. Any other
IP (Tailscale/CGNAT 100.64/10, a global IPv6 address, a LAN on a public
range) is only accepted when the client_id's scheme + netloc equal the netloc
the token request was made to. Beatify posts to ``http://127.0.0.1:<port>``,
so without an explicit Host header HA compared against ``127.0.0.1:8123``,
rejected the client_id with "Invalid client id", and the admin page looped
on the login screen.

``_ha_accepts_client_id`` below mirrors HA's rule (homeassistant/components/
auth/indieauth.py ``_parse_client_id``) so the tests reproduce the failure
against what the loopback request actually sends.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from custom_components.beatify.server.views import (
    BeatifyAuthCallbackView,
    BeatifyAuthRefreshView,
)

_LOCAL_NETWORKS = (
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("fc00::/7"),
    ip_network("169.254.0.0/16"),
    ip_network("fe80::/10"),
)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _norm(scheme: str, netloc: str):
    parts = urlsplit(f"{scheme}://{netloc}")
    try:
        address = ip_address(parts.hostname or "")
    except ValueError:
        return None
    return (parts.scheme, address, parts.port or _DEFAULT_PORTS.get(parts.scheme))


def _ha_accepts_client_id(client_id: str, request_scheme: str, request_netloc: str):
    """Mirror of HA's IP rule in indieauth._parse_client_id."""
    parts = urlsplit(client_id)
    try:
        address = ip_address(parts.hostname or "")
    except ValueError:
        return True  # domain name
    if any(address in net for net in _LOCAL_NETWORKS if net.version == address.version):
        return True
    return _norm(request_scheme, request_netloc) == _norm(parts.scheme, parts.netloc)


def _hass() -> MagicMock:
    hass = MagicMock()
    hass.http.server_port = 8123
    hass.http.ssl_certificate = None
    return hass


class _Ctx:
    def __init__(self, text: str):
        self._text = text

    async def __aenter__(self):
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(return_value=self._text)
        return resp

    async def __aexit__(self, *exc):
        return False


def _session() -> MagicMock:
    session = MagicMock()
    session.post = MagicMock(
        return_value=_Ctx('{"access_token":"a","refresh_token":"r","expires_in":1800}')
    )
    return session


def _request(host: str, **extra) -> MagicMock:
    request = MagicMock()
    request.headers = {"Host": host, **extra.pop("headers", {})}
    request.scheme = "http"
    request.host = host
    request.query = extra.get("query", {})
    request.cookies = extra.get("cookies", {})
    return request


def _ha_view_of_call(session: MagicMock) -> tuple[str, str]:
    """Return (client_id, netloc HA sees) for the recorded loopback POST."""
    call = session.post.call_args
    loopback = urlsplit(call.args[0])
    netloc = call.kwargs["headers"].get("Host", loopback.netloc)
    client_id = parse_qs(call.kwargs["data"])["client_id"][0]
    return client_id, netloc


@pytest.mark.parametrize(
    "browser_host",
    ["100.101.102.103:8123", "[2a02:8070:1:2::5]:8123", "192.168.1.20:8123"],
)
@pytest.mark.asyncio
async def test_code_exchange_client_id_passes_ha_check(browser_host):
    session = _session()
    with patch(
        "custom_components.beatify.server.views.async_get_clientsession",
        return_value=session,
    ):
        resp = await BeatifyAuthCallbackView(_hass()).get(
            _request(browser_host, query={"code": "c", "state": "s"})
        )

    client_id, netloc = _ha_view_of_call(session)
    assert client_id == f"http://{browser_host}/beatify/"
    assert netloc == browser_host
    assert _ha_accepts_client_id(client_id, "http", netloc)
    assert "auth_error" not in resp.headers["Location"]


@pytest.mark.asyncio
async def test_refresh_client_id_passes_ha_check():
    session = _session()
    with patch(
        "custom_components.beatify.server.views.async_get_clientsession",
        return_value=session,
    ):
        resp = await BeatifyAuthRefreshView(_hass()).get(
            _request("100.101.102.103:8123", cookies={"beatify_refresh": "r"})
        )

    client_id, netloc = _ha_view_of_call(session)
    assert netloc == "100.101.102.103:8123"
    assert _ha_accepts_client_id(client_id, "http", netloc)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_forwarded_host_is_used_for_host_header():
    # Behind a proxy the client_id netloc comes from X-Forwarded-Host, so the
    # Host header must follow it to stay equal to the client_id netloc.
    session = _session()
    with patch(
        "custom_components.beatify.server.views.async_get_clientsession",
        return_value=session,
    ):
        await BeatifyAuthCallbackView(_hass()).get(
            _request(
                "ha.local:8123",
                headers={"X-Forwarded-Host": "xxx.ui.nabu.casa"},
                query={"code": "c"},
            )
        )

    client_id, netloc = _ha_view_of_call(session)
    assert urlsplit(client_id).netloc == netloc == "xxx.ui.nabu.casa"


def test_mirror_rejects_loopback_netloc_for_public_ip():
    # Guard the mirror itself: this is the exact pre-fix situation.
    assert not _ha_accepts_client_id(
        "http://100.101.102.103:8123/beatify/", "http", "127.0.0.1:8123"
    )
