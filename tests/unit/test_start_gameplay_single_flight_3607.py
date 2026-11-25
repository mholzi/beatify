"""#3607: a second start after a rematch must not surface a 409 to the host.

startGameplay() only disabled its button after an awaited lobby update, so a
second tap/handler in that window sent a second start_game. admin.js cannot be
imported in vitest (DOM globals), so these are source guards.
"""

from __future__ import annotations

from pathlib import Path

JS = Path(__file__).parents[2] / "custom_components/beatify/www/js"


def test_start_gameplay_guards_before_the_awaited_lobby_update():
    src = (JS / "admin.js").read_text(encoding="utf-8")
    body = src[src.index("async function startGameplay()") :]
    body = body[: body.index("async function startGameplayInner")]
    assert "_gameplayStartInFlight" in body
    inner = src[src.index("async function startGameplayInner") :]
    assert inner.index("await postLobbyUpdate") < inner.index("start_game")


def test_player_lobby_ignores_already_started():
    src = (JS / "player-lobby.js").read_text(encoding="utf-8")
    body = src[src.index("export function handleStartFailure") :]
    assert "ALREADY_STARTED" in body[: body.index("startBtn.disabled = false")]
