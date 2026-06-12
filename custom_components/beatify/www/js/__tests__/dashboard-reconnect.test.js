/**
 * Reconnect-backoff coverage for the spectator dashboard (#1398).
 *
 * The TV/monitor dashboard (dashboard.js) is a passive always-on display that
 * used to STOP reconnecting after MAX_RECONNECT_ATTEMPTS = 20 (~8 min of capped
 * backoff) and then sat on the "no game" view forever — a router reboot or HA
 * restart longer than that bricked the screen until someone physically woke the
 * tab (visibilitychange never fires on an always-on TV).
 *
 * The fix moves the backoff policy into the shared, DOM-free BeatifyUtils IIFE
 * (utils.js, importable in the node test env) and makes the dashboard retry
 * FOREVER with a capped delay. These tests assert the helper:
 *   - matches the exponential schedule for early attempts,
 *   - caps at maxDelay, and
 *   - keeps returning a finite, capped delay WELL past the old 20-attempt /
 *     ~8-minute give-up point (i.e. it never "gives up").
 */
import { describe, it, expect } from 'vitest';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

describe('BeatifyUtils.reconnectBackoffDelay (#1398)', () => {
    it('is exported by BeatifyUtils', () => {
        expect(typeof U.reconnectBackoffDelay).toBe('function');
    });

    it('follows base * 2^(attempt-1) for early 1-based attempts', () => {
        expect(U.reconnectBackoffDelay(1)).toBe(1000);   // 1s
        expect(U.reconnectBackoffDelay(2)).toBe(2000);   // 2s
        expect(U.reconnectBackoffDelay(3)).toBe(4000);   // 4s
        expect(U.reconnectBackoffDelay(4)).toBe(8000);   // 8s
        expect(U.reconnectBackoffDelay(5)).toBe(16000);  // 16s
    });

    it('caps at the default 30s ceiling once the schedule exceeds it', () => {
        // 2^5 = 32000 > 30000 → clamped.
        expect(U.reconnectBackoffDelay(6)).toBe(30000);
        expect(U.reconnectBackoffDelay(7)).toBe(30000);
        expect(U.reconnectBackoffDelay(20)).toBe(30000);
    });

    it('honours a custom baseDelay / maxDelay', () => {
        expect(U.reconnectBackoffDelay(1, { baseDelay: 500, maxDelay: 5000 })).toBe(500);
        expect(U.reconnectBackoffDelay(2, { baseDelay: 500, maxDelay: 5000 })).toBe(1000);
        // 500 * 2^4 = 8000 > 5000 → clamped to maxDelay.
        expect(U.reconnectBackoffDelay(5, { baseDelay: 500, maxDelay: 5000 })).toBe(5000);
    });

    it('treats non-positive / non-numeric attempts as the first attempt', () => {
        expect(U.reconnectBackoffDelay(0)).toBe(1000);
        expect(U.reconnectBackoffDelay(-3)).toBe(1000);
        expect(U.reconnectBackoffDelay(undefined)).toBe(1000);
        expect(U.reconnectBackoffDelay('nope')).toBe(1000);
    });

    it('NEVER gives up: stays finite and capped far past the old ~8 min limit', () => {
        // The old dashboard stopped at attempt 20. Prove the policy keeps
        // yielding a valid, capped delay long after that — i.e. an always-on TV
        // keeps retrying indefinitely instead of freezing on "no game".
        for (const attempt of [21, 50, 100, 1000, 10000, 1e6]) {
            const delay = U.reconnectBackoffDelay(attempt);
            expect(Number.isFinite(delay)).toBe(true);
            expect(delay).toBe(30000); // capped, never NaN / Infinity / 0
        }
    });

    it('a forever-retry loop accumulates real wall-clock time past 8 minutes', () => {
        // Sanity model of the dashboard's onclose loop: sum the delays of the
        // first 20 attempts (the old cap) and confirm we are nowhere near
        // "done" — there are unbounded further attempts each adding up to 30s.
        let total = 0;
        for (let attempt = 1; attempt <= 20; attempt++) {
            total += U.reconnectBackoffDelay(attempt);
        }
        // ~8 minutes was the OLD terminal point; the loop simply continues.
        expect(total).toBeGreaterThan(7 * 60 * 1000);
        // Attempt 21 (which the old code never reached) still returns a delay.
        expect(U.reconnectBackoffDelay(21)).toBe(30000);
    });
});
