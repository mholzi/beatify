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
