/**
 * #2040 — Reset must reload even when a cleanup step never settles.
 *
 * Field report (Markus, 09.08. 20:05): pressing Reset left the host screen
 * exactly as it was; only a manual browser reload landed on the wizard. The
 * Home Assistant log proves the server half ran (`Game ended: heQo0XwKlGA`,
 * 20:05:36), and the wizard appearing after the manual reload proves the
 * localStorage clear ran too. So steps 1 and 2 completed and step 4 — the
 * reload — did not. Between them sits `navigator.serviceWorker
 * .getRegistrations()`, awaited without a deadline, on iOS Safari.
 *
 * A rejected promise was always handled. A promise that never settles was not:
 * `await` on one skips every line below it, silently. These tests pin the two
 * properties that make the button honest — every step has a deadline, and the
 * navigation happens no matter what.
 */
import { describe, it, expect, vi } from 'vitest';
import {
    performReset,
    withResetTimeout,
    RESET_STEP_TIMEOUT_MS,
} from '../admin/sections/force-reset.js';

/** A promise that never settles — the actual iOS failure mode. */
const NEVER = () => new Promise(() => {});

/** setTimeout double that fires immediately, so tests don't wait 4 seconds. */
const instantTimer = (fn) => fn();

function deps(overrides = {}) {
    return {
        authFetch: vi.fn(() => Promise.resolve({ ok: true })),
        storage: { removeItem: vi.fn() },
        serviceWorker: { getRegistrations: vi.fn(() => Promise.resolve([])) },
        navigate: vi.fn(),
        timer: instantTimer,
        ...overrides,
    };
}

describe('performReset (#2040 reload is not hostage to cleanup)', () => {
    it('reloads on the happy path', async () => {
        const d = deps();
        await performReset(d);

        expect(d.authFetch).toHaveBeenCalledWith('/beatify/api/force-reset', {
            method: 'POST',
        });
        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads when the service worker lookup never settles', async () => {
        // The reported bug, reduced to one line.
        const d = deps({ serviceWorker: { getRegistrations: NEVER } });
        await performReset(d);

        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads when unregistering a service worker never settles', async () => {
        const d = deps({
            serviceWorker: {
                getRegistrations: () => Promise.resolve([{ unregister: NEVER }]),
            },
        });
        await performReset(d);

        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads when the server POST never settles', async () => {
        const d = deps({ authFetch: NEVER });
        await performReset(d);

        // The local half still has to run — the reload depends on it.
        expect(d.storage.removeItem).toHaveBeenCalled();
        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads when the server POST rejects', async () => {
        const d = deps({ authFetch: () => Promise.reject(new Error('offline')) });
        await performReset(d);

        expect(d.storage.removeItem).toHaveBeenCalled();
        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads when localStorage throws (private mode)', async () => {
        const d = deps({
            storage: {
                removeItem: vi.fn(() => {
                    throw new Error('QuotaExceededError');
                }),
            },
        });
        await performReset(d);

        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('reloads on a browser without service workers', async () => {
        const d = deps({ serviceWorker: null });
        await performReset(d);

        expect(d.navigate).toHaveBeenCalledTimes(1);
    });

    it('clears every Beatify-owned key', async () => {
        const d = deps();
        await performReset(d);

        const cleared = d.storage.removeItem.mock.calls.map((c) => c[0]);
        expect(cleared).toEqual(
            expect.arrayContaining([
                'beatify_wizard_state',
                'beatify_last_player',
                'beatify_game_settings',
                'beatify_admin_token',
            ])
        );
    });

    it('clears local state before navigating away', async () => {
        const order = [];
        const d = deps({
            storage: { removeItem: () => order.push('clear') },
            navigate: () => order.push('navigate'),
        });
        await performReset(d);

        expect(order[order.length - 1]).toBe('navigate');
        expect(order).toContain('clear');
    });

    it('navigates exactly once even if everything stalls at once', async () => {
        const d = deps({
            authFetch: NEVER,
            serviceWorker: { getRegistrations: NEVER },
        });
        await performReset(d);

        expect(d.navigate).toHaveBeenCalledTimes(1);
    });
});

describe('withResetTimeout', () => {
    it('resolves with the deadline when the promise never settles', async () => {
        const fired = vi.fn();
        await withResetTimeout(NEVER(), 10, 'test step', (fn) => {
            fired();
            fn();
        });

        expect(fired).toHaveBeenCalled();
    });

    it('swallows a rejection instead of propagating it', async () => {
        await expect(
            withResetTimeout(Promise.reject(new Error('boom')), 10, 'test step', instantTimer)
        ).resolves.toBeUndefined();
    });

    it('ships a deadline long enough for a slow instance', () => {
        // Not a magic number for its own sake: a loaded HA answering a POST in
        // three seconds must still be waited for, and a host staring at an
        // unchanged screen must not wait much longer than that.
        expect(RESET_STEP_TIMEOUT_MS).toBeGreaterThanOrEqual(3000);
        expect(RESET_STEP_TIMEOUT_MS).toBeLessThanOrEqual(8000);
    });
});
