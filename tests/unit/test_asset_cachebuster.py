"""Tests for the asset-fingerprint cache-buster (#1266).

The cache-buster must move on ANY css/js/i18n change, not just a manifest
version bump. These guard the #824 / rc11-SW-recovery failure class: a reused
or forgotten version left the ``?v=`` marker and the SW ``CACHE_VERSION``
identical, so browsers / the service worker kept serving stale assets.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server import base
from custom_components.beatify.server.base import (
    _apply_cache_tokens,
    _compute_asset_fingerprint,
    _get_asset_version,
)
from custom_components.beatify.server.stats_views import (
    AnalyticsPageView,
    DashboardView,
)
from custom_components.beatify.server.views import AdminView, PlayerView, SwJsView


class _FakeHass:
    """Minimal hass stand-in: real version data + inline executor."""

    def __init__(self, version: str) -> None:
        self.data = {DOMAIN: {"version": version}}

    async def async_add_executor_job(self, func, *args):  # noqa: ANN001
        return func(*args)


def _write(root, sub, name, body) -> None:  # noqa: ANN001
    d = root / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body, encoding="utf-8")


class TestAssetFingerprint:
    """The fingerprint is the lever that makes busting automatic."""

    def test_fingerprint_changes_when_asset_content_changes(self, tmp_path) -> None:
        _write(tmp_path, "css", "styles.css", "a {}")
        fp1 = _compute_asset_fingerprint(tmp_path)
        # Edit the file (size changes) — same as shipping a new CSS build.
        _write(tmp_path, "css", "styles.css", "a { color: red }")
        fp2 = _compute_asset_fingerprint(tmp_path)
        assert fp1 != fp2, "fingerprint must change when an asset's content changes"

    def test_fingerprint_changes_when_asset_added(self, tmp_path) -> None:
        _write(tmp_path, "js", "admin.js", "x")
        fp1 = _compute_asset_fingerprint(tmp_path)
        _write(tmp_path, "i18n", "de.json", "{}")
        fp2 = _compute_asset_fingerprint(tmp_path)
        assert fp1 != fp2, "fingerprint must change when an asset is added"

    def test_fingerprint_stable_when_nothing_changes(self, tmp_path) -> None:
        _write(tmp_path, "js", "admin.js", "x")
        assert _compute_asset_fingerprint(tmp_path) == _compute_asset_fingerprint(
            tmp_path
        )

    def test_fingerprint_ignores_non_asset_dirs(self, tmp_path) -> None:
        # img/ and arbitrary files are not part of the ?v=-busted set.
        _write(tmp_path, "js", "admin.js", "x")
        fp1 = _compute_asset_fingerprint(tmp_path)
        _write(tmp_path, "img", "icon.png", "binary-ish")
        fp2 = _compute_asset_fingerprint(tmp_path)
        assert fp1 == fp2, "only css/js/i18n should drive the fingerprint"

    def test_fingerprint_is_short_hex(self, tmp_path) -> None:
        _write(tmp_path, "css", "styles.css", "a {}")
        fp = _compute_asset_fingerprint(tmp_path)
        assert len(fp) == 8
        assert all(c in "0123456789abcdef" for c in fp)

    def test_missing_dirs_do_not_raise(self, tmp_path) -> None:
        # Defensive: runs on the HTML serve path even on a malformed install.
        assert isinstance(_compute_asset_fingerprint(tmp_path), str)


class TestAssetVersion:
    """``<version>-<fingerprint>`` shape and token substitution."""

    def setup_method(self) -> None:
        # Clear the module-level throttle so each test recomputes fresh.
        base._ASSET_FP_CACHE = None

    def test_asset_version_is_version_plus_fingerprint(self, tmp_path) -> None:
        _write(tmp_path, "css", "styles.css", "a {}")
        av = _get_asset_version("9.9.9", tmp_path)
        # Back-compat: starts with the version (so ?v=<version> assertions hold)
        # and carries a fingerprint suffix that busts on asset changes.
        assert av.startswith("9.9.9-")
        assert len(av) == len("9.9.9-") + 8

    def test_apply_cache_tokens_substitutes_both(self) -> None:
        hass = _FakeHass("9.9.9")
        text = 'v={{VERSION}} a="?v={{ASSET_VER}}"'
        out = _apply_cache_tokens(text, hass)
        assert "{{VERSION}}" not in out
        assert "{{ASSET_VER}}" not in out
        # Clean version on its own; asset version carries the suffix.
        assert "v=9.9.9 " in out
        assert "?v=9.9.9-" in out

    def test_apply_cache_tokens_passthrough_without_tokens(self) -> None:
        hass = _FakeHass("9.9.9")
        assert _apply_cache_tokens("no tokens here", hass) == "no tokens here"


class TestAssetVersionThreadSafety:
    """The fingerprint cache is read/written from the event loop AND HA
    executor threads, so concurrent first-access must not race (#1592)."""

    def setup_method(self) -> None:
        base._ASSET_FP_CACHE = None

    def test_concurrent_first_access_yields_one_consistent_fingerprint(
        self, tmp_path
    ) -> None:
        _write(tmp_path, "css", "styles.css", "a {}")
        _write(tmp_path, "js", "admin.js", "x")

        n = 16
        barrier = threading.Barrier(n)
        results: list[str] = []
        errors: list[BaseException] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                # Line all threads up so they hit the empty cache together.
                barrier.wait()
                av = _get_asset_version("9.9.9", tmp_path)
            except BaseException as exc:  # noqa: BLE001 — surface any race crash
                with lock:
                    errors.append(exc)
            else:
                with lock:
                    results.append(av)

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent access raised: {errors}"
        assert len(results) == n
        # All threads must observe one identical fingerprint.
        assert len(set(results)) == 1, results
        assert results[0].startswith("9.9.9-")
        # And the cache ends up populated exactly once.
        assert base._ASSET_FP_CACHE is not None


class TestServedPagesHaveNoUnresolvedTokens:
    """End-to-end: real view fns + the real HTML / sw.js on disk."""

    def setup_method(self) -> None:
        base._ASSET_FP_CACHE = None

    async def _serve(self, view_cls):  # noqa: ANN001
        view = view_cls(_FakeHass("9.9.9"))
        return await view.get(object())

    async def test_admin_html_resolves_tokens(self) -> None:
        resp = await self._serve(AdminView)
        assert resp.status == 200
        assert "{{VERSION}}" not in resp.text
        assert "{{ASSET_VER}}" not in resp.text
        # ?v= now carries <version>-<fingerprint>, not the bare version.
        assert "?v=9.9.9-" in resp.text
        # The meta tag keeps the clean semantic version.
        assert 'name="beatify-version" content="9.9.9"' in resp.text
        # And the new asset-version meta carries the fingerprint (#824 i18n fix).
        assert 'name="beatify-asset-version" content="9.9.9-' in resp.text

    async def test_player_and_dashboard_and_analytics_resolve_tokens(self) -> None:
        for view_cls in (PlayerView, DashboardView, AnalyticsPageView):
            resp = await self._serve(view_cls)
            assert resp.status == 200, view_cls.__name__
            assert "{{VERSION}}" not in resp.text, view_cls.__name__
            assert "{{ASSET_VER}}" not in resp.text, view_cls.__name__

    async def test_sw_js_cache_version_carries_fingerprint(self) -> None:
        resp = await self._serve(SwJsView)
        assert resp.status == 200
        assert "{{ASSET_VER}}" not in resp.text
        assert "beatify-v9.9.9-" in resp.text


# ---------------------------------------------------------------------------
# Static consistency guard (#1278)
# ---------------------------------------------------------------------------
#
# #1266 made cache-busting automatic by templating ``{{ASSET_VER}}`` /
# ``{{VERSION}}`` at serve time, so nobody bumps ``?v=`` or ``CACHE_VERSION`` by
# hand anymore. The remaining risk is a *regression*: someone re-introduces a
# hardcoded literal (the rc8->rc14 drift / legacy-admin-flash class) by pasting
# a ``?v=4.0.0`` or ``CACHE_VERSION = 'beatify-v4.0.0'`` back into a template.
# These tests are the CI guard requested in #1278 AC #2 — they fail the PR the
# moment a literal slips in, instead of waiting for stale assets in production.

_WWW_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"

# Any ``?v=`` whose value is not the {{ASSET_VER}} token is a hardcoded literal.
_HARDCODED_V = re.compile(r"\?v=(?!\{\{ASSET_VER\}\})")
# A CACHE_VERSION assignment whose value doesn't carry the token is hardcoded.
_HARDCODED_CACHE_VERSION = re.compile(
    r"CACHE_VERSION\s*=\s*['\"](?![^'\"]*\{\{ASSET_VER\}\})"
)


def _html_files() -> list[Path]:
    return sorted(_WWW_DIR.glob("*.html"))


class TestNoHardcodedCacheBusters:
    """Every shipped template must use the token, never a baked-in literal."""

    def test_www_dir_is_present(self) -> None:
        # Guards the guard: a wrong path would make the checks below vacuous.
        assert _WWW_DIR.is_dir(), _WWW_DIR
        assert _html_files(), "no HTML templates found to check"

    @pytest.mark.parametrize("html", _html_files(), ids=lambda p: p.name)
    def test_html_has_no_hardcoded_v_query(self, html: Path) -> None:
        text = html.read_text(encoding="utf-8")
        offenders = [
            line
            for line in text.splitlines()
            if "?v=" in line and _HARDCODED_V.search(line)
        ]
        assert not offenders, (
            f"{html.name} contains hardcoded ?v= cache-buster(s) — use "
            f"'?v={{{{ASSET_VER}}}}' so #1266 templating busts them automatically "
            f"(#1278):\n  " + "\n  ".join(offenders)
        )

    def test_sw_js_cache_version_uses_token(self) -> None:
        sw = _WWW_DIR / "sw.js"
        text = sw.read_text(encoding="utf-8")
        assignments = [line for line in text.splitlines() if "CACHE_VERSION =" in line]
        assert assignments, "sw.js has no CACHE_VERSION assignment"
        offenders = [
            line for line in assignments if _HARDCODED_CACHE_VERSION.search(line)
        ]
        assert not offenders, (
            "sw.js CACHE_VERSION must carry the {{ASSET_VER}} token, not a "
            "hardcoded literal, so it busts on any asset change (#1278):\n  "
            + "\n  ".join(offenders)
        )


class TestAsyncApplyCacheTokens:
    """The async serve-path wrapper must prime the fingerprint OFF the event
    loop: the sync form's blocking ``rglob``/``stat`` sweep tripped HA's
    ``util/loop`` blocking-call detector when the throttle TTL expired.
    ``async_apply_cache_tokens`` offloads that sweep to an executor first, then
    substitutes against the warm cache."""

    def setup_method(self) -> None:
        base._ASSET_FP_CACHE = None

    async def test_substitutes_like_sync_form(self) -> None:
        hass = _FakeHass("9.9.9")
        out = await base.async_apply_cache_tokens(
            hass, 'v={{VERSION}} a="?v={{ASSET_VER}}"'
        )
        assert "{{VERSION}}" not in out
        assert "{{ASSET_VER}}" not in out
        assert "v=9.9.9 " in out
        assert "?v=9.9.9-" in out

    async def test_fingerprint_sweep_runs_in_executor(self) -> None:
        # The blocking sweep must be offloaded — record what the executor runs.
        offloaded: list = []

        class _SpyHass(_FakeHass):
            async def async_add_executor_job(self, func, *args):  # noqa: ANN001
                offloaded.append(func)
                return func(*args)

        await base.async_apply_cache_tokens(_SpyHass("9.9.9"), "{{ASSET_VER}}")
        assert base._compute_asset_fingerprint in offloaded, (
            "the blocking fingerprint sweep must run via async_add_executor_job, "
            "not inline on the event loop"
        )

    async def test_prime_warms_cache_so_sync_form_does_not_recompute(
        self, monkeypatch
    ) -> None:
        # After the async wrapper primes the cache, the sync substitution that
        # follows must hit the warm cache and NOT re-run the blocking sweep.
        await base.async_apply_cache_tokens(_FakeHass("9.9.9"), "{{ASSET_VER}}")
        assert base._ASSET_FP_CACHE is not None

        calls: list = []
        real = base._compute_asset_fingerprint

        def _spy(www_dir):  # noqa: ANN001
            calls.append(www_dir)
            return real(www_dir)

        monkeypatch.setattr(base, "_compute_asset_fingerprint", _spy)
        base._apply_cache_tokens("{{ASSET_VER}}", _FakeHass("9.9.9"))
        assert calls == [], "warm cache must not trigger a blocking recompute"

    async def test_fresh_cache_skips_executor_entirely(self) -> None:
        # A warm cache is a no-op: no executor job, no sweep — the hot path.
        await base.async_apply_cache_tokens(_FakeHass("9.9.9"), "{{ASSET_VER}}")

        offloaded: list = []

        class _SpyHass(_FakeHass):
            async def async_add_executor_job(self, func, *args):  # noqa: ANN001
                offloaded.append(func)
                return func(*args)

        await base.async_apply_cache_tokens(_SpyHass("9.9.9"), "{{ASSET_VER}}")
        assert offloaded == [], "a fresh fingerprint cache must skip the executor"
