"""The guard that watches ``main`` itself must stay uncancellable and fast (#2673).

Every job in ``test.yml`` runs against a pull-request branch, and a PR is green
against its own base. ``main`` is a combination no PR ever evaluated. That gap is
invisible for hand-written code and unavoidable for *derived* artifacts, because
a minified bundle or a ``.gz`` sibling encodes the state of the whole tree it was
generated from.

On 2026-09-06 it cost twenty minutes of wrong bytes: #2666 committed 77 ``.gz``
siblings built from its own branch, #2650 and #2663 landed frontend sources in
between, and ``main`` then served five siblings that decompressed to the previous
version of their file. Home Assistant hands ``<file>.gz`` to every browser and
derives the ETag from the compressed file, so those bytes were served *and*
cached as current.

``build:check`` did run on that push and did name all five files — but the report
survived by luck. Seven merges landed inside 30 seconds and ``test.yml`` groups
its concurrency by ``github.ref`` with ``cancel-in-progress: true``, so six of
the seven runs were cancelled. Only the last commit of the burst was checked, and
a cancelled run raises no alarm at all.

``tests/unit/test_static_gzip_siblings.py`` owns the tree state. This module owns
the plumbing: the properties whose absence let 2026-09-06 go unreported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML ships in requirements_test.txt")

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
GUARD = WORKFLOWS / "main-artifact-guard.yml"

# YAML 1.1 reads a bare ``on:`` key as the boolean True. GitHub means the
# trigger block; both spellings are the same key to us.
ON_KEYS = ("on", True)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    for key in ON_KEYS:
        if key in workflow:
            return workflow[key]
    raise AssertionError(f"workflow has no trigger block: {sorted(workflow)}")


def _steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


def _run_scripts(workflow: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in _steps(workflow))


@pytest.fixture(name="guard")
def guard_fixture() -> dict[str, Any]:
    assert GUARD.is_file(), f"the main guard workflow is gone: {GUARD}"
    return _load(GUARD)


def test_guard_runs_on_every_push_to_main(guard: dict[str, Any]) -> None:
    """The whole point: a gate that evaluates the combination, not a branch."""
    push = _triggers(guard)["push"]

    assert "main" in push["branches"]


def test_guard_is_not_cancelled_by_the_next_merge(guard: dict[str, Any]) -> None:
    """2026-09-06 in one assertion.

    ``test.yml`` groups by ``github.ref``, so merge number two kills the run of
    merge number one. Six of seven runs died that way and nobody noticed,
    because a cancelled run is not a failed run. Keying the group to the commit
    means a burst of merges produces a burst of guards, not one survivor.
    """
    concurrency = guard["concurrency"]

    assert "github.sha" in concurrency["group"], (
        "the guard must group per commit, not per branch — a branch-keyed group "
        "lets each merge cancel the check of the merge before it"
    )
    assert concurrency["cancel-in-progress"] is False


def test_guard_rebuilds_and_compares_the_derived_artifacts(
    guard: dict[str, Any],
) -> None:
    """It has to run the check that named the five files, not a proxy for it."""
    scripts = _run_scripts(guard)

    assert "scripts/build.mjs --check" in scripts or "build:check" in scripts


def test_guard_names_the_drifted_files(guard: dict[str, Any]) -> None:
    """A red X that says only "failed" gets ignored; a list of paths does not."""
    scripts = _run_scripts(guard)

    assert "::error" in scripts, "drifted files must surface as run annotations"
    assert "GITHUB_STEP_SUMMARY" in scripts, "the run needs a readable summary"


def test_guard_announces_itself_beyond_a_red_commit(guard: dict[str, Any]) -> None:
    """On 2026-09-06 main was red for 23 minutes and the fix was an accident.

    In a repo merging several times a day, a red check on a main commit is not
    an alarm. The guard opens (or comments on) an issue so the condition has an
    owner and a timestamp.
    """
    scripts = _run_scripts(guard)

    assert "gh issue create" in scripts
    assert "gh issue comment" in scripts, (
        "recurrences must not open a new issue each time"
    )
    assert guard["permissions"]["issues"] == "write"


def test_guard_stays_fast_enough_to_be_read(guard: dict[str, Any]) -> None:
    """No matrix, no linter, no test suite — install, rebuild, compare, done."""
    jobs = guard["jobs"]

    assert len(jobs) == 1, "a second job makes the guard a pipeline, not a guard"
    job = next(iter(jobs.values()))
    assert "strategy" not in job, "a matrix multiplies the wait for no extra signal"
    assert job["timeout-minutes"] <= 10

    scripts = _run_scripts(guard)
    for slow in ("npm run lint", "npm test", "npm run test:coverage", "pytest"):
        assert slow not in scripts, f"{slow!r} belongs on the pull request, not here"


def test_the_guard_is_allowed_past_gitignore() -> None:
    """A workflow GitHub never receives is the loudest possible no-op.

    ``.gitignore`` ignores ``.github/workflows/*`` and re-admits files one by
    one. That allowlist exists because untracking ``.github/`` in April 2026
    silently switched CI off for two months (#784). A new workflow that is not
    named there sits in the working tree looking correct and runs nowhere.
    """
    gitignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(
        encoding="utf-8"
    )

    assert f"!.github/workflows/{GUARD.name}" in gitignore


def test_the_pull_request_gates_are_untouched() -> None:
    """The guard adds coverage for main; it does not weaken the PR pipeline.

    ``test.yml`` keeps ``cancel-in-progress: true`` on purpose — with several
    merges a day, running every superseded PR push to completion costs far more
    than it finds. The fix for #2673 is the uncancellable slice above, not
    turning that saving off.
    """
    test_workflow = _load(WORKFLOWS / "test.yml")

    triggers = _triggers(test_workflow)
    assert "main" in triggers["pull_request"]["branches"]
    assert "build:check" in _run_scripts(test_workflow)
