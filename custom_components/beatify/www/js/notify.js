/**
 * Beatify — non-blocking notifications (#1663 item 1: alert() → toast/banner).
 *
 * Two surfaces that replace the blocking, unstyled native `alert()`:
 *
 *   showToast()  — Variant A "Neon Top-Toast". Top-center, auto-dismiss (~4s)
 *                  with a glowing depleting progress bar; toasts stack. Best for
 *                  transient confirmations / network hiccups (rematch failed,
 *                  connection lost). Announced via an aria-live container.
 *
 *   showBanner() — Variant C "Inline Panel-Banner". Docked inside the panel,
 *                  above the primary action; persistent, contextual, and stays
 *                  in the screen-reader flow (role="alert"). Best for
 *                  setup/validation errors (e.g. PROVIDER_NOT_SUPPORTED, "start
 *                  not possible").
 *
 * Framework-free and import-free so the same module bundles cleanly into BOTH
 * admin.min.js (entry admin.js) and player.bundle.min.js (entry player-core.js)
 * without pulling in either bundle's local state. Also exposed on
 * `window.BeatifyNotify` for classic (non-module) callers / debugging.
 */

var TOAST_CONTAINER_ID = 'beatify-toast-container';
var DEFAULT_TOAST_MS = 4000;

// i18n lookup with a hard fallback — mirrors the `window.BeatifyI18n && …`
// guard the rest of the codebase uses so this works before i18n has loaded.
function tr(key, fallback) {
    try {
        if (window.BeatifyI18n && typeof window.BeatifyI18n.t === 'function') {
            var s = window.BeatifyI18n.t(key);
            if (s && s !== key) return s;
        }
    } catch (e) { /* i18n not ready — use fallback */ }
    return fallback;
}

function ensureToastContainer() {
    var el = document.getElementById(TOAST_CONTAINER_ID);
    if (!el) {
        el = document.createElement('div');
        el.id = TOAST_CONTAINER_ID;
        el.className = 'beatify-toast-container';
        // Polite live-region so screen readers announce each toast as it lands.
        el.setAttribute('aria-live', 'polite');
        el.setAttribute('aria-atomic', 'false');
        document.body.appendChild(el);
    }
    return el;
}

/**
 * Show a transient neon top-toast.
 * @param {string} message - Text to display.
 * @param {Object} [opts]
 * @param {('error'|'info'|'success')} [opts.type='error'] - Visual accent.
 * @param {number} [opts.duration=4000] - Auto-dismiss ms; 0 = sticky (manual close only).
 * @param {string|null} [opts.icon] - Leading glyph; null to omit.
 * @returns {HTMLElement|null} the toast node.
 */
export function showToast(message, opts) {
    opts = opts || {};
    if (!message) return null;
    var container = ensureToastContainer();
    var duration = typeof opts.duration === 'number' ? opts.duration : DEFAULT_TOAST_MS;
    var type = opts.type || 'error';

    var toast = document.createElement('div');
    toast.className = 'beatify-toast beatify-toast--' + type;
    toast.setAttribute('role', 'status');

    var body = document.createElement('div');
    body.className = 'beatify-toast-body';

    if (opts.icon !== null) {
        var iconEl = document.createElement('span');
        iconEl.className = 'beatify-toast-icon';
        iconEl.setAttribute('aria-hidden', 'true');
        iconEl.textContent = opts.icon || (type === 'success' ? '✅' : (type === 'info' ? 'ℹ️' : '⚠️'));
        body.appendChild(iconEl);
    }

    var textEl = document.createElement('span');
    textEl.className = 'beatify-toast-text';
    textEl.textContent = String(message);
    body.appendChild(textEl);
    toast.appendChild(body);

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'beatify-toast-close';
    closeBtn.setAttribute('aria-label', tr('common.close', 'Dismiss'));
    closeBtn.textContent = '×';
    toast.appendChild(closeBtn);

    if (duration > 0) {
        var progress = document.createElement('div');
        progress.className = 'beatify-toast-progress';
        // The bar drains over exactly the auto-dismiss window (CSS animation);
        // under prefers-reduced-motion it stays full (see styles.css).
        progress.style.animationDuration = duration + 'ms';
        toast.appendChild(progress);
    }

    container.appendChild(toast);
    // Enter transition (next frame so the initial state paints first).
    if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(function() { toast.classList.add('beatify-toast--in'); });
    } else {
        toast.classList.add('beatify-toast--in');
    }

    var dismissed = false;
    var timer = null;
    function dismiss() {
        if (dismissed) return;
        dismissed = true;
        if (timer) clearTimeout(timer);
        toast.classList.remove('beatify-toast--in');
        toast.classList.add('beatify-toast--leaving');
        setTimeout(function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 280);
    }
    closeBtn.addEventListener('click', dismiss);
    if (duration > 0) {
        timer = setTimeout(dismiss, duration);
    }
    return toast;
}

/**
 * Show a persistent inline panel-banner docked above a primary action.
 * @param {string} message - Body text.
 * @param {Object} [opts]
 * @param {(HTMLElement|string)} [opts.anchor] - Element (or id) the banner is
 *   inserted BEFORE — i.e. it docks directly above the primary action.
 * @param {(HTMLElement|string)} [opts.parent] - Explicit parent; defaults to the
 *   anchor's parent.
 * @param {string} [opts.title] - Optional bold title line.
 * @param {('error'|'warning'|'info')} [opts.type='error'] - Visual accent.
 * @param {string} [opts.icon] - Leading glyph.
 * @param {string} [opts.id='beatify-banner'] - Reused id — a second call with the
 *   same id replaces the previous banner instead of stacking duplicates.
 * @param {boolean} [opts.dismissible=true] - Show a close button.
 * @returns {HTMLElement|null} the banner node.
 */
export function showBanner(message, opts) {
    opts = opts || {};
    if (!message) return null;

    var anchor = opts.anchor;
    if (typeof anchor === 'string') anchor = document.getElementById(anchor);
    var parent = opts.parent;
    if (typeof parent === 'string') parent = document.getElementById(parent);
    if (!parent) parent = anchor ? anchor.parentNode : null;
    if (!parent) return null;

    var id = opts.id || 'beatify-banner';
    var existing = document.getElementById(id);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    var banner = document.createElement('div');
    banner.id = id;
    banner.className = 'beatify-banner beatify-banner--' + (opts.type || 'error');
    // role="alert" keeps it in the screen-reader flow (announced in place).
    banner.setAttribute('role', 'alert');

    var iconEl = document.createElement('span');
    iconEl.className = 'beatify-banner-icon';
    iconEl.setAttribute('aria-hidden', 'true');
    iconEl.textContent = opts.icon || '⛔';
    banner.appendChild(iconEl);

    var content = document.createElement('div');
    content.className = 'beatify-banner-content';
    if (opts.title) {
        var titleEl = document.createElement('div');
        titleEl.className = 'beatify-banner-title';
        titleEl.textContent = String(opts.title);
        content.appendChild(titleEl);
    }
    var textEl = document.createElement('div');
    textEl.className = 'beatify-banner-text';
    textEl.textContent = String(message);
    content.appendChild(textEl);
    banner.appendChild(content);

    if (opts.dismissible !== false) {
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'beatify-banner-close';
        closeBtn.setAttribute('aria-label', tr('common.close', 'Dismiss'));
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', function() {
            if (banner.parentNode) banner.parentNode.removeChild(banner);
        });
        banner.appendChild(closeBtn);
    }

    if (anchor && anchor.parentNode === parent) {
        parent.insertBefore(banner, anchor);
    } else {
        parent.appendChild(banner);
    }
    return banner;
}

/**
 * Remove a banner previously shown by showBanner (by id).
 * @param {string} [id='beatify-banner']
 */
export function clearBanner(id) {
    var el = document.getElementById(id || 'beatify-banner');
    if (el && el.parentNode) el.parentNode.removeChild(el);
}

// Classic-script / debugging handle. Guarded so importing this module in a
// non-browser (vitest node) context is a harmless no-op.
try {
    window.BeatifyNotify = { showToast: showToast, showBanner: showBanner, clearBanner: clearBanner };
} catch (e) { /* no window (SSR / unit test) */ }
