/**
 * Tests for BeatifyUtils.createReconnectGuard (#1397).
 *
 * Regression cover for "Duplicate WebSocket connections after visibilitychange
 * reconnect races pending backoff timer": the spectator dashboard scheduled a
 * setTimeout(connectWebSocket, delay) backoff reconnect in ws.onclose, but the
 * visibilitychange handler reconnected immediately WITHOUT cancelling that
 * pending timer — so it fired later and opened a SECOND parallel socket.
 *
 * dashboard.js is a classic global IIFE (window.dashboard = (...)()) whose live
 * socket lifecycle is covered by manual device QA, not unit tests. The pure,
 * shippable unit that fixes the race is this guard: schedule() always cancels
 * any in-flight timer, and cancel() lets an out-of-band connect kill it. These
 * tests prove exactly that contract end-to-end with fake timers.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

describe('BeatifyUtils.createReconnectGuard (#1397)', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('exists on the BeatifyUtils surface', () => {
        expect(typeof U.createReconnectGuard).toBe('function');
    });

    it('runs the scheduled reconnect once after the delay elapses', () => {
        const guard = U.createReconnectGuard();
        const connect = vi.fn();
        guard.schedule(connect, 30000);
        expect(guard.isPending()).toBe(true);

        expect(connect).not.toHaveBeenCalled();
        vi.advanceTimersByTime(30000);

        expect(connect).toHaveBeenCalledTimes(1);
        expect(guard.isPending()).toBe(false);
    });

    it('cancel() stops a pending backoff reconnect from firing (no duplicate WS)', () => {
        // Models ws.onclose scheduling a backoff reconnect...
        const guard = U.createReconnectGuard();
        const backoffConnect = vi.fn();
        guard.schedule(backoffConnect, 30000);
        expect(guard.isPending()).toBe(true);

        // ...then visibilitychange firing connectWebSocket(), which calls
        // guard.cancel() at the top before opening its own socket.
        guard.cancel();
        expect(guard.isPending()).toBe(false);

        // The orphaned backoff timer must never fire — otherwise it opens a
        // second parallel WebSocket.
        vi.advanceTimersByTime(60000);
        expect(backoffConnect).not.toHaveBeenCalled();
    });

    it('the visibilitychange race opens exactly ONE socket, not two', () => {
        // End-to-end model of the bug: a single connect() that (a) cancels any
        // pending timer and (b) opens a socket — mirroring dashboard.js's
        // connectWebSocket(). The backoff timer scheduled by onclose must be
        // swallowed by the immediate visibilitychange-driven connect.
        const guard = U.createReconnectGuard();
        let openSockets = 0;
        function connect() {
            guard.cancel();        // top of connectWebSocket() (#1397)
            openSockets++;         // new WebSocket(...)
        }

        // 1) Tab hidden: socket closed, onclose schedules a backoff reconnect.
        guard.schedule(connect, 30000);

        // 2) Tab visible again: visibilitychange sees CLOSED and connects now.
        connect();
        expect(openSockets).toBe(1);

        // 3) Time passes; the cancelled backoff timer must NOT add a 2nd socket.
        vi.advanceTimersByTime(60000);
        expect(openSockets).toBe(1);
    });

    it('schedule() supersedes an earlier pending timer (only the latest survives)', () => {
        const guard = U.createReconnectGuard();
        const first = vi.fn();
        const second = vi.fn();

        guard.schedule(first, 10000);
        guard.schedule(second, 5000); // cancels `first`

        vi.advanceTimersByTime(20000);
        expect(first).not.toHaveBeenCalled();
        expect(second).toHaveBeenCalledTimes(1);
    });

    it('cancel() is idempotent and safe with no pending timer', () => {
        const guard = U.createReconnectGuard();
        expect(() => { guard.cancel(); guard.cancel(); }).not.toThrow();
        expect(guard.isPending()).toBe(false);
    });
});
