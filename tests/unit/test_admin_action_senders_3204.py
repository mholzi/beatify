"""Contract: every admin WebSocket action has a client sender (#3204).

``seek_forward`` lost its button during a UI rewrite and nobody noticed, because
the server-side handler kept working. This test reads the admin action table
and the shipped JS sources and fails when a table key has no
``action: '<key>'`` sender in ``www/js/**`` (tests and minified bundles
excluded). Delete the handler or restore the control; do not leave it dangling.
"""

from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"
ADMIN_PY = ROOT / "server" / "ws_handlers" / "admin.py"
JS_DIR = ROOT / "www" / "js"

# Actions that are legitimately sent some other way than a literal
# ``action: '<key>'`` in www/js. Keep this empty unless there is a real reason.
SENDER_ALLOWLIST: set[str] = set()


def _admin_action_keys() -> set[str]:
    """Return the keys of the ``admin_handlers`` dict in the admin dispatcher."""
    tree = ast.parse(ADMIN_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "admin_handlers"
                for t in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            return {
                k.value
                for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    msg = "admin_handlers dict not found in ws_handlers/admin.py"
    raise AssertionError(msg)


def _js_sources() -> str:
    parts = []
    for path in JS_DIR.rglob("*.js"):
        rel = path.relative_to(JS_DIR).parts
        if path.name.endswith(".min.js") or "__tests__" in rel or "tests" in rel:
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_action_table_is_parsed():
    keys = _admin_action_keys()
    assert {"start_game", "next_round", "kick_player"} <= keys


def test_every_admin_action_has_a_frontend_sender():
    js = _js_sources()
    assert "sendAdminCommand" in js, "frontend sources not found"
    missing = sorted(
        key
        for key in _admin_action_keys() - SENDER_ALLOWLIST
        if not re.search(rf"""action\s*:\s*['"]{re.escape(key)}['"]""", js)
    )
    assert not missing, (
        f"Admin WS actions with no sender in www/js: {missing}. "
        "Remove the handler or restore the control (#3204)."
    )
