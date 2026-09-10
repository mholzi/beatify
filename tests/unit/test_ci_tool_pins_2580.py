"""#2580: the lint and type-check tools are pinned in two files — keep them equal.

`requirements_test.txt` is what a contributor installs locally; the workflow is
what the gate actually runs. Until now ruff appeared only in the workflow, so
`pip install -r requirements_test.txt` gave you no ruff at all and whichever
version your machine happened to have. mypy appeared in both, with nothing
keeping the two numbers in step.

The drift is silent in the worst direction: a local run that passes against a
newer ruff, and a CI run that fails against the pinned one — or the reverse,
which is worse, because then the gate is not checking what the author checked.

This test does not care *which* version is pinned. It cares that the two files
say the same thing, so bumping a tool stays one edit with one obvious other
place to change.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
REQUIREMENTS = ROOT / "requirements_test.txt"

#: Tools whose pin has to agree between the two files.
PINNED_TOOLS = ("ruff", "mypy")


def _requirement_pin(tool: str) -> str | None:
    """The `==` pin for `tool` in requirements_test.txt, comments stripped."""
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.fullmatch(rf"{tool}==([\w.]+)", line)
        if m:
            return m.group(1)
    return None


def _workflow_pins(tool: str) -> list[str]:
    """Every `pip install <tool>==x.y.z` version in the workflow."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return re.findall(rf"pip install [^\n]*\b{tool}==([\w.]+)", text)


class TestCiToolPins:
    @pytest.mark.parametrize("tool", PINNED_TOOLS)
    def test_tool_is_pinned_in_requirements(self, tool: str) -> None:
        assert _requirement_pin(tool) is not None, (
            f"{tool} has no == pin in requirements_test.txt — a local install "
            f"then differs from the gate"
        )

    @pytest.mark.parametrize("tool", PINNED_TOOLS)
    def test_workflow_matches_requirements(self, tool: str) -> None:
        wanted = _requirement_pin(tool)
        found = _workflow_pins(tool)
        assert found, f"no `pip install {tool}==…` step found in test.yml"
        for got in found:
            assert got == wanted, (
                f"{tool} is pinned to {got} in test.yml but {wanted} in "
                f"requirements_test.txt — the gate runs a different version "
                f"than a contributor installs"
            )
