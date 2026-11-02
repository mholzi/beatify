/**
 * #3390 — the TV notices a silently dead connection.
 *
 * The phone has pinged since #967, the TV never did. A Wi-Fi drop without a
 * TCP reset left the TV's socket half open: no onclose, no badge, and the old
 * round shown as current (24 s+ seen live). Now:
 *
 *   - a ping every 15 s; 40 s without any frame from the server → dead,
 *   - the dead socket is cut loose and the loss path runs at once: dim, badge,
 *     countdown stopped, next attempt scheduled — forever, as before (#1398),
 *   - after 30 s without a connection the badge gets one line about the
 *     network; the next successful open takes it away.
 *
 * The factories run for real from utils.js; the dashboard wiring is compiled
 * out of dashboard.js (helpers/js-source.js) against stubs.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, readSource, locale, WWW_DIR } from './helpers/js-source.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); });

describe('createSocketHeartbeat (#3390)', () => {
    function make(overrides = {}) {
        const sent = [];
        const dead = vi.fn();
        let open = true;
        const hb = U.createSocketHeartbeat({
            isOpen: () => open,
            sendPing: () => sent.push('ping'),
            onDead: dead,
            ...overrides,
        });
        return { hb, sent, dead, setOpen: (v) => { open = v; } };
    }

    it('pings every 15 s while frames keep arriving', () => {
        const { hb, sent, dead } = make();
        hb.start();
        for (let i = 0; i < 6; i++) {
            vi.advanceTimersByTime(15000);
            hb.activity();  // the server's pong
        }
        expect(sent).toHaveLength(6);
        expect(dead).not.toHaveBeenCalled();
    });

    it('declares a silent socket dead after 40 s, once', () => {
        const { hb, sent, dead } = make();
        hb.start();
        vi.advanceTimersByTime(45000);  // ticks at 15 s and 30 s ping, 45 s sees 45 s of silence
        expect(sent).toHaveLength(2);
        expect(dead).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(120000);
        expect(dead).toHaveBeenCalledTimes(1);
    });

    it('stop() ends the pings', () => {
        const { hb, sent } = make();
        hb.start();
        hb.stop();
        vi.advanceTimersByTime(60000);
        expect(sent).toHaveLength(0);
    });

    it('a ping that throws does not stop the watch', () => {
        const dead = vi.fn();
        const hb = U.createSocketHeartbeat({
            isOpen: () => true,
            sendPing: () => { throw new Error('socket gone'); },
            onDead: dead,
        });
        hb.start();
        vi.advanceTimersByTime(45000);
        expect(dead).toHaveBeenCalledTimes(1);
    });
});

describe('createDelayedNotice (#3390)', () => {
    it('shows only after the delay, counted from the FIRST loss', () => {
        const show = vi.fn();
        const hide = vi.fn();
        const n = U.createDelayedNotice({ delay: 30000, show, hide });
        n.lost();
        vi.advanceTimersByTime(10000);
        n.lost();  // a failed reconnect attempt must not restart the clock
        vi.advanceTimersByTime(19999);
        expect(show).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(show).toHaveBeenCalledTimes(1);
        expect(n.isShown()).toBe(true);
    });

    it('back() before the delay shows nothing; after it hides the line', () => {
        const show = vi.fn();
        const hide = vi.fn();
        const n = U.createDelayedNotice({ delay: 30000, show, hide });
        n.lost();
        vi.advanceTimersByTime(5000);
        n.back();
        vi.advanceTimersByTime(60000);
        expect(show).not.toHaveBeenCalled();
        expect(hide).not.toHaveBeenCalled();

        n.lost();
        vi.advanceTimersByTime(30000);
        n.back();
        expect(hide).toHaveBeenCalledTimes(1);
        expect(n.isShown()).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// The dashboard wiring
// ---------------------------------------------------------------------------

const DASHBOARD = readSource('dashboard.js');
const src = (name) => declaration(DASHBOARD, name, 'dashboard.js');

function makeTv() {
    const calls = [];
    const note = (fn) => (...args) => calls.push(fn + (args.length ? ':' + args.join(',') : ''));
    const notice = U.createDelayedNotice({
        delay: 30000,
        show: note('noticeShown'),
        hide: note('noticeHidden'),
    });
    const scope = {
        ws: null,
        reconnectAttempts: 0,
        debug: () => {},
        _heartbeat: { stop: note('heartbeatStop') },
        _setDisconnectedDim: note('dim'),
        stopCountdown: note('stopCountdown'),
        _scheduleRender: { reset: note('renderReset') },
        _motionGate: { reset: note('motionReset') },
        _lastScenePhase: 'PLAYING',
        _showReconnectIndicator: note('badge'),
        _lostNotice: notice,
        getReconnectDelay: () => 1000,
        reconnectGuard: { schedule: (fn, d) => calls.push('schedule:' + d) },
        connectWebSocket: () => {},
    };
    const api = evaluate(
        [src('_handleSocketLost'), src('_dropDeadSocket')],
        '{ lost: _handleSocketLost, drop: _dropDeadSocket, setWs: (s) => { ws = s; } }',
        scope,
    );
    return { api, calls, notice };
}

describe('dashboard loss path (#3390)', () => {
    it('dims, shows the badge, STOPS the countdown and schedules the next attempt', () => {
        const tv = makeTv();
        tv.api.lost();
        expect(tv.calls).toEqual(expect.arrayContaining([
            'heartbeatStop', 'dim:true', 'stopCountdown', 'renderReset', 'badge', 'schedule:1000',
        ]));
    });

    it('a heartbeat timeout cuts the half-open socket loose and runs the loss path at once', () => {
        const tv = makeTv();
        const socket = { onopen: 1, onmessage: 1, onclose: 1, onerror: 1, close: vi.fn() };
        tv.api.setWs(socket);
        tv.api.drop();
        expect(socket.close).toHaveBeenCalled();
        // Its late onclose cannot run the loss path a second time.
        expect(socket.onclose).toBeNull();
        expect(socket.onmessage).toBeNull();
        expect(tv.calls.filter((c) => c === 'schedule:1000')).toHaveLength(1);
        expect(tv.calls).toContain('badge');
    });

    it('after 30 s of failed attempts the network line appears, and only once', () => {
        const tv = makeTv();
        tv.api.lost();
        vi.advanceTimersByTime(15000);
        tv.api.lost();
        vi.advanceTimersByTime(15000);
        expect(tv.calls.filter((c) => c === 'noticeShown')).toHaveLength(1);
        tv.notice.back();  // what onopen does
        expect(tv.calls).toContain('noticeHidden');
    });
});

describe('dashboard markup + copy (#3390)', () => {
    const html = readFileSync(join(WWW_DIR, 'dashboard.html'), 'utf8');

    it('the badge carries the network line, hidden until needed', () => {
        expect(html).toMatch(/id="dashboard-reconnect-notice" class="dashboard-reconnect-notice hidden" data-i18n="dashboard\.reconnectNotice"/);
    });

    it('the line adds no motion: no animation or transition on it', () => {
        const rule = html.match(/\.dashboard-reconnect-notice \{[^}]*\}/);
        expect(rule).not.toBeNull();
        expect(rule[0]).not.toMatch(/animation|transition/);
    });

    it('onopen restarts the heartbeat and drops the line', () => {
        const open = DASHBOARD.slice(DASHBOARD.indexOf('ws.onopen = function()'));
        const body = open.slice(0, open.indexOf('};'));
        expect(body).toContain('_lostNotice.back()');
        expect(body).toContain('_heartbeat.start()');
    });

    it.each(['en', 'de', 'es', 'fr', 'it', 'nl'])('%s has dashboard.reconnectNotice', (lang) => {
        const text = locale(lang).dashboard.reconnectNotice;
        expect(typeof text).toBe('string');
        expect(text).toContain('Home Assistant');
    });
});
