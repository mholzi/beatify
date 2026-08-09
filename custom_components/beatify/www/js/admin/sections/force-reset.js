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

// #2040: no single cleanup step may hold the reload hostage. A rejected promise
// was always handled; a promise that never settles was not, and `await` on one
// silently skips everything below it — including the reload that is the whole
// point of the button.
export const RESET_STEP_TIMEOUT_MS = 4000;

/**
 * Await `promise`, but give up after `ms` and continue either way.
 *
 * Both outcomes are non-events for the caller: a reset that could not reach the
 * server, or could not unregister the service worker, still reloads. The log
 * line is the only difference between them.
 */
export function withResetTimeout(promise, ms, label, timer = setTimeout) {
    return Promise.race([
        Promise.resolve(promise).catch((err) => {
            console.warn(`[Reset] ${label} failed (continuing):`, err);
        }),
        new Promise((resolve) => {
            timer(() => {
                console.warn(`[Reset] ${label} did not settle in ${ms}ms (continuing)`);
                resolve();
            }, ms);
        }),
    ]);
}

/**
 * Force-reset Beatify: end any active game on the server, clear local
 * Beatify state, unregister the service worker, and reload. Designed to
 * recover from any stuck state — does NOT require an admin token. The
 * server endpoint is rate-limited per IP (3 per hour). On endpoint
 * failure we still clear local state + reload, because most stuck
 * symptoms are client-side and a reload often clears them anyway.
 *
 * Dependency-injected so the ordering and the never-settles case are testable
 * without a browser; `confirmReset()` binds the real globals.
 */
export async function performReset({
    authFetch,
    storage,
    serviceWorker,
    navigate,
    timeoutMs = RESET_STEP_TIMEOUT_MS,
    timer = setTimeout,
}) {
    try {
        // 1. Hit the server, but don't block local cleanup on its result.
        //    #2036: this POST is also what makes the wizard reappear. It drops
        //    the persisted setup blob; without that the reload re-seeds the
        //    speaker we are about to delete below (reconcileSavedSetup,
        //    "server wins" per #1927) and the host lands back on the
        //    ready-to-host screen.
        //    The POST stays first even though the local clear cannot hang: the
        //    auth layer reads its token before we start deleting keys, and
        //    reordering to chase a hypothetical would risk a real 401.
        await withResetTimeout(
            authFetch('/beatify/api/force-reset', { method: 'POST' }),
            timeoutMs,
            'force-reset POST',
            timer
        );

        // 2. Clear Beatify-owned localStorage entries.
        try {
            _BEATIFY_LS_KEYS.forEach((k) => storage.removeItem(k));
        } catch (err) {
            console.warn('[Reset] localStorage clear failed:', err);
        }

        // 3. Unregister the SW so a fresh registration happens on next load
        //    (matters since #780 fixed SW activation — stale caches can now
        //    actually exist). This is the step that hung on iOS in #2040:
        //    `getRegistrations()` never settled, so the reload below never ran
        //    and Reset looked like it did nothing at all.
        if (serviceWorker) {
            await withResetTimeout(
                serviceWorker
                    .getRegistrations()
                    .then((regs) => Promise.all(regs.map((r) => r.unregister()))),
                timeoutMs,
                'SW unregister',
                timer
            );
        }
    } finally {
        // 4. Reload onto the admin entry point — in `finally`, so no failure
        //    mode above can strand the host on the screen they asked to leave.
        navigate();
    }
}

function confirmReset() {
    closeResetModal();
    return performReset({
        authFetch: (url, opts) => BeatifyAuth.fetch(url, opts),
        storage: localStorage,
        serviceWorker: 'serviceWorker' in navigator ? navigator.serviceWorker : null,
        navigate: () => window.location.replace('/beatify/admin'),
    });
}

export function setupResetModal() {
    document.getElementById('reset-btn')?.addEventListener('click', showResetModal);
    document.getElementById('reset-confirm-btn')?.addEventListener('click', confirmReset);
    document.getElementById('reset-cancel-btn')?.addEventListener('click', closeResetModal);
    document.querySelector('#reset-modal .modal-backdrop')?.addEventListener('click', closeResetModal);

    // #1402 B7: reset modal previously had no Escape support — register it now.
    registerModalClose('reset-modal', closeResetModal);
}
