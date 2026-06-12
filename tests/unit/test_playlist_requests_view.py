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
from datetime import datetime, timezone
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from aiohttp import StreamReader
from aiohttp.test_utils import make_mocked_request

from custom_components.beatify.server.playlist_views import _issue_to_status
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


def _authorized():
    """Patch is_authorized_http to allow the POST through (#1367)."""
    return mock.patch(
        "custom_components.beatify.server.playlist_views.is_authorized_http",
        new=MagicMock(return_value=True),
    )


class TestPlaylistRequestsPost:
    """POST must accept a valid JSON body — it 400'd unconditionally before #937."""

    async def test_valid_empty_body_is_saved(self):
        request = _request_with_body(b'{"requests": [], "last_poll": null}')
        with _authorized():
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
        with _authorized():
            resp = await _view().post(request)
        assert resp.status == 200
        assert json.loads(resp.body)["requests"][0]["issue_number"] == 1

    async def test_malformed_json_still_returns_400(self):
        # A genuinely broken body must still be rejected — that 400 is correct.
        request = _request_with_body(b"{not valid json")
        with _authorized():
            resp = await _view().post(request)
        assert resp.status == 400
        assert json.loads(resp.body)["error"] == "INVALID_REQUEST"


class TestPlaylistRequestsPostAuth:
    """#1367: POST rewrites the whole requests file, so it must require auth.

    Before the fix any unauthenticated client on the LAN (or via the Nabu Casa
    remote URL) could POST {"requests": []} to wipe every household request, or
    inject arbitrary entries — only IP rate limiting stood in the way.
    """

    async def test_unauthorized_post_is_rejected_401(self):
        request = _request_with_body(b'{"requests": [], "last_poll": null}')
        view = _view()
        with mock.patch(
            "custom_components.beatify.server.playlist_views.is_authorized_http",
            new=MagicMock(return_value=False),
        ):
            resp = await view.post(request)
        assert resp.status == 401
        assert json.loads(resp.body)["error"] == "UNAUTHORIZED"

    async def test_unauthorized_post_does_not_write_to_disk(self):
        # The wipe must be blocked before _save_requests is ever reached.
        request = _request_with_body(b'{"requests": [], "last_poll": null}')
        view = _view()
        with mock.patch(
            "custom_components.beatify.server.playlist_views.is_authorized_http",
            new=MagicMock(return_value=False),
        ):
            await view.post(request)
        view.hass.async_add_executor_job.assert_not_called()


# ---------------------------------------------------------------------------
# Server-side status sync (#970)
# ---------------------------------------------------------------------------


class TestIssueToStatus:
    """The issue STATE is the source of truth — not a specific label. A
    request closed as completed counts as delivered; one closed as "not
    planned" (or carrying a decline label) counts as declined."""

    def test_open_issue_is_pending(self):
        assert _issue_to_status("open", "", ["playlist-request"]) == ("pending", None)

    def test_closed_with_approved_is_delivered(self):
        # The exact case of #73 / #74 — closed with `approved`, never
        # `playlist-ready`. The old poller left these stuck on "submitted".
        assert _issue_to_status(
            "closed", "completed", ["playlist-request", "approved"]
        ) == ("ready", None)

    def test_closed_with_no_labels_is_delivered(self):
        assert _issue_to_status("closed", "completed", []) == ("ready", None)

    def test_closed_with_decline_label_is_declined(self):
        assert _issue_to_status("closed", "completed", ["wont-fix"]) == (
            "declined",
            None,
        )

    def test_closed_not_planned_is_declined(self):
        # A request the maintainer simply closed as "not planned", with no
        # decline label — must not show the user a misleading "ready".
        assert _issue_to_status("closed", "not_planned", []) == ("declined", None)
        assert _issue_to_status("closed", "not_planned", ["playlist-request"]) == (
            "declined",
            None,
        )

    def test_version_label_is_extracted(self):
        status, version = _issue_to_status(
            "closed", "completed", ["playlist-ready", "v3.3.6"]
        )
        assert status == "ready"
        assert version == "3.3.6"


def _get_view_with_store(store: dict) -> PlaylistRequestsView:
    """A view whose load/save are stubbed so get() runs against `store`."""
    hass = MagicMock()
    hass.config.path = MagicMock(return_value="/tmp/beatify-test/requests.json")
    # get() funnels both _load_requests and _save_requests through this.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    view = PlaylistRequestsView(hass)
    view._load_requests = MagicMock(return_value=store)
    view._save_requests = MagicMock(return_value=True)
    return view


def _get_request():
    return make_mocked_request("GET", "/beatify/api/playlist-requests")


class TestStatusSyncOnGet:
    """GET reconciles pending requests against GitHub, throttled by last_poll."""

    async def test_get_marks_closed_request_delivered(self):
        store = {
            "requests": [{"issue_number": 73, "status": "pending"}],
            "last_poll": None,
        }
        view = _get_view_with_store(store)
        view._fetch_issue = AsyncMock(
            return_value=("closed", "completed", ["approved"])
        )

        with mock.patch(
            "custom_components.beatify.server.playlist_views.async_get_clientsession",
            return_value=MagicMock(),
        ):
            resp = await view.get(_get_request())

        body = json.loads(resp.body)
        assert body["requests"][0]["status"] == "ready"
        assert body["last_poll"] is not None
        view._save_requests.assert_called_once()

    async def test_get_corrects_ready_to_declined_when_not_planned(self):
        # A request previously synced to "ready" must be re-polled and
        # corrected once the issue is seen as closed "not planned" — the
        # poller already re-checks "ready" rows, so the fix is retroactive.
        store = {
            "requests": [{"issue_number": 980, "status": "ready"}],
            "last_poll": None,
        }
        view = _get_view_with_store(store)
        view._fetch_issue = AsyncMock(return_value=("closed", "not_planned", []))

        with mock.patch(
            "custom_components.beatify.server.playlist_views.async_get_clientsession",
            return_value=MagicMock(),
        ):
            resp = await view.get(_get_request())

        assert json.loads(resp.body)["requests"][0]["status"] == "declined"

    async def test_get_skips_poll_when_recently_polled(self):
        store = {
            "requests": [{"issue_number": 73, "status": "pending"}],
            "last_poll": datetime.now(timezone.utc).isoformat(),
        }
        view = _get_view_with_store(store)
        view._fetch_issue = AsyncMock()

        resp = await view.get(_get_request())

        view._fetch_issue.assert_not_awaited()
        assert json.loads(resp.body)["requests"][0]["status"] == "pending"

    async def test_get_keeps_status_when_github_unreachable(self):
        store = {
            "requests": [{"issue_number": 73, "status": "pending"}],
            "last_poll": None,
        }
        view = _get_view_with_store(store)
        # _fetch_issue returning None == GitHub error / 403 / network failure.
        view._fetch_issue = AsyncMock(return_value=None)

        with mock.patch(
            "custom_components.beatify.server.playlist_views.async_get_clientsession",
            return_value=MagicMock(),
        ):
            resp = await view.get(_get_request())

        body = json.loads(resp.body)
        assert body["requests"][0]["status"] == "pending"
        # last_poll still stamped so a failure backs off for the full interval.
        assert body["last_poll"] is not None
