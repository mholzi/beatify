/**
 * Unit tests for the pure helpers extracted into admin/api.js (#1279, Schritt 3/6).
 *
 * Step 3 moves the admin WebSocket hub (connect / message-dispatch / reconnect)
 * out of admin.js into admin/api.js. The live-socket lifecycle is not unit-
 * tested here (it needs a real WS + DOM + the injected admin callbacks — that's
 * covered by the mandatory manual device QA). What IS cleanly testable are the
 * two side-effect-free helpers the hub builds on:
 *
 *   - buildWsUrl(location)   — ws:/wss: URL builder from a location-like object
 *   - reconnectDelay(attempt) — exponential backoff (1-based), capped at 30s
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { buildWsUrl, reconnectDelay } from '../admin/api.js';

const tick = () => new Promise((r) => setTimeout(r, 0));

describe('buildWsUrl', () => {
    it('uses wss: on an https location', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'example.com' }))
            .toBe('wss://example.com/beatify/ws');
    });

    it('uses ws: on an http location', () => {
        expect(buildWsUrl({ protocol: 'http:', host: 'example.com' }))
            .toBe('ws://example.com/beatify/ws');
    });

    it('uses ws: for any non-https protocol (e.g. file:)', () => {
        expect(buildWsUrl({ protocol: 'file:', host: 'localhost:8123' }))
            .toBe('ws://localhost:8123/beatify/ws');
    });

    it('preserves host:port', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'ha.local:8123' }))
            .toBe('wss://ha.local:8123/beatify/ws');
    });

    it('always targets the /beatify/ws path', () => {
        expect(buildWsUrl({ protocol: 'https:', host: 'x' })).toMatch(/\/beatify\/ws$/);
    });
});

describe('reconnectDelay', () => {
    it('returns 1000ms for the first attempt', () => {
        expect(reconnectDelay(1)).toBe(1000);
    });

    it('doubles each attempt (exponential backoff)', () => {
        expect(reconnectDelay(2)).toBe(2000);
        expect(reconnectDelay(3)).toBe(4000);
        expect(reconnectDelay(4)).toBe(8000);
        expect(reconnectDelay(5)).toBe(16000);
    });

    it('caps the delay at 30000ms', () => {
        // 2^5 * 1000 = 32000 > cap, and everything beyond stays at the cap
        expect(reconnectDelay(6)).toBe(30000);
        expect(reconnectDelay(10)).toBe(30000);
        expect(reconnectDelay(100)).toBe(30000);
    });
});

/**
 * #1393 — the admin WS UNAUTHORIZED recovery-exhaustion path must NOT bounce
 * Companion bypass-mode users to OAuth (which lands on the Invalid-redirect-URI
 * screen). Instead it surfaces an actionable local-network hint and stops.
 *
 * The live WS lifecycle is otherwise untested (see the file header), but the
 * message-dispatch branch is a pure switch over `data` + injected `deps` +
 * the global `BeatifyAuth`, so we can drive it directly. MAX recoveries = 2,
 * so the 3rd UNAUTHORIZED hits the exhaustion branch.
 */
describe('handleAdminWsMessage UNAUTHORIZED recovery exhaustion (#1393)', () => {
    afterEach(() => {
        delete globalThis.BeatifyAuth;
        delete globalThis.window;
    });

    // Fresh module per test so the module-private adminWsAuthRecoveryAttempts
    // counter starts at 0 (it is intentionally not exported/resettable).
    async function setup(bypass) {
        vi.resetModules();
        const api = await import('../admin/api.js');
        const calls = { showError: [], logout: 0, login: 0, rejections: 0, api };
        api.initAdminApi({ showError: (m) => calls.showError.push(m), debug: () => {} });
        globalThis.window = {
            location: { protocol: 'https:', host: 'ha.example' },
            BeatifyI18n: undefined,
        };
        globalThis.BeatifyAuth = {
            isCompanionBypassMode: () => bypass,
            // In bypass mode handleServerRejection resolves null without nav;
            // here we just mirror that so the recovery .then runs and clears
            // the recovering flag between attempts.
            handleServerRejection: () => { calls.rejections++; return Promise.resolve(null); },
            getAccessToken: () => Promise.resolve(null),
            logout: () => { calls.logout++; },
            login: () => { calls.login++; },
        };
        return calls;
    }

    // Drive N UNAUTHORIZED messages, awaiting the microtask between each so the
    // in-flight handleServerRejection().then() clears adminWsAuthRecovering.
    async function fireUnauthorized(api, n) {
        for (let i = 0; i < n; i++) {
            api.handleAdminWsMessage({ type: 'error', code: 'UNAUTHORIZED', message: 'nope' });
            await tick();
        }
    }

    it('Companion bypass mode: shows local-network hint, never calls logout()/login()', async () => {
        const calls = await setup(true);
        await fireUnauthorized(calls.api, 3); // attempts 1,2 recover; 3rd exhausts
        expect(calls.login).toBe(0);
        expect(calls.logout).toBe(0);
        expect(calls.showError).toHaveLength(1);
        expect(calls.showError[0]).toMatch(/local network access from the Companion app/i);
    });

    it('Normal browser: exhaustion still bounces to OAuth re-login (no regression)', async () => {
        const calls = await setup(false);
        await fireUnauthorized(calls.api, 3);
        expect(calls.logout).toBe(1);
        expect(calls.login).toBe(1);
        // The exhaustion toast uses the wsAuthFailed/HA-rejected wording, not
        // the Companion hint.
        expect(calls.showError).toHaveLength(1);
        expect(calls.showError[0]).toMatch(/rejected the access token/i);
    });
});

/**
 * #1402 B7 — a WS `error` must only be treated as a start failure (reset the
 * home "Start game" button + blocking showError) while a start_game is pending.
 * Errors for unrelated mid-game commands (set_volume, stop_song, next_round, …)
 * must NOT rewrite the home button or pop a blocking dialog — they go to a
 * non-blocking console.warn instead. The flag is set by sendAdminWs() on a
 * start_game payload (only over an OPEN socket) and cleared by the next `state`
 * message OR by the start-failure branch itself.
 */
describe('handleAdminWsMessage start-failure gating (#1402 B7)', () => {
    // Minimal fake WebSocket so sendAdminWs() sees an OPEN socket and arms the
    // pending flag (mirrors admin-ws-lifecycle.test.js).
    const WS_OPEN = 1;
    let liveSockets = [];
    class FakeWebSocket {
        constructor(url) {
            this.url = url;
            this.readyState = 0;
            this.onopen = this.onmessage = this.onclose = this.onerror = null;
            liveSockets.push(this);
        }
        send() {}
        close() { this.readyState = 3; }
    }
    FakeWebSocket.CONNECTING = 0;
    FakeWebSocket.OPEN = WS_OPEN;
    FakeWebSocket.CLOSED = 3;

    let resolveToken;

    afterEach(() => {
        delete globalThis.BeatifyAuth;
        delete globalThis.window;
        delete globalThis.WebSocket;
        delete globalThis.BeatifyI18n;
        vi.restoreAllMocks();
    });

    // Boot a fresh module with injected deps + an OPEN fake socket so sendAdminWs
    // can arm startPending through the real public path.
    async function setup() {
        vi.resetModules();
        liveSockets = [];
        globalThis.WebSocket = FakeWebSocket;
        globalThis.window = { location: { protocol: 'https:', host: 'ha.local' } };
        globalThis.BeatifyAuth = {
            getAccessToken: () => new Promise((res) => { resolveToken = res; }),
            isCompanionBypassMode: () => false,
        };
        globalThis.BeatifyI18n = { t: () => '' };
        const api = await import('../admin/api.js?ts=' + Math.random());
        const calls = { showError: [], resetHomeStartButton: 0 };
        api.initAdminApi({
            showError: (m) => calls.showError.push(m),
            resetHomeStartButton: () => { calls.resetHomeStartButton++; },
            handleAdminStateUpdate: () => {},
            debug: () => {},
            stopLobbyPolling: () => {},
        });
        // Open the socket so isAdminWsOpen() is true.
        const p = api.connectAdminWebSocket();
        resolveToken('tok');
        await p;
        liveSockets[0].readyState = WS_OPEN;
        return { api, calls };
    }

    it('does NOT reset the home button for an unrelated command error when no start is pending', async () => {
        const { api, calls } = await setup();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        api.handleAdminWsMessage({ type: 'error', code: 'INVALID_ACTION', message: 'volume failed' });
        expect(calls.resetHomeStartButton).toBe(0);
        expect(calls.showError).toHaveLength(0);
        expect(warn).toHaveBeenCalled();
    });

    it('DOES reset the home button + shows error for an error while a start_game is pending', async () => {
        const { api, calls } = await setup();
        const sent = api.sendAdminWs({ type: 'admin', action: 'start_game' });
        expect(sent).toBe(true); // confirms the socket was OPEN → flag armed
        api.handleAdminWsMessage({ type: 'error', code: 'MEDIA_PLAYER_UNAVAILABLE', message: 'player gone' });
        expect(calls.resetHomeStartButton).toBe(1);
        expect(calls.showError).toContain('player gone');
    });

    it('a `state` message clears the pending flag so a later error is non-blocking', async () => {
        const { api, calls } = await setup();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        expect(api.sendAdminWs({ type: 'admin', action: 'start_game' })).toBe(true);
        api.handleAdminWsMessage({ type: 'state' }); // start succeeded → clears flag
        api.handleAdminWsMessage({ type: 'error', code: 'NO_SONGS_REMAINING', message: 'oops' });
        expect(calls.resetHomeStartButton).toBe(0);
        expect(calls.showError).toHaveLength(0);
        expect(warn).toHaveBeenCalled();
    });

    it('a non-start command does NOT arm the flag (sendAdminWs ignores set_volume)', async () => {
        const { api, calls } = await setup();
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
        api.sendAdminWs({ type: 'admin', action: 'set_volume', direction: 'up' });
        api.handleAdminWsMessage({ type: 'error', code: 'INVALID_ACTION', message: 'vol fail' });
        expect(calls.resetHomeStartButton).toBe(0);
        expect(warn).toHaveBeenCalled();
    });
});
