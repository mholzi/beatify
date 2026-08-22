"""Tests for the shared _json_error helper (#1097 / rc16).

The body shape changed in rc16: it now sets the code under both ``code``
and ``error``. Frontend code (admin.js) reads ``data.code``; before rc16
the helper only set ``error``, so the GAME_IN_LOBBY auto-recovery and
i18n-by-code lookup were both silently dead.
"""

from __future__ import annotations

import json
import logging

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


class TestJsonErrorLogging:
    """#2294 — every error response must leave a trace.

    Before this, all 33 call sites returned silently. On 2026-08-21 a host
    could not start a game for an evening: the banner showed the one generic
    string that twelve different rejections share, and ``system_log`` held
    zero Beatify entries. The reason — "Media player is unavailable" — was
    known inside this helper and written nowhere.
    """

    @pytest.mark.asyncio
    async def test_logs_status_code_and_message(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="custom_components.beatify.server.base"
        ):
            _json_error("Media player is unavailable", 400, code="INVALID_REQUEST")
        assert "400" in caplog.text
        assert "INVALID_REQUEST" in caplog.text
        # The message is the whole point: the code alone cannot distinguish
        # this from "No playlists selected".
        assert "Media player is unavailable" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_at_warning_so_system_log_collects_it(self, caplog):
        # Home Assistant's system_log — Settings > System > Logs, and the
        # first place anyone looks — only collects WARNING and above. An INFO
        # line would have been exactly as invisible as no line at all.
        with caplog.at_level(
            logging.DEBUG, logger="custom_components.beatify.server.base"
        ):
            _json_error("Media player is unavailable", 400, code="INVALID_REQUEST")
        records = [r for r in caplog.records if "INVALID_REQUEST" in r.getMessage()]
        assert records, "the error response produced no log record at all"
        assert all(r.levelno >= logging.WARNING for r in records)

    @pytest.mark.asyncio
    async def test_two_rejections_sharing_a_code_are_distinguishable_in_the_log(
        self, caplog
    ):
        with caplog.at_level(
            logging.WARNING, logger="custom_components.beatify.server.base"
        ):
            _json_error("Media player is unavailable", 400, code="INVALID_REQUEST")
            _json_error("No playlists selected", 400, code="INVALID_REQUEST")
        assert "Media player is unavailable" in caplog.text
        assert "No playlists selected" in caplog.text

    @pytest.mark.asyncio
    async def test_logging_does_not_change_the_response_body(self, caplog):
        resp = _json_error("Test message", 409, code="TEST_CODE", details={"extra": 1})
        body = json.loads(resp.body)
        assert body == {
            "code": "TEST_CODE",
            "error": "TEST_CODE",
            "message": "Test message",
            "extra": 1,
        }
        assert resp.status == 409
