"""#2581: the CI has to run against the Python version Home Assistant requires.

Home Assistant's own `pyproject.toml` moved to `requires-python >= 3.14.2` with
2026.3 (2026.1 was still 3.13.2). Every user on a current Home Assistant runs
this integration on Python 3.14 — and before this change the CI matrix stopped
at 3.13, so not one test had ever executed there.

The lower bound stays at 3.12 as long as `hacs.json` names HA 2025.1.0 as the
minimum: HA 2025.2.0 is the first release to require 3.13.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
HACS = ROOT / "hacs.json"

_MATRIX = re.compile(r"python-version:\s*\[([^\]]+)\]")


def _matrices() -> list[list[str]]:
    text = WORKFLOW.read_text(encoding="utf-8")
    return [
        [v.strip().strip('"').strip("'") for v in m.split(",")]
        for m in _MATRIX.findall(text)
    ]


class TestCiPythonMatrix:
    def test_every_matrix_covers_314(self):
        matrices = _matrices()
        assert matrices, "no python-version matrix found in test.yml"
        for versions in matrices:
            assert "3.14" in versions, f"matrix {versions} does not test 3.14"

    def test_burn_in_runs_on_314(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        assert 'PYTHON_VERSION: "3.14"' in text

    def test_lower_bound_matches_the_declared_hacs_minimum(self):
        """3.12 may only be dropped once hacs.json stops claiming HA 2025.1.0."""
        minimum = json.loads(HACS.read_text(encoding="utf-8")).get("homeassistant")
        versions = _matrices()[0]
        if minimum == "2025.1.0":
            assert "3.12" in versions, (
                "hacs.json still claims HA 2025.1.0, which runs on Python 3.12 — "
                "keep it in the matrix or raise the declared minimum first"
            )
        else:  # pragma: no cover - guard for a future bump
            pytest.skip(f"hacs.json minimum moved to {minimum}; revisit the floor")
