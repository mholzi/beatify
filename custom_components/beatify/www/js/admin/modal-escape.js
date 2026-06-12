/**
 * Beatify Admin — consolidated modal Escape-close (#1402 B7).
 *
 * admin.js historically wired THREE separate `document` keydown listeners — one
 * each in setupQRModal / setupRematchModal / setupAdminJoin — that each checked
 * Escape and closed their own modal (and the join one also handled the end-game
 * modal). Three document-level listeners for the same key is wasteful and made
 * it easy to forget Escape on new modals (reset + request had none).
 *
 * This module owns a single registry + one document keydown handler. Each
 * modal's setup calls `registerModalClose(id, closeFn)`; `setupModalEscapeHandler`
 * (wired once at init) closes only the TOPMOST visible registered modal on
 * Escape — iterating in reverse registration order so the most recently
 * registered overlay wins a tie, and a single Escape dismisses exactly one
 * modal.
 *
 * Pure + injectable (`doc` defaults to the global `document`) so it unit-tests
 * without a real DOM.
 */

const modalCloseHandlers = [];

/** Register a modal's element id + its close callback. */
export function registerModalClose(modalId, closeFn) {
    modalCloseHandlers.push({ modalId, close: closeFn });
}

/** Test-only: drop all registrations so each test starts clean. */
export function _resetModalCloseHandlers() {
    modalCloseHandlers.length = 0;
}

/**
 * Close the topmost visible registered modal. Returns true if one was closed.
 * Exported for direct unit testing; the live handler delegates to it.
 */
export function closeTopmostModal(doc = document) {
    for (let i = modalCloseHandlers.length - 1; i >= 0; i--) {
        const entry = modalCloseHandlers[i];
        const el = doc.getElementById(entry.modalId);
        if (el && !el.classList.contains('hidden')) {
            entry.close();
            return true;
        }
    }
    return false;
}

/** Wire the single document-level Escape → close-topmost-modal handler. */
export function setupModalEscapeHandler(doc = document) {
    doc.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        closeTopmostModal(doc);
    });
}
