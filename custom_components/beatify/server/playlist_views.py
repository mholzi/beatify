"""Playlist-related HTTP views for Beatify."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.beatify.server.base import (
    RateLimitMixin,
    _json_error,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Labels that mean a closed request was turned down rather than delivered.
_DECLINED_LABELS = frozenset(
    {"declined", "wont-fix", "wontfix", "duplicate", "invalid"}
)
# Optional vX.Y.Z label the maintainer may add to record the shipping release.
_VERSION_LABEL_RE = re.compile(r"^v?(\d+\.\d+\.\d+\S*)$")


def _issue_to_status(
    state: str, state_reason: str, labels: list[str]
) -> tuple[str, str | None]:
    """Map a GitHub issue's state + close reason + labels to a request status.

    The issue STATE is the source of truth, not a specific label: any
    closed request issue counts as delivered unless it was closed as "not
    planned" or carries a decline label. This is deliberate — the old
    browser poller only recognised a `playlist-ready` + `vX.Y.Z` label
    pair, so requests the maintainer closed with `approved` (the actual
    habit) never advanced past "submitted".

    Honouring GitHub's `not_planned` close reason (follow-up to #970) means
    a maintainer can decline a request just by closing it that way — a
    declined request would otherwise show the user a misleading "ready"
    status unless a decline label was added by hand. Returns
    (status, release_version | None).
    """
    if state != "closed":
        return "pending", None
    if state_reason == "not_planned" or any(
        label.lower() in _DECLINED_LABELS for label in labels
    ):
        return "declined", None
    version: str | None = None
    for label in labels:
        match = _VERSION_LABEL_RE.match(label.strip())
        if match:
            version = match.group(1)
            break
    return "ready", version


class PlaylistRequestsView(RateLimitMixin, HomeAssistantView):
    """API for managing playlist requests (Story 44).

    Stores requests in a JSON file on the HA server so they persist
    across browser sessions and devices.
    """

    url = "/beatify/api/playlist-requests"
    name = "beatify:api:playlist-requests"
    requires_auth = False

    MAX_REQUESTS = 100
    MAX_FIELD_LENGTH = 500
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60  # seconds

    # Server-side status sync (#970). GET reconciles pending requests
    # against GitHub issue state, throttled to once an hour so a busy Hub
    # tab can't hammer GitHub's unauthenticated 60/hr-per-IP limit.
    GITHUB_ISSUES_API = "https://api.github.com/repos/mholzi/beatify/issues"
    POLL_INTERVAL_SECONDS = 3600
    POLL_TIMEOUT_SECONDS = 12

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._storage_path = Path(hass.config.path("beatify/playlist_requests.json"))
        self._init_rate_limits()

    def _sanitize_item(self, item: object) -> dict | None:
        """Validate and sanitize a single playlist request item."""
        if not isinstance(item, dict):
            return None
        sanitized = {}
        for key, value in item.items():
            if not isinstance(key, str) or len(key) > 50:
                continue
            if isinstance(value, str):
                sanitized[key] = value[: self.MAX_FIELD_LENGTH]
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
        return sanitized if sanitized else None

    def _load_requests(self) -> dict:
        """Load requests from storage file."""
        if self._storage_path.exists():
            try:
                return json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Failed to load playlist requests: %s", e)
        return {"requests": [], "last_poll": None}

    def _save_requests(self, data: dict) -> bool:
        """Save requests to storage file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to save playlist requests: %s", e)
            return False

    def _poll_due(self, data: dict) -> bool:
        """Return True if the GitHub status sync hasn't run within the interval."""
        last_poll = data.get("last_poll")
        if not last_poll:
            return True
        try:
            last = datetime.fromisoformat(str(last_poll).replace("Z", "+00:00"))
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        return elapsed >= self.POLL_INTERVAL_SECONDS

    async def _fetch_issue(
        self, session: object, issue_number: object
    ) -> tuple[str, str, list[str]] | None:
        """Fetch a GitHub issue's state, close reason and labels, or None on failure."""
        try:
            async with session.get(
                f"{self.GITHUB_ISSUES_API}/{issue_number}",
                headers={"Accept": "application/vnd.github+json"},
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Playlist-request poll: issue %s returned HTTP %s",
                        issue_number,
                        resp.status,
                    )
                    return None
                issue = await resp.json()
            labels = [
                label.get("name", "")
                for label in issue.get("labels", [])
                if isinstance(label, dict)
            ]
            return issue.get("state", ""), issue.get("state_reason") or "", labels
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Playlist-request poll: issue %s failed: %s", issue_number, err
            )
            return None

    async def _poll_statuses(self, data: dict) -> dict:
        """Reconcile pending request statuses against GitHub issue state (#970).

        Stamps `last_poll` whenever a poll is attempted — even if there is
        nothing pending or GitHub is unreachable — so a failure backs off
        for the full interval instead of retrying on every Hub open.
        """
        now = datetime.now(timezone.utc).isoformat()
        data["last_poll"] = now

        requests = data.get("requests", [])
        pending = [
            r
            for r in requests
            if isinstance(r, dict)
            and r.get("issue_number")
            and r.get("status") in (None, "", "pending", "ready")
        ]
        if not pending:
            return data

        session = async_get_clientsession(self.hass)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    *(self._fetch_issue(session, r["issue_number"]) for r in pending)
                ),
                timeout=self.POLL_TIMEOUT_SECONDS,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Playlist-request poll aborted: %s", err)
            return data

        for req, result in zip(pending, results):
            if result is None:
                continue
            state, state_reason, labels = result
            status, version = _issue_to_status(state, state_reason, labels)
            req["status"] = status
            req["last_checked"] = now
            if version:
                req["release_version"] = version
        return data

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Get all playlist requests, refreshing statuses from GitHub if due."""
        data = await self.hass.async_add_executor_job(self._load_requests)
        if self._poll_due(data):
            try:
                data = await self._poll_statuses(data)
                await self.hass.async_add_executor_job(self._save_requests, data)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Playlist-request status poll failed: %s", err)
        return web.json_response(data)

    async def post(self, request: web.Request) -> web.Response:
        """Save playlist requests (replaces all data)."""
        # Rate limiting
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        try:
            # #937: do NOT pass `content_type=` here — aiohttp 3.11+ removed
            # that parameter from Request.json(). Passing it raised TypeError
            # on every call, which the broad except below mislabelled as
            # "Invalid JSON" — so every playlist-request save 400'd. Modern
            # json() already parses without a content-type check, which is
            # exactly what `content_type=None` was meant to achieve.
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        # Validate data structure
        if not isinstance(body.get("requests"), list):
            return _json_error(
                "Missing or invalid requests array", 400, code="INVALID_REQUEST"
            )

        raw_requests = body["requests"][: self.MAX_REQUESTS]

        # Sanitize each item
        sanitized = []
        for item in raw_requests:
            clean = self._sanitize_item(item)
            if clean is not None:
                sanitized.append(clean)

        # Build storage object
        data = {
            "requests": sanitized,
            "last_poll": body.get("last_poll"),
        }

        # Save to file
        success = await self.hass.async_add_executor_job(self._save_requests, data)
        if not success:
            return _json_error("Failed to save request", 500, code="SAVE_FAILED")

        return web.json_response({"success": True, "requests": data["requests"]})
