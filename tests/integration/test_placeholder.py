"""
Integration tests — WebSocket layer and full-stack flows.

Planned as part of Issue #197 (Test Coverage: Game Logic & WebSocket Layer).
These tests require a running Home Assistant instance and are tracked separately.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Integration tests not yet implemented — tracked in #197")
def test_websocket_connect_disconnect() -> None:
    """Placeholder: WebSocket connect / disconnect lifecycle."""


@pytest.mark.skip(reason="Integration tests not yet implemented — tracked in #197")
def test_websocket_state_sync() -> None:
    """Placeholder: State sync between server and connected clients."""
