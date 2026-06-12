/**
 * Lifecycle regression tests for the admin WS race fixed in #1395.
 *
 * Two defects were addressed in admin/api.js:
 *   1. connectAdminWebSocket() awaited getAccessToken() BEFORE the
 *      already-connected check, and that check only matched readyState OPEN —
 *      so a CONNECTING socket slipped through and concurrent callers each
 *      created a new socket, orphaning the earlier ones. The guard now runs
 *      BEFORE the await, treats CONNECTING as connected, and an
 *      `adminWsConnecting` coalesce flag covers the await window.
 *   2. onclose unconditionally did `adminWs = null`. After a reconnect or the
 *      UNAUTHORIZED recovery replaced adminWs, a dead socket's deferred onclose
 *      nulled the *fresh* socket — isAdminWsOpen() then reported disconnected
 *      and the healthy socket leaked. onclose now bails unless it is still the
 *      active socket.
 *
 * Globals (WebSocket, BeatifyAuth, window) are browser-supplied; we stub them.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// --- minimal fake WebSocket -------------------------------------------------
const WS_CONNECTING = 0;
const WS_OPEN = 1;
const WS_CLOSED = 3;

let liveSockets = [];

class FakeWebSocket {
    constructor(url) {
        this.url = url;
        this.readyState = WS_CONNECTING;
        this.sent = [];
        this.onopen = null;
        this.onmessage = null;
        this.onclose = null;
        this.onerror = null;
        liveSockets.push(this);
    }
    send(data) {
        this.sent.push(data);
    }
    close() {
        this.readyState = WS_CLOSED;
    }
    // test helpers
    _open() {
        this.readyState = WS_OPEN;
        if (this.onopen) this.onopen();
    }
    _fireClose() {
        this.readyState = WS_CLOSED;
        if (this.onclose) this.onclose();
    }
}
FakeWebSocket.CONNECTING = WS_CONNECTING;
FakeWebSocket.OPEN = WS_OPEN;
FakeWebSocket.CLOSED = WS_CLOSED;

let resolveToken;

function installGlobals() {
    liveSockets = [];
    globalThis.WebSocket = FakeWebSocket;
    globalThis.window = { location: { protocol: 'https:', host: 'ha.local' } };
    globalThis.BeatifyAuth = {
        // Deferred token: tests resolve it manually to exercise the await window.
        getAccessToken: vi.fn(() => new Promise((res) => { resolveToken = res; })),
        isCompanionBypassMode: vi.fn(() => false),
    };
}

// Re-import the module fresh each test so the encapsulated adminWs/connecting
// state never leaks between cases.
async function loadApi() {
    vi.resetModules();
    const mod = await import('../admin/api.js?ts=' + Math.random());
    return mod;
}

beforeEach(() => {
    installGlobals();
});

describe('#1395 connect guard: CONNECTING + concurrent callers coalesce', () => {
    it('does not open a second socket while the first is still CONNECTING', async () => {
        const api = await loadApi();

        // First caller: starts, parks on the token await.
        const p1 = api.connectAdminWebSocket();
        // Second concurrent caller while p1 is awaiting its token — must coalesce
        // via the adminWsConnecting flag and NOT start a second connect.
        const p2 = api.connectAdminWebSocket();

        // Resolve the (single) token request and let both settle.
        resolveToken('tok-abc');
        await p1;
        await p2;

        // Exactly one socket was created.
        expect(liveSockets.length).toBe(1);
        // Only one getAccessToken call happened — the second caller bailed early.
        expect(BeatifyAuth.getAccessToken).toHaveBeenCalledTimes(1);
        expect(api.getAdminWs()).toBe(liveSockets[0]);
    });

    it('a caller arriving while a socket is CONNECTING (post-assign) returns early', async () => {
        const api = await loadApi();

        const p1 = api.connectAdminWebSocket();
        resolveToken('tok-abc');
        await p1;

        const sock = api.getAdminWs();
        expect(sock.readyState).toBe(WS_CONNECTING); // not yet OPEN

        // New caller now: CONNECTING must count as "already connecting".
        const p2 = api.connectAdminWebSocket();
        // p2 must not even request a token (guard is before the await).
        await p2;

        expect(liveSockets.length).toBe(1);
        expect(BeatifyAuth.getAccessToken).toHaveBeenCalledTimes(1);
        expect(api.getAdminWs()).toBe(sock);
    });

    it('a caller arriving while a socket is OPEN returns early', async () => {
        const api = await loadApi();

        const p1 = api.connectAdminWebSocket();
        resolveToken('tok-abc');
        await p1;
        const sock = api.getAdminWs();
        sock._open();
        expect(api.isAdminWsOpen()).toBe(true);

        const p2 = api.connectAdminWebSocket();
        await p2;

        expect(liveSockets.length).toBe(1);
        expect(BeatifyAuth.getAccessToken).toHaveBeenCalledTimes(1);
    });
});

describe('#1395 onclose identity: only null adminWs for the active socket', () => {
    it('a stale socket onclose does NOT null the fresh adminWs', async () => {
        const api = await loadApi();

        // Open socket A.
        const pA = api.connectAdminWebSocket();
        resolveToken('tok-A');
        await pA;
        const socketA = api.getAdminWs();
        socketA._open();
        expect(api.isAdminWsOpen()).toBe(true);

        // Simulate a recovery/reconnect that replaces the active socket:
        // close A out-of-band (mirroring `var deadWs = adminWs; adminWs = null;`)
        // then connect a fresh socket B.
        socketA.close();
        const pB = api.connectAdminWebSocket();
        resolveToken('tok-B');
        await pB;
        const socketB = api.getAdminWs();
        socketB._open();

        expect(socketB).not.toBe(socketA);
        expect(api.isAdminWsOpen()).toBe(true);

        // NOW the dead socket A's deferred onclose finally fires. Before the
        // fix this nulled adminWs (which points at the healthy B) — the bug.
        socketA._fireClose();

        // adminWs must STILL be B; the connection must STILL report open.
        expect(api.getAdminWs()).toBe(socketB);
        expect(api.isAdminWsOpen()).toBe(true);
    });

    it('the active socket onclose DOES null adminWs (normal disconnect)', async () => {
        const api = await loadApi();

        const pA = api.connectAdminWebSocket();
        resolveToken('tok-A');
        await pA;
        const socketA = api.getAdminWs();
        socketA._open();
        expect(api.isAdminWsOpen()).toBe(true);

        // Active socket closes for real.
        socketA._fireClose();

        expect(api.getAdminWs()).toBe(null);
        expect(api.isAdminWsOpen()).toBe(false);
    });
});
