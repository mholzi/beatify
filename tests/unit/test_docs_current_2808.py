"""#2808: the documentation has to describe the version that ships.

Release step 7 names two numbers and then says "and anything else under
`docs/` that mentions a version". On 2026-09-10 the two numbers were right, the
step was ticked off, and two other things had been stale for a month: the
README's "What's New" ended at v4.2.0 — four minor versions back — and
`docs/provider-coverage.md` still counted a 5,980-song catalogue that had grown
to 8,432, so every percentage in it was wrong.

A step that depends on somebody taking a trailing clause seriously is not a
check. This one runs in CI.

**It is deliberately quiet during an rc cycle.** Otherwise every rc-cut PR
would have to announce a version nobody can install yet. The contract is: the
README is current *when a stable ships*.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from check_docs_current import catalogue, check, shipped_version  # noqa: E402


class TestDocsMatchTheRepository:
    def test_no_disagreements(self):
        findings = check()
        assert not findings, "documentation drift:\n" + "\n".join(
            f"  {f['file']} — {f['what']}: {f['detail']}" for f in findings
        )


class TestTheCheckItself:
    """A check that cannot fail is decoration."""

    def test_it_notices_a_stale_catalogue_number(self, monkeypatch):
        import check_docs_current as mod

        monkeypatch.setattr(mod, "catalogue", lambda: (99, 12345))
        findings = mod.check()
        assert any("catalogue" in f["what"] for f in findings), (
            "the numbers were moved out from under the README and the check "
            "stayed green"
        )

    def test_it_notices_a_behind_whats_new(self, monkeypatch, tmp_path):
        import check_docs_current as mod

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        current = shipped_version().split("-")[0]
        fake = tmp_path / "README.md"
        fake.write_text(readme.replace(f"### v{current}", "### v0.1.0", 1), "utf-8")
        monkeypatch.setattr(mod, "README", fake)
        monkeypatch.setattr(mod, "shipped_version", lambda: current)

        findings = mod.check()
        assert any("What's New" in f["what"] for f in findings)

    def test_it_holds_its_tongue_during_an_rc(self, monkeypatch, tmp_path):
        """An rc must not force a README edit — that is the whole nuance."""
        import check_docs_current as mod

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        current = shipped_version().split("-")[0]
        fake = tmp_path / "README.md"
        fake.write_text(readme.replace(f"### v{current}", "### v0.1.0", 1), "utf-8")
        monkeypatch.setattr(mod, "README", fake)
        monkeypatch.setattr(mod, "shipped_version", lambda: "9.9.9-rc1")

        findings = mod.check()
        assert not any("What's New" in f["what"] for f in findings)


class TestTheNumbersItReads:
    def test_the_catalogue_is_not_empty(self):
        playlists, songs = catalogue()
        assert playlists > 0 and songs > 0

    def test_the_manifest_version_parses(self):
        v = shipped_version()
        assert v and v[0].isdigit(), v


@pytest.mark.parametrize("path", ["scripts/check_docs_current.py"])
def test_the_checker_is_committed(path):
    """It only helps if it travels with the repository."""
    assert (ROOT / path).exists()
