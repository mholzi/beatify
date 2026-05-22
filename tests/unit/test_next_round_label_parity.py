"""Regression test for #1111 — admin browser and player view "Next Round"
control-bar buttons must use the same i18n label key.

Both buttons invoke the same `adminNextRound` handler and send the same
WebSocket `{type: admin, action: next_round}` message. The user-facing
label must match — historically the admin browser said "Skip" /
"Überspringen" which read as "skip this", not "advance round". A German
user (#1111, Max Lindner) didn't recognize the affordance and fell back
to End Game when their timer expired without all submissions.

This test pins the invariant: both buttons must reference the same
i18n key so the labels can't drift apart again.
"""

from __future__ import annotations

import re
from pathlib import Path

WWW = Path(__file__).parent.parent.parent / "custom_components" / "beatify" / "www"


def _data_i18n_for(html_path: Path, button_id: str) -> str:
    """Return the data-i18n attribute used by the .control-label inside the
    button with the given id. None if not found."""
    text = html_path.read_text(encoding="utf-8")
    # Find the <button id="..."> opening + the next .control-label data-i18n
    btn = re.search(
        rf'<button[^>]*id="{re.escape(button_id)}"[^>]*>(.*?)</button>',
        text,
        re.DOTALL,
    )
    assert btn, f"button #{button_id} not found in {html_path.name}"
    label_match = re.search(
        r'class="control-label"[^>]*data-i18n="([^"]+)"', btn.group(1)
    )
    return label_match.group(1) if label_match else None


def test_admin_browser_and_player_view_use_same_next_round_label():
    """#1111: the admin browser's control-bar advance button used to say
    'Skip' (admin.skipRound) while the player view's identical-function
    button said 'Next' (admin.next). Same handler, same WebSocket message,
    different label — German users didn't realize 'Überspringen' was the
    way to advance the round. Pin the two together."""
    admin_label = _data_i18n_for(WWW / "admin.html", "admin-skip-round")
    player_label = _data_i18n_for(WWW / "player.html", "next-round-admin-btn")

    assert admin_label == "admin.next", (
        f"admin browser control-bar advance button uses '{admin_label}'; "
        f"must use 'admin.next' to match the player view's same-function "
        f"button (regression of #1111)."
    )
    assert player_label == "admin.next", (
        f"player view control-bar advance button uses '{player_label}'; "
        f"must use 'admin.next' (regression of #1111)."
    )
    assert admin_label == player_label, (
        f"admin/player advance labels diverged: "
        f"admin='{admin_label}' vs player='{player_label}'. "
        f"Both buttons call the same adminNextRound handler — labels must "
        f"stay aligned so users on either side see the same affordance "
        f"text."
    )
