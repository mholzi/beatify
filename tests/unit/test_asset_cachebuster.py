"""Tests for the asset-fingerprint cache-buster (#1266).

The cache-buster must move on ANY css/js/i18n change, not just a manifest
version bump. These guard the #824 / rc11-SW-recovery failure class: a reused
or forgotten version left the ``?v=`` marker and the SW ``CACHE_VERSION``
identical, so browsers / the service worker kept serving stale assets.
"""

from __future__ import annotations

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
