/**
 * #1396 — Wake lock must be acquired SYNCHRONOUSLY inside the user-gesture
 * window on the rematch-confirm and legacy #start-game paths (same defect class
 * as #1122/#1207).
 *
 * The fix routes both gesture entries through `acquireWakeLockFirst()`, which
 * calls the wake-lock requester before any await/WS send. iOS HA Companion
 * WKWebView consumes the user-activation after the first `await`, so the Layer 2
 * NoSleep silent-video fallback only works if the lock is requested first.
 *
 * These tests pin the ordering contract: `requestWakeLock` is invoked
 * synchronously, BEFORE the (possibly-async) start/rematch action begins its
 * own async work.
 */
import { describe, it, expect, vi } from 'vitest';
import { acquireWakeLockFirst } from '../admin/util.js';

describe('acquireWakeLockFirst (#1396 gesture-first wake lock)', () => {
    it('calls requestWakeLock synchronously before invoking the action', () => {
        const calls = [];
        const requestWakeLock = vi.fn(() => calls.push('wakelock'));
        const action = vi.fn(() => calls.push('action'));

        acquireWakeLockFirst(requestWakeLock, action);

        expect(requestWakeLock).toHaveBeenCalledTimes(1);
        expect(action).toHaveBeenCalledTimes(1);
        // wake lock MUST come first — this is the whole point of the fix.
        expect(calls).toEqual(['wakelock', 'action']);
    });

    it('acquires the wake lock before the action awaits anything (rematch WS path)', async () => {
        const calls = [];
        const requestWakeLock = vi.fn(() => calls.push('wakelock'));

        // Models confirmRematch()'s WS path: send + return synchronously, no await.
        const wsRematch = vi.fn(() => {
            calls.push('send-rematch_game');
            return undefined;
        });

        const result = acquireWakeLockFirst(requestWakeLock, wsRematch);

        expect(result).toBeUndefined();
        // Wake lock acquired strictly before the WS send (gesture still active).
        expect(calls).toEqual(['wakelock', 'send-rematch_game']);
    });

    it('acquires the wake lock before the action starts awaiting fetch (legacy startGame path)', async () => {
        const calls = [];
        const requestWakeLock = vi.fn(() => calls.push('wakelock'));

        // Models startGame()'s legacy path: the first thing it does is await fetch.
        const startGameAction = vi.fn(async () => {
            calls.push('before-await');
            await Promise.resolve();
            calls.push('after-await');
        });

        const p = acquireWakeLockFirst(requestWakeLock, startGameAction);

        // Synchronously (before any microtask), the wake lock + the pre-await
        // body have run; the wake lock is first.
        expect(calls).toEqual(['wakelock', 'before-await']);
        await p;
        expect(calls).toEqual(['wakelock', 'before-await', 'after-await']);
    });

    it('returns the action result (e.g. its promise) for the caller to await', () => {
        const sentinel = Promise.resolve('ok');
        const result = acquireWakeLockFirst(() => {}, () => sentinel);
        expect(result).toBe(sentinel);
    });

    it('is a no-op-safe guard: tolerates a missing requestWakeLock or action', () => {
        expect(() => acquireWakeLockFirst(undefined, undefined)).not.toThrow();
        const action = vi.fn(() => 42);
        // Even without a requestWakeLock, the action still runs.
        expect(acquireWakeLockFirst(null, action)).toBe(42);
        expect(action).toHaveBeenCalledTimes(1);
    });
});
