/**
 * Shared modal focus trap (#1716), split out of player-utils.js in #3581 so the
 * admin bundle can use it without pulling in the player's import-time side
 * effects. player-utils.js re-exports it for the existing player imports.
 */

/**
 * #1716: accessible focus management for aria-modal dialogs. On activate() we
 * move focus into the dialog, trap Tab within its `.modal-content`, and close
 * on Escape; deactivate() restores focus to whatever held it before the dialog
 * opened. Kept DOM-injectable (reads the modal's ownerDocument) so it is pure
 * with respect to this module and unit-testable without a real browser
 * (see __tests__/modal-focus-trap.test.js).
 *
 * @param {Element} modal - the dialog root (`.hidden` toggled by the caller).
 * @param {Object} [options]
 * @param {string} [options.contentSelector='.modal-content'] - focus-trap scope.
 * @returns {{activate:Function, deactivate:Function}}
 */
export function createModalFocusTrap(modal, options) {
    var opts = options || {};
    var contentSelector = opts.contentSelector || '.modal-content';
    var doc = (modal && modal.ownerDocument) ||
        (typeof document !== 'undefined' ? document : null);
    var previouslyFocused = null;
    var keydownHandler = null;
    var activeOnEscape = null;

    var FOCUSABLE = 'button, [href], input, select, textarea, ' +
        '[tabindex]:not([tabindex="-1"])';

    function focusable() {
        var scope = (modal && modal.querySelector(contentSelector)) || modal;
        if (!scope || !scope.querySelectorAll) return [];
        var nodes = scope.querySelectorAll(FOCUSABLE);
        return Array.prototype.filter.call(nodes, function(el) {
            // Skip disabled / explicitly hidden nodes; keep everything else so a
            // minimal test DOM (no layout) still yields the trap targets.
            return !el.disabled && el.getAttribute('aria-hidden') !== 'true';
        });
    }

    function onKeydown(e) {
        if (e.key === 'Escape' || e.key === 'Esc') {
            if (typeof activeOnEscape === 'function') {
                if (e.preventDefault) e.preventDefault();
                activeOnEscape();
            }
            return;
        }
        if (e.key !== 'Tab') return;
        var f = focusable();
        if (f.length === 0) { if (e.preventDefault) e.preventDefault(); return; }
        var first = f[0];
        var last = f[f.length - 1];
        var active = doc ? doc.activeElement : null;
        var idx = Array.prototype.indexOf.call(f, active);
        if (e.shiftKey) {
            if (idx <= 0) { if (e.preventDefault) e.preventDefault(); last.focus(); }
        } else if (idx === -1 || idx === f.length - 1) {
            if (e.preventDefault) e.preventDefault();
            first.focus();
        }
    }

    function activate(activateOpts) {
        activateOpts = activateOpts || {};
        activeOnEscape = typeof activateOpts.onEscape === 'function'
            ? activateOpts.onEscape : null;
        previouslyFocused = doc ? doc.activeElement : null;
        var f = focusable();
        var initial = activateOpts.initialFocus || f[0];
        if (initial && typeof initial.focus === 'function') initial.focus();
        keydownHandler = onKeydown;
        if (doc && doc.addEventListener) {
            doc.addEventListener('keydown', keydownHandler, true);
        }
    }

    function deactivate() {
        if (keydownHandler && doc && doc.removeEventListener) {
            doc.removeEventListener('keydown', keydownHandler, true);
        }
        keydownHandler = null;
        activeOnEscape = null;
        if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
            previouslyFocused.focus();
        }
        previouslyFocused = null;
    }

    return { activate: activate, deactivate: deactivate };
}
