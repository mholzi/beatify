/**
 * Regression test for #1580 — "Silent sync break on malformed WS message".
 *
 * admin/api.js `ws.onmessage` used to wrap JSON.parse in a try/catch whose
 * only action was `console.error(...)`. When a malformed/unparseable frame
 * arrived (truncated payload, or a server/client version mismatch sending an
 * unreadable shape) the admin got ZERO feedback — state sync silently stalled.
 *
 * The fix: log a `console.warn` WITH raw payload context, surface a reload
 * hint via `deps.showError`, and SKIP the bad frame so the socket keeps
 * processing subsequent well-formed messages instead of breaking sync.
 *
 * Globals (WebSocket, BeatifyAuth, BeatifyI18n, window) are browser-supplied;
 * we stub them.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

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
    send(data) { this.sent.push(data); }
    close() { this.readyState = WS_CLOSED; }
    _open() {
        this.readyState = WS_OPEN;
        if (this.onopen) this.onopen();
    }
    // Deliver a raw frame exactly like the browser would.
    _message(raw) {
        if (this.onmessage) this.onmessage({ data: raw });
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
        getAccessToken: vi.fn(() => new Promise((res) => { resolveToken = res; })),
        isCompanionBypassMode: vi.fn(() => false),
    };
    // Untranslated → exercise the inline English fallback string.
    globalThis.BeatifyI18n = { t: vi.fn(() => null) };
}

async function loadApi() {
    vi.resetModules();
    return import('../admin/api.js?ts=' + Math.random());
}

let warnSpy;

beforeEach(() => {
    installGlobals();
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
    warnSpy.mockRestore();
});

async function connectOpenSocket(api) {
    const p = api.connectAdminWebSocket();
    resolveToken('tok-1580');
    await p;
    const sock = api.getAdminWs();
    sock._open();
    return sock;
}

describe('#1580 malformed WS message: warn + reload hint + keep syncing', () => {
    it('a malformed frame does not throw, warns with context, and shows a reload hint', async () => {
        const api = await loadApi();
        const showError = vi.fn();
        api.initAdminApi({ showError });

        const sock = await connectOpenSocket(api);

        // A truncated / non-JSON payload — must NOT throw out of onmessage.
        expect(() => sock._message('{"type":"state", "broke')).not.toThrow();

        // Logged a warning WITH the raw payload context (not a silent swallow).
        expect(warnSpy).toHaveBeenCalled();
        const warnArgs = warnSpy.mock.calls[0].join(' ');
        expect(warnArgs).toContain('malformed');
        expect(warnArgs).toContain('{"type":"state", "broke');

        // Surfaced a user-facing reload hint (fallback string, i18n untranslated).
        expect(showError).toHaveBeenCalledTimes(1);
        expect(showError.mock.calls[0][0]).toMatch(/reload/i);
    });

    it('keeps the socket alive so a later well-formed message still dispatches', async () => {
        const api = await loadApi();
        const showError = vi.fn();
        const stopLobbyPolling = vi.fn();
        api.initAdminApi({ showError, stopLobbyPolling });

        const sock = await connectOpenSocket(api);

        // Bad frame first — silently swallowed in the old code, sync stalled.
        sock._message('not json at all');
        expect(showError).toHaveBeenCalledTimes(1);

        // Then a valid frame: dispatch must still run (admin_connect_ack stops
        // the REST lobby polling). Proves the connection wasn't broken.
        sock._message(JSON.stringify({ type: 'admin_connect_ack', game_id: 'g1' }));
        expect(stopLobbyPolling).toHaveBeenCalledTimes(1);

        // The good frame did not raise another error hint.
        expect(showError).toHaveBeenCalledTimes(1);
    });
});
