/**
 * Beatify Admin — QR-Modal section (#1589, continuation of #1279 Schritt 4b).
 *
 * Extracted verbatim from admin.js: the tap-to-enlarge join-QR modal
 * (openQRModal / closeQRModal) plus its one-time wiring (setupQRModal). The
 * modal is shared between the home-view tap-to-enlarge (BeatifyHome triggers
 * openQRModal) and the admin-playing view's QR preview, so only
 * backdrop/close/Escape are wired here — the triggers live with each view.
 *
 * State: reads the shared `adminState.cachedQRUrl` (admin/state.js).
 * Escape-close goes through the consolidated registry (admin/modal-escape.js).
 * `QRCode` is the global vendor lib loaded ahead of the admin bundle.
 *
 * No window shim: every caller stays inside the bundle — admin.js init drives
 * `setupQRModal()` once and the home-view handlers call `openQRModal()` (still
 * behind their `typeof openQRModal === 'function'` guards, which keep working
 * against the imported module binding). closeQRModal stays internal.
 */

import { adminState } from '../state.js';
import { registerModalClose } from '../modal-escape.js';

/**
 * Open QR modal with enlarged code
 */
export function openQRModal() {
    if (!adminState.cachedQRUrl) return;

    var modal = document.getElementById('qr-modal');
    var modalCode = document.getElementById('qr-modal-code');
    if (!modal || !modalCode) return;

    // Clear and render larger QR
    modalCode.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(modalCode, {
            text: adminState.cachedQRUrl,
            width: 280,
            height: 280,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    }

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    // Focus close button for accessibility
    var closeBtn = document.getElementById('qr-modal-close');
    if (closeBtn) closeBtn.focus();
}

/**
 * Close QR modal
 */
export function closeQRModal() {
    var modal = document.getElementById('qr-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

/**
 * Wire the QR modal once at init. The modal itself is shared between the
 * home-view tap-to-enlarge (BeatifyHome triggers openQRModal) and the
 * admin-playing view's QR preview, so only backdrop/close/escape are wired
 * here — the triggers live with each view.
 */
export function setupQRModal() {
    var modal = document.getElementById('qr-modal');
    var backdrop = modal ? modal.querySelector('.qr-modal-backdrop') : null;
    var closeBtn = document.getElementById('qr-modal-close');

    if (backdrop) backdrop.addEventListener('click', closeQRModal);
    if (closeBtn) closeBtn.addEventListener('click', closeQRModal);

    // #1402 B7: Escape handled by the consolidated setupModalEscapeHandler().
    registerModalClose('qr-modal', closeQRModal);
}

/**
 * #2621 — the in-game invite triggers.
 *
 * The join QR had exactly one trigger, `#home-qr-code` in `#home-view`, and
 * home-view is exited the moment the game leaves LOBBY. A guest arriving in
 * round 3 therefore left the host with no way to hand out the link, even
 * though the backend accepts late joins (`game/player_registry.py`). These are
 * the header buttons in the PLAYING and REVEAL sections; both open the same
 * modal, so there is one QR implementation on the admin page, not three.
 */
export const INVITE_TRIGGER_IDS = ['admin-invite-playing', 'admin-invite-reveal'];

/**
 * Wire the in-game invite buttons to the shared modal. Called once at init,
 * next to setupQRModal(); the buttons live in sections that are only shown
 * later, but they exist in the DOM from page load, so one wiring pass holds.
 */
export function setupInviteTriggers(doc = document) {
    INVITE_TRIGGER_IDS.forEach(function (id) {
        var btn = doc.getElementById(id);
        if (btn) btn.addEventListener('click', openQRModal);
    });
}

/**
 * Show the invite buttons only once a join URL is cached — openQRModal() is a
 * silent no-op without one, and a button that does nothing when tapped is
 * worse than no button. Called from the PLAYING/REVEAL renderers.
 */
export function syncInviteTriggers(doc = document) {
    INVITE_TRIGGER_IDS.forEach(function (id) {
        var btn = doc.getElementById(id);
        if (btn) btn.classList.toggle('hidden', !adminState.cachedQRUrl);
    });
}
