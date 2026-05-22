"""Tests for the shared _json_error helper (#1097 / rc16).

The body shape changed in rc16: it now sets the code under both ``code``
and ``error``. Frontend code (admin.js) reads ``data.code``; before rc16
the helper only set ``error``, so the GAME_IN_LOBBY auto-recovery and
i18n-by-code lookup were both silently dead.
"""

from __future__ import annotations

import json

import pytest

from custom_components.beatify.server.base import _json_error


class TestJsonError:
    @pytest.mark.asyncio
    async def test_body_includes_code_field_for_frontend(self):
        # admin.js:1998 / :2006 read data.code. rc15 and earlier only set
        # ``error`` — those branches never fired. rc16 emits both keys so
        # ``data.code`` works without breaking anything still reading
        # ``data.error``.
        resp = _json_error("Test message", 409, code="TEST_CODE")
        body = json.loads(resp.body)
        assert body["code"] == "TEST_CODE"
        assert body["message"] == "Test message"

    @pytest.mark.asyncio
    async def test_body_keeps_legacy_error_field_for_backcompat(self):
        # Anything still reading data.error from older builds keeps working.
        resp = _json_error("Test message", 409, code="TEST_CODE")
        body = json.loads(resp.body)
        assert body["error"] == "TEST_CODE"

    @pytest.mark.asyncio
    async def test_default_code_is_generic_error(self):
        resp = _json_error("Boom", 500)
        body = json.loads(resp.body)
        assert body["code"] == "ERROR"
        assert body["error"] == "ERROR"

    @pytest.mark.asyncio
    async def test_status_code_is_set(self):
        resp = _json_error("Bad input", 400, code="INVALID_REQUEST")
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_game_in_lobby_response_shape(self):
        # The specific case from #1097: ensure the GAME_IN_LOBBY response
        # body carries `code` so admin.js's auto-recovery and i18n lookup
        # both light up.
        resp = _json_error(
            "A game is already in the lobby — start gameplay instead",
            409,
            code="GAME_IN_LOBBY",
        )
        body = json.loads(resp.body)
        assert body["code"] == "GAME_IN_LOBBY"
        assert body["message"].startswith("A game is already in the lobby")
