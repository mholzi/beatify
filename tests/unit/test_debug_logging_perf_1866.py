"""#1866 — `custom_components.beatify: debug` must not cost 50-500x.

Two regressions are pinned here:

1. The media-player compatibility scan runs on every ``/beatify/api/status``
   call (the admin polls it every ~3 s) and used to re-emit a DEBUG line per
   skipped entity every time. HA writes log records synchronously on the event
   loop, so that starved the round timer (#1865).
2. ``[Companion-Debug]`` (per HTTP request) and ``[WS-Debug]`` (per WS frame)
   must not be reachable via ``custom_components.beatify: debug`` at all — they
   live on an opt-in wire logger.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import (
    _reset_scan_log_state,
    async_get_media_players,
)
from custom_components.beatify.wire_debug import (
    WIRE_DEFAULT_LEVEL,
    WIRE_LOGGER_NAME,
    get_wire_logger,
)

SCAN_LOGGER = "custom_components.beatify.services.media_player"


def _entry(entity_id: str, platform: str, unique_id: str | None) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.unique_id = unique_id
    entry.domain = "media_player"
    return entry


def _state(entity_id: str) -> MagicMock:
    state = MagicMock()
    state.entity_id = entity_id
    state.state = "idle"
    state.attributes = {"friendly_name": entity_id}
    return state


def _hass_and_registry(entries: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
    by_id = {e.entity_id: e for e in entries}
    hass = MagicMock()
    hass.states.async_all = MagicMock(
        return_value=[_state(e.entity_id) for e in entries]
    )
    registry = MagicMock()
    registry.entities.values = MagicMock(return_value=list(entries))
    registry.async_get = MagicMock(side_effect=lambda eid: by_id.get(eid))
    return hass, registry


async def _scan(entries: list[MagicMock]) -> list[dict]:
    hass, registry = _hass_and_registry(entries)
    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=registry,
    ):
        return await async_get_media_players(hass)


def _skip_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == SCAN_LOGGER]


@pytest.fixture(autouse=True)
def _clean_scan_cache():
    """The dedup cache is module state — never leak it between tests."""
    _reset_scan_log_state()
    yield
    _reset_scan_log_state()


# An unsupported platform (raw Cast without MA) and an MA twin pair — the two
# skip reasons the scan logs.
UNSUPPORTED = _entry("media_player.tv_cast", "cast", "cast-1")
MA_TWIN = _entry("media_player.kuche_2", "music_assistant", "RINCON_1")
NATIVE_TWIN = _entry("media_player.kuche", "sonos", "RINCON_1")


class TestCompatScanLogsOncePerEntity:
    """The static skip reasons are logged on change, not on every poll (#1866)."""

    @pytest.mark.asyncio
    async def test_repeated_scans_log_skip_reason_once(self, caplog):
        entries = [UNSUPPORTED, MA_TWIN, NATIVE_TWIN]
        with caplog.at_level(logging.DEBUG, logger=SCAN_LOGGER):
            for _ in range(5):
                result = await _scan(entries)

        # Behaviour is unchanged: only the MA twin survives the scan.
        assert {p["entity_id"] for p in result} == {"media_player.kuche_2"}

        lines = _skip_lines(caplog)
        assert sum("Skipping unsupported player" in ln for ln in lines) == 1
        assert sum("Skipping native twin" in ln for ln in lines) == 1
        # ...and the summary line likewise, since the count never moved.
        assert sum("Found 1 compatible media players" in ln for ln in lines) == 1

    @pytest.mark.asyncio
    async def test_changed_reason_is_logged_again(self, caplog):
        """A skip reason that actually changes must resurface."""
        moved = _entry("media_player.tv_cast", "cast", "cast-1")
        with caplog.at_level(logging.DEBUG, logger=SCAN_LOGGER):
            await _scan([moved])
            moved.platform = "androidtv_remote"  # different reason, same entity
            await _scan([moved])

        skips = [ln for ln in _skip_lines(caplog) if "Skipping unsupported" in ln]
        assert len(skips) == 2
        assert "platform=cast" in skips[0]
        assert "platform=androidtv_remote" in skips[1]

    @pytest.mark.asyncio
    async def test_count_line_follows_the_count(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=SCAN_LOGGER):
            await _scan([MA_TWIN])
            await _scan([MA_TWIN])
            await _scan([MA_TWIN, _entry("media_player.bad", "music_assistant", "u2")])

        counts = [ln for ln in _skip_lines(caplog) if "compatible media players" in ln]
        assert counts == [
            "Found 1 compatible media players",
            "Found 2 compatible media players",
        ]

    @pytest.mark.asyncio
    async def test_removed_entity_logs_again_when_it_returns(self, caplog):
        """Stale cache entries are pruned, so a re-added entity is not silent."""
        with caplog.at_level(logging.DEBUG, logger=SCAN_LOGGER):
            await _scan([UNSUPPORTED, MA_TWIN])
            await _scan([MA_TWIN])  # cast player disappears → prune
            await _scan([UNSUPPORTED, MA_TWIN])  # comes back → log again

        skips = [ln for ln in _skip_lines(caplog) if "Skipping unsupported" in ln]
        assert len(skips) == 2

    @pytest.mark.asyncio
    async def test_scans_while_debug_off_do_not_poison_the_cache(self, caplog):
        """Turning debug ON later must still produce the full picture.

        This is the whole point of the feature: a user enables debug *because*
        something is wrong. If quiet scans had populated the cache, they would
        see nothing until an entity changed.
        """
        entries = [UNSUPPORTED, MA_TWIN, NATIVE_TWIN]
        with caplog.at_level(logging.WARNING, logger=SCAN_LOGGER):
            for _ in range(3):
                await _scan(entries)
            assert _skip_lines(caplog) == []

        with caplog.at_level(logging.DEBUG, logger=SCAN_LOGGER):
            await _scan(entries)

        lines = _skip_lines(caplog)
        assert any("Skipping unsupported player" in ln for ln in lines)
        assert any("Skipping native twin" in ln for ln in lines)


class TestWireLoggerIsOptIn:
    """Per-request / per-frame lines are NOT part of `beatify: debug` (#1866)."""

    def test_wire_logger_carries_an_explicit_level(self):
        """Without its own level it would inherit the parent's DEBUG."""
        wire = get_wire_logger()
        assert wire.name == WIRE_LOGGER_NAME
        assert wire.level == WIRE_DEFAULT_LEVEL
        assert wire.level > logging.DEBUG

    def test_parent_debug_does_not_enable_the_wire_logger(self):
        """`custom_components.beatify: debug` must leave wire traffic off."""
        parent = logging.getLogger("custom_components.beatify")
        previous = parent.level
        try:
            parent.setLevel(logging.DEBUG)
            assert not get_wire_logger().isEnabledFor(logging.DEBUG)
        finally:
            parent.setLevel(previous)

    def test_naming_the_wire_logger_directly_turns_it_on(self):
        """The documented opt-in must actually work."""
        wire = get_wire_logger()
        previous = wire.level
        try:
            wire.setLevel(logging.DEBUG)
            assert wire.isEnabledFor(logging.DEBUG)
        finally:
            wire.setLevel(previous)

    def test_companion_and_ws_debug_lines_use_the_wire_logger(self):
        """Guards against a future edit reattaching them to the module logger."""
        from custom_components.beatify.server import companion_auth, websocket

        for module in (companion_auth, websocket):
            source = (
                __import__("pathlib").Path(module.__file__).read_text(encoding="utf-8")
            )
            for tag in ("[Companion-Debug]", "[WS-Debug]"):
                for idx, line in enumerate(source.splitlines()):
                    if tag not in line:
                        continue
                    # Walk back to the logging call that owns this message.
                    call = next(
                        source.splitlines()[i]
                        for i in range(idx, -1, -1)
                        if "_LOGGER.debug(" in source.splitlines()[i]
                    )
                    assert "_WIRE_LOGGER.debug(" in call, (
                        f"{module.__name__}: {tag} still logs to the module logger"
                    )
