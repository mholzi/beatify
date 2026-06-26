/**
 * Beatify Admin — Force-Reset / recovery modal section (#1589, cont. #1279 4b).
 *
 * Extracted verbatim from admin.js (#777 follow-up): the emergency
 * "force-reset" modal that recovers from any stuck state — ends the active
 * game server-side, clears Beatify-owned localStorage, unregisters the service
 * worker, and reloads onto the admin entry point. Deliberately requires NO
 * admin token (the server endpoint is IP-rate-limited, 3/hour) so it can
 * recover even when the token is the thing that's broken.
 *
 * Self-contained: depends only on `registerModalClose` (admin/modal-escape.js)
 * and the `BeatifyAuth` global. No adminState, no core admin.js functions.
 *
 * No window shim: `setupResetModal()` is the only external entry point
 * (admin.js init); show/close/confirm are wired internally via addEventListener.
 */

import { registerModalClose } from '../modal-escape.js';

// localStorage keys Beatify writes — cleared on force-reset.
// Add new keys here if you introduce more, otherwise stuck state survives.
const _BEATIFY_LS_KEYS = [
    'beatify_wizard_state',
    'beatify_last_player',
    'beatify_game_settings',
    'beatify_party_lights',
    'beatify_tts',
    'beatify_admin_token',
    'beatify_admin_token_game_id',
];

function showResetModal() {
    document.getElementById('reset-modal')?.classList.remove('hidden');
}

function closeResetModal() {
    document.getElementById('reset-modal')?.classList.add('hidden');
}

/**
 * Force-reset Beatify: end any active game on the server, clear local
 * Beatify state, unregister the service worker, and reload. Designed to
 * recover from any stuck state — does NOT require an admin token. The
 * server endpoint is rate-limited per IP (3 per hour). On endpoint
 * failure we still clear local state + reload, because most stuck
 * symptoms are client-side and a reload often clears them anyway.
 */
async function confirmReset() {
    closeResetModal();

    // 1. Hit the server, but don't block local cleanup on its result.
    try {
        await BeatifyAuth.fetch('/beatify/api/force-reset', { method: 'POST' });
    } catch (err) {
        console.warn('[Reset] force-reset POST failed (continuing with local cleanup):', err);
    }

    // 2. Clear Beatify-owned localStorage entries.
    try {
        _BEATIFY_LS_KEYS.forEach((k) => localStorage.removeItem(k));
    } catch (err) {
        console.warn('[Reset] localStorage clear failed:', err);
    }

    // 3. Unregister the SW so a fresh registration happens on next load
    //    (matters since #780 fixed SW activation — stale caches can now
    //    actually exist).
    try {
        if ('serviceWorker' in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations();
            await Promise.all(regs.map((r) => r.unregister()));
        }
    } catch (err) {
        console.warn('[Reset] SW unregister failed:', err);
    }

    // 4. Reload onto the admin entry point.
    window.location.replace('/beatify/admin');
}

export function setupResetModal() {
    document.getElementById('reset-btn')?.addEventListener('click', showResetModal);
    document.getElementById('reset-confirm-btn')?.addEventListener('click', confirmReset);
    document.getElementById('reset-cancel-btn')?.addEventListener('click', closeResetModal);
    document.querySelector('#reset-modal .modal-backdrop')?.addEventListener('click', closeResetModal);

    // #1402 B7: reset modal previously had no Escape support — register it now.
    registerModalClose('reset-modal', closeResetModal);
}
