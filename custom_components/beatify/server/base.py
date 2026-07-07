"""Shared base class and helpers for Beatify HTTP views."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Fallback version string used only if manifest.json could not be read at
# integration setup (very rare — would mean a malformed install). The real
# version is loaded from manifest.json once during async_setup_entry and
# cached in hass.data[DOMAIN]['version'] (#784).
#
# We deliberately do NOT read manifest.json at module import time: HA 2026.2+
# flags any blocking I/O at module level, including the reload path where the
# event loop is already running.
_VERSION_FALLBACK = "unknown"


def _get_version(hass: HomeAssistant | None = None) -> str:
    """
    Get the integration version.

    Reads from ``hass.data[DOMAIN]['version']`` (populated at setup_entry from
    manifest.json) when ``hass`` is provided. Falls back to the unknown sentinel
    if hass isn't available or the key isn't populated yet.
    """
    if hass is not None:
        try:
            data = hass.data.get(DOMAIN, {})
            version = data.get("version")
            if version:
                return version
        except (AttributeError, KeyError):  # pragma: no cover — defensive
            pass
    return _VERSION_FALLBACK


def _read_file(path: Path) -> str:
    """Read file contents (runs in executor)."""
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Cache-buster (#1266)
# ---------------------------------------------------------------------------
#
# The ``?v=`` asset query strings and the service worker's ``CACHE_VERSION``
# used to be hardcoded version literals, so busting depended on remembering to
# bump every file on every release. A reused or forgotten bump left the marker
# identical and browsers / the SW cache served stale CSS/JS/i18n (#824, and the
# rc11 self-healing-SW workaround were symptoms of this).
#
# Instead we derive an ``{{ASSET_VER}}`` token = ``<version>-<fingerprint>``
# where the fingerprint is a short hash of the served asset files. Because it
# moves whenever ANY css/js/i18n file changes, cache-busting no longer needs a
# manifest bump. ``{{VERSION}}`` stays the clean semantic version for the meta
# tag / footer. Ported from the Quizify sibling (quizify#162).

# Tokens substituted at serve time. {{VERSION}} -> clean semver (display);
# {{ASSET_VER}} -> <version>-<fingerprint> (cache-busting).
_VERSION_TOKEN = "{{VERSION}}"
_ASSET_VER_TOKEN = "{{ASSET_VER}}"

# Subdirs under www/ holding the ?v=-busted assets.
_ASSET_SUBDIRS = ("css", "js", "i18n")

# Recompute the fingerprint at most this often — a small dir walk, bounded so a
# burst of player.html loads at game start doesn't re-walk per request.
_ASSET_FP_TTL_NS = 5 * 1_000_000_000  # 5s
_ASSET_FP_CACHE: tuple[int, str] | None = None  # (monotonic_ns, fingerprint)
# Guards _ASSET_FP_CACHE: it's read/written from both the event loop and HA
# executor threads, so concurrent first-access could otherwise race and recompute
# the fingerprint twice (#1592). Double-checked inside the lock below.
_ASSET_FP_LOCK = threading.Lock()


def _compute_asset_fingerprint(www_dir: Path) -> str:
    """Short hash over the served assets' (relative path, mtime, size).

    Changes whenever any css/js/i18n file is added, removed, or edited — so the
    cache-buster moves on any real asset change, with no manifest bump needed.
    Cheap: a handful of ``stat`` calls. Falls back gracefully if dirs/files are
    missing (defensive — runs on the HTML serve path).
    """
    h = hashlib.md5(usedforsecurity=False)
    for sub in _ASSET_SUBDIRS:
        d = www_dir / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            try:
                st = p.stat()
            except OSError:  # pragma: no cover — defensive
                continue
            h.update(str(p.relative_to(www_dir)).encode())
            h.update(str(st.st_mtime_ns).encode())
            h.update(str(st.st_size).encode())
    return h.hexdigest()[:8]


def _get_asset_version(version: str, www_dir: Path) -> str:
    """Cache-buster value ``<version>-<asset_fingerprint>``.

    The version prefix keeps it readable (which release) and back-compatible
    with assertions that look for ``?v=<version>``; the fingerprint suffix is
    what makes it move on asset changes. Fingerprint recompute is throttled to
    ``_ASSET_FP_TTL_NS``.
    """
    global _ASSET_FP_CACHE  # noqa: PLW0603
    now = time.monotonic_ns()
    # Fast path: a fresh cache entry needs no lock (tuple reads are atomic).
    cache = _ASSET_FP_CACHE
    if cache is not None and now - cache[0] < _ASSET_FP_TTL_NS:
        return f"{version}-{cache[1]}"
    # Slow path: serialize recompute so concurrent first-access (event loop +
    # executor threads) hashes once, not once-per-thread (#1592). Re-check the
    # cache inside the lock — another thread may have just populated it.
    with _ASSET_FP_LOCK:
        cache = _ASSET_FP_CACHE
        if cache is not None and now - cache[0] < _ASSET_FP_TTL_NS:
            fingerprint = cache[1]
        else:
            fingerprint = _compute_asset_fingerprint(www_dir)
            _ASSET_FP_CACHE = (time.monotonic_ns(), fingerprint)
    return f"{version}-{fingerprint}"


def _www_dir() -> Path:
    """Absolute path to the integration's www/ asset directory."""
    return Path(__file__).parent.parent / "www"


def _apply_cache_tokens(text: str, hass: HomeAssistant) -> str:
    """Substitute {{VERSION}} and {{ASSET_VER}} tokens at serve time (#1266)."""
    version = _get_version(hass)
    text = text.replace(_ASSET_VER_TOKEN, _get_asset_version(version, _www_dir()))
    return text.replace(_VERSION_TOKEN, version)


async def _async_prime_asset_fingerprint(hass: HomeAssistant) -> None:
    """Warm ``_ASSET_FP_CACHE`` via an executor job when it is cold or stale.

    Mirrors the throttle/lock logic in :func:`_get_asset_version`, but performs
    the actual filesystem sweep (:func:`_compute_asset_fingerprint`, a blocking
    ``rglob``/``stat`` walk) off the event loop. A no-op when the cache is fresh.
    """
    global _ASSET_FP_CACHE  # noqa: PLW0603
    now = time.monotonic_ns()
    cache = _ASSET_FP_CACHE
    if cache is not None and now - cache[0] < _ASSET_FP_TTL_NS:
        return
    fingerprint = await hass.async_add_executor_job(
        _compute_asset_fingerprint, _www_dir()
    )
    with _ASSET_FP_LOCK:
        cache = _ASSET_FP_CACHE
        if cache is None or time.monotonic_ns() - cache[0] >= _ASSET_FP_TTL_NS:
            _ASSET_FP_CACHE = (time.monotonic_ns(), fingerprint)


async def async_apply_cache_tokens(hass: HomeAssistant, text: str) -> str:
    """Async form of :func:`_apply_cache_tokens` for the HTTP serve path.

    ``_get_asset_version`` recomputes the asset fingerprint with a blocking
    ``rglob``/``stat`` sweep on cache miss (once per ``_ASSET_FP_TTL_NS``).
    Calling the sync form directly from an async view runs that sweep on the
    event loop, which HA's ``util/loop`` blocking-call detector flags
    (``scandir``/``read_bytes`` inside the event loop). Priming the fingerprint
    cache in an executor first keeps the hot serve path non-blocking; the
    subsequent sync substitution then hits the warm cache.
    """
    await _async_prime_asset_fingerprint(hass)
    return _apply_cache_tokens(text, hass)


# #1177 follow-up: PR #1179 set documentElement.lang inside setLanguage(), but
# on Android Chrome auto-translate runs against the *initial* HTML, before the
# WebSocket state arrives and triggers setLanguage('de'). The static
# <html lang="en"> in the page sources then causes the browser to auto-translate
# the already-correct German strings ("Tipp abgeben" -> "Trinkgeld abgeben",
# "Fun Facts" -> "Wissenswertes"). Patching the attribute server-side, before
# the bytes leave the integration, eliminates the race entirely.
def _resolve_page_language(hass: HomeAssistant) -> str:
    """Resolve the locale to render into ``<html lang>`` for HTML pages.

    Priority:
    1. Active game's language (the wizard selection wins for player/dashboard
       pages, which are the surfaces that show the per-game translated UI).
    2. Home Assistant's configured UI language (covers admin/launcher visits
       outside an active game — matches what the wizard would default to).
    3. ``"en"`` as last resort.
    """
    data = hass.data.get(DOMAIN, {})
    game_state = data.get("game")
    if game_state is not None:
        lang = getattr(game_state, "language", None)
        if lang:
            return lang
    # `hass.config` exists on a real HomeAssistant but may be absent on a bare
    # test/stub hass — guard the attribute access so the helper degrades to "en"
    # instead of raising while serving a page.
    cfg = getattr(hass, "config", None)
    cfg_lang = getattr(cfg, "language", None)
    if cfg_lang:
        return cfg_lang
    return "en"


def _apply_html_lang(text: str, hass: HomeAssistant) -> str:
    """Rewrite ``<html lang="en">`` to the active locale before serving."""
    lang = _resolve_page_language(hass)
    # All Beatify HTML files ship with the literal `<html lang="en">`; a plain
    # string replace stays predictable (no regex-escaping the locale value) and
    # is a no-op if a future template lands with a different default.
    return text.replace('<html lang="en">', f'<html lang="{lang}">', 1)


_html_cache: dict[str, str] = {}


async def _get_html(hass: HomeAssistant, path: Path) -> str | None:
    """Read HTML file with in-memory caching."""
    key = str(path)
    if key in _html_cache:
        return _html_cache[key]
    if not path.exists():
        return None
    content = await hass.async_add_executor_job(_read_file, path)
    _html_cache[key] = content
    return content


def _json_error(
    message: str,
    status: int,
    *,
    code: str = "ERROR",
    details: dict[str, Any] | None = None,
) -> web.Response:
    """Return a consistent JSON error response.

    rc16 (#1097): the body now puts the machine-readable code under
    ``code`` (matching the WebSocket error shape — see ws_handlers.py).
    Before rc16 this used the key ``error``, which caused two regressions:

    1. ``admin.js`` checks ``data.code === 'GAME_IN_LOBBY'`` to silently
       recover when a LOBBY game already exists; with the old key the
       check was dead code and the user got dropped into a modal with
       the raw English message instead of the seamless gameplay start.
    2. The ``errors.<CODE>`` i18n lookup (also reading ``data.code``)
       never fired, so German / Spanish / French / Dutch users saw the
       raw English ``message`` for every REST-side error response.

    The ``error`` key is kept too so anything still reading it from
    older builds doesn't break — drop after a few releases.

    ``details`` (optional) carries extra machine-readable context that the
    admin UI can render — e.g. the structured per-song rejections from a
    failed playlist import (#1576). Merged into the body under their own keys
    so clients ignoring them are unaffected.
    """
    body: dict[str, Any] = {"code": code, "error": code, "message": message}
    if details:
        body.update(details)
    return web.json_response(body, status=status)


class RateLimitMixin:
    """Mixin providing IP-based rate limiting for views."""

    RATE_LIMIT_REQUESTS: int = 5
    RATE_LIMIT_WINDOW: int = 60  # seconds

    def _init_rate_limits(self) -> None:
        """Initialize rate limit state. Call from __init__."""
        self._rate_limits: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is within rate limit."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True


class BeatifyAdminView(HomeAssistantView):
    """Base class for admin-protected Beatify views.

    #998: gating is delegated to Home Assistant's own auth — ``requires_auth``
    makes HA's middleware reject any request without a valid HA bearer token
    before the handler runs. The former per-game ``admin_token`` check is
    retired: a logged-in HA user *is* the admin.
    """

    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view with hass reference."""
        self.hass = hass

    # -- helpers available to subclasses --

    def _get_game_state(self) -> Any | None:
        """Return the current GameState or None."""
        return self.hass.data.get(DOMAIN, {}).get("game")
