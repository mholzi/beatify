"""Tests for PlaylistRequestsView's POST handler (#937).

Before #937, POST /beatify/api/playlist-requests called
`request.json(content_type=None)`. aiohttp 3.11+ removed the `content_type`
parameter, so every call raised TypeError — masked by a broad except as
"Invalid JSON" — and every save 400'd. These tests drive the *real* aiohttp
`request.json()`, so a re-added `content_type=` kwarg would fail them again.
"""

from __future__ import annotations

import asyncio
import json
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from aiohttp import StreamReader
from aiohttp.test_utils import make_mocked_request

from custom_components.beatify.server.views import PlaylistRequestsView


def _request_with_body(body: bytes):
    """Build a POST request whose real `.json()` will read `body`."""
    reader = StreamReader(
        mock.Mock(_reading_paused=False), 2**16, loop=asyncio.get_event_loop()
    )
    reader.feed_data(body)
    reader.feed_eof()
    return make_mocked_request(
        "POST",
        "/beatify/api/playlist-requests",
        headers={"Content-Type": "application/json"},
        payload=reader,
    )


def _view() -> PlaylistRequestsView:
    """A view whose file save is stubbed out (no disk I/O in the test)."""
    hass = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/beatify-test/requests.json")
    # post() saves via async_add_executor_job(self._save_requests, data).
    hass.async_add_executor_job = AsyncMock(return_value=True)
    return PlaylistRequestsView(hass)


class TestPlaylistRequestsPost:
    """POST must accept a valid JSON body — it 400'd unconditionally before #937."""

    async def test_valid_empty_body_is_saved(self):
        request = _request_with_body(b'{"requests": [], "last_poll": null}')
        resp = await _view().post(request)
        # Regression: this returned 400 "Invalid JSON" for ALL bodies because
        # request.json(content_type=None) raised TypeError on aiohttp 3.11+.
        assert resp.status == 200
        assert json.loads(resp.body)["success"] is True

    async def test_valid_body_with_requests_is_saved(self):
        item = {"issue_number": 1, "playlist_name": "Test", "status": "pending"}
        request = _request_with_body(
            json.dumps({"requests": [item], "last_poll": None}).encode()
        )
        resp = await _view().post(request)
        assert resp.status == 200
        assert json.loads(resp.body)["requests"][0]["issue_number"] == 1

    async def test_malformed_json_still_returns_400(self):
        # A genuinely broken body must still be rejected — that 400 is correct.
        request = _request_with_body(b"{not valid json")
        resp = await _view().post(request)
        assert resp.status == 400
        assert json.loads(resp.body)["error"] == "INVALID_REQUEST"
