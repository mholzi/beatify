/**
 * Unified WS reconnect for the player page (#1662).
 *
 * player-core.js used to carry TWO near-identical `onclose` blocks (session
 * reconnect vs. name-based join) plus a bespoke LINEAR backoff, while the
 * spectator dashboard used a capped-EXPONENTIAL curve. That divergence was both
 * a behavioural inconsistency and a maintenance hazard. The fix moves the
 * reconnect orchestration into the shared, DOM-free BeatifyUtils
 * (createWsCloseHandler) and points the player backoff at the same
 * reconnectBackoffDelay the dashboard already uses.
 *
 * These tests assert, against the REAL shared helpers (not a re-implementation):
 *   1. the unified player backoff schedule grows exponentially and caps, and
 *   2. the shared onclose handler runs its side effects: heartbeat teardown,
 *      the intentional-leave short-circuit, the reconnect scheduling under the
 *      attempt cap, and the give-up path at the cap.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

// Mirror player-core.js constants (#1662). Cap lowered 10->7 to bound the
// exponential-backoff give-up wallclock (~64s instead of ~181s).
const MAX_RECONNECT_ATTEMPTS = 7;
const MAX_RECONNECT_DELAY_MS = 30000;

// The exact getReconnectDelay() the player now uses (delegates to the shared
// helper with the player cap; reconnectAttempts is 1-based at call time).
function playerReconnectDelay(state) {
    return U.reconnectBackoffDelay(state.reconnectAttempts, { maxDelay: MAX_RECONNECT_DELAY_MS });
}

describe('unified player reconnect backoff (#1662)', () => {
    it('is exported by BeatifyUtils', () => {
        expect(typeof U.createWsCloseHandler).toBe('function');
        expect(typeof U.reconnectBackoffDelay).toBe('function');
    });

    it('grows exponentially then caps at the 30s player ceiling', () => {
        // 1-based attempts as the onclose handler increments them.
        const delays = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((attempt) =>
            U.reconnectBackoffDelay(attempt, { maxDelay: MAX_RECONNECT_DELAY_MS })
        );
        expect(delays.slice(0, 6)).toEqual([1000, 2000, 4000, 8000, 16000, 30000]);
        // Every step at least doubles until the cap, and never exceeds it.
        for (let i = 1; i < delays.length; i++) {
            expect(delays[i]).toBeLessThanOrEqual(MAX_RECONNECT_DELAY_MS);
            if (delays[i] < MAX_RECONNECT_DELAY_MS) {
                expect(delays[i]).toBe(delays[i - 1] * 2);
            } else {
                expect(delays[i]).toBe(MAX_RECONNECT_DELAY_MS);
            }
        }
        // Once capped it stays capped (finite, never NaN/Infinity).
        expect(delays[delays.length - 1]).toBe(MAX_RECONNECT_DELAY_MS);
    });
});

describe('BeatifyUtils.createWsCloseHandler side effects (#1662)', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    // Build a handler wired exactly like player-core's makeSocketCloseHandler.
    function makeHandler(state, spies, scheduleReconnect) {
        return U.createWsCloseHandler({
            state,
            maxAttempts: MAX_RECONNECT_ATTEMPTS,
            getDelay: () => playerReconnectDelay(state),
            scheduleReconnect,
            stopHeartbeat: spies.stopHeartbeat,
            onReconnecting: spies.onReconnecting,
            onGiveUp: spies.onGiveUp,
        });
    }

    function freshState(over = {}) {
        return {
            playerName: 'Alice',
            reconnectAttempts: 0,
            isReconnecting: false,
            intentionalLeave: false,
            ...over,
        };
    }

    function freshSpies() {
        return {
            stopHeartbeat: vi.fn(),
            onReconnecting: vi.fn(),
            onGiveUp: vi.fn(),
        };
    }

    it('always stops the heartbeat, even on an intentional leave', () => {
        const state = freshState({ intentionalLeave: true });
        const spies = freshSpies();
        const reconnect = vi.fn();
        makeHandler(state, spies, reconnect)();

        expect(spies.stopHeartbeat).toHaveBeenCalledTimes(1);
        // Intentional leave: flag consumed, NO reconnect, NO UI churn.
        expect(state.intentionalLeave).toBe(false);
        expect(state.isReconnecting).toBe(false);
        expect(spies.onReconnecting).not.toHaveBeenCalled();
        vi.advanceTimersByTime(60000);
        expect(reconnect).not.toHaveBeenCalled();
    });

    it('under the cap: flags reconnecting, bumps the attempt, and schedules the reconnect after the backoff delay', () => {
        const state = freshState();
        const spies = freshSpies();
        const reconnect = vi.fn();
        makeHandler(state, spies, reconnect)();

        expect(state.isReconnecting).toBe(true);
        expect(state.reconnectAttempts).toBe(1);
        // onReconnecting gets the 1-based attempt + the first backoff delay (1s).
        expect(spies.onReconnecting).toHaveBeenCalledWith(1, 1000);
        expect(spies.onGiveUp).not.toHaveBeenCalled();

        // Reconnect fires only after the delay elapses (exactly once).
        expect(reconnect).not.toHaveBeenCalled();
        vi.advanceTimersByTime(999);
        expect(reconnect).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(reconnect).toHaveBeenCalledTimes(1);
    });

    it('successive closes schedule an exponentially growing delay', () => {
        const state = freshState();
        const spies = freshSpies();
        const handler = makeHandler(state, spies, vi.fn());

        handler(); // attempt 1 -> 1000
        handler(); // attempt 2 -> 2000
        handler(); // attempt 3 -> 4000
        expect(spies.onReconnecting.mock.calls.map((c) => c[1])).toEqual([1000, 2000, 4000]);
        expect(state.reconnectAttempts).toBe(3);
    });

    it('at the cap: clears reconnecting and runs the give-up hook, scheduling nothing', () => {
        const state = freshState({ reconnectAttempts: MAX_RECONNECT_ATTEMPTS });
        const spies = freshSpies();
        const reconnect = vi.fn();
        makeHandler(state, spies, reconnect)();

        expect(state.isReconnecting).toBe(false);
        expect(spies.onGiveUp).toHaveBeenCalledTimes(1);
        expect(spies.onReconnecting).not.toHaveBeenCalled();
        vi.advanceTimersByTime(60000);
        expect(reconnect).not.toHaveBeenCalled();
    });

    it('no player name: does nothing beyond heartbeat teardown (no reconnect, no give-up)', () => {
        const state = freshState({ playerName: null });
        const spies = freshSpies();
        const reconnect = vi.fn();
        makeHandler(state, spies, reconnect)();

        expect(spies.stopHeartbeat).toHaveBeenCalledTimes(1);
        expect(spies.onReconnecting).not.toHaveBeenCalled();
        expect(spies.onGiveUp).not.toHaveBeenCalled();
        vi.advanceTimersByTime(60000);
        expect(reconnect).not.toHaveBeenCalled();
    });

    it('routes to the caller-supplied reconnect target (session vs name-join)', () => {
        // Proves the ONLY per-socket difference — the reconnect target — is
        // preserved, while all guard/UI side effects are shared.
        const sessionState = freshState();
        const sessionReconnect = vi.fn();
        makeHandler(sessionState, freshSpies(), sessionReconnect)();
        vi.advanceTimersByTime(1000);
        expect(sessionReconnect).toHaveBeenCalledTimes(1);

        const nameState = freshState();
        const nameReconnect = vi.fn();
        makeHandler(nameState, freshSpies(), nameReconnect)();
        vi.advanceTimersByTime(1000);
        expect(nameReconnect).toHaveBeenCalledTimes(1);
    });
});
