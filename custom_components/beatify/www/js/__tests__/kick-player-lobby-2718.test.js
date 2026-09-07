/**
 * #2718 — the host can remove a guest who scanned, typed a name and left.
 *
 * The server half never went away: `kick_player` is registered in
 * `server/ws_handlers/admin.py` and has been since #659 (April). PR #1613
 * (26 June) deleted the flat lobby along with its kick button and
 * `handleKickPlayer()`, and the home-view tile grid that replaced it rendered
 * names and nothing else — no away state, no tap action. From then on a guest
 * who walked off held a slot against MAX_PLAYERS, and a survivor slot in
 * Sudden Death, with no way back short of ending the game.
 *
 * Three things are covered here, all of them the parts that can silently
 * regress again:
 *
 * 1. `buildHomePlayerTiles` — which tiles show "away" and which of them are
 *    tappable. The server refuses a connected player and refuses the admin, so
 *    a button on either could only ever fail; the boundary between <div> and
 *    <button> is the contract with `admin_kick_player`.
 * 2. `confirmKickPlayer` — a tap opens the modal and sends NOTHING; only the
 *    confirm sends `kick_player`. This is the guard against a misplaced tap at
 *    a party dropping a player.
 * 3. `handleAdminWsMessage` — a rejected kick reaches the host as a message
 *    instead of dying in `console.warn`, which is where every non-start
 *    command error used to land.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { buildHomePlayerTiles } from '../admin/sections/render-helpers.js';
import { block, evaluate, readSource } from './helpers/js-source.js';
import { el, doc } from './helpers/mini-dom.js';

function realEscape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

const AWAY = { name: 'Kirsten', connected: false, is_admin: false };
const PRESENT = { name: 'Jonas', connected: true, is_admin: false };
const HOST = { name: 'Markus', connected: true, is_admin: true };

// One tile's markup, sliced out of the concatenated grid by the guest's name.
// Tiles never nest, so splitting before each opening tag is enough.
function tileFor(html, name) {
    return html
        .split(/(?=<(?:div|button)[^>]*class="home-player-tile)/)
        .filter(Boolean)
        .find((t) => t.includes('>' + name + '<'));
}

describe('buildHomePlayerTiles — away state and the remove affordance', () => {
    beforeEach(() => {
        globalThis.window = globalThis;
        globalThis.BeatifyUtils = { escapeHtml: realEscape };
        globalThis.BeatifyI18n = {
            t: (k, params) => {
                const table = {
                    'lobby.away': 'away',
                    'admin.kickPlayerAria': 'Remove {name} from the lobby',
                };
                let v = table[k];
                if (v === undefined) return k;
                if (params) Object.keys(params).forEach((p) => { v = v.split('{' + p + '}').join(params[p]); });
                return v;
            },
        };
    });
    afterEach(() => {
        delete globalThis.BeatifyUtils;
        delete globalThis.BeatifyI18n;
        delete globalThis.window;
    });

    it('marks a disconnected guest away — the state only the TV used to show', () => {
        const html = buildHomePlayerTiles([AWAY]);
        expect(html).toContain('home-player-tile--away');
        expect(html).toContain('>away<');
    });

    it('leaves a connected guest plain: no away badge, no button', () => {
        const html = buildHomePlayerTiles([PRESENT]);
        expect(html).not.toContain('home-player-tile--away');
        expect(html).not.toContain('<button');
        expect(html).toContain('Jonas');
    });

    it('renders the away guest as a button carrying their name, the present one as a div', () => {
        const html = buildHomePlayerTiles([PRESENT, AWAY]);
        expect(tileFor(html, 'Kirsten').startsWith('<button')).toBe(true);
        expect(tileFor(html, 'Kirsten')).toContain('data-player="Kirsten"');
        expect(tileFor(html, 'Jonas').startsWith('<div')).toBe(true);
    });

    it('never offers to remove the host, even when the host is away', () => {
        const html = buildHomePlayerTiles([{ ...HOST, connected: false }]);
        // The host still reads as away — the info is useful — but the tile is
        // inert: admin_kick_player refuses the admin.
        expect(html).toContain('home-player-tile--away');
        expect(html).not.toContain('<button');
        expect(html).not.toContain('home-player-tile--removable');
    });

    it('a payload with no `connected` field paints nobody away', () => {
        // REST polls and older servers omit it; `=== false` is the guard.
        const html = buildHomePlayerTiles([{ name: 'Nina', is_admin: false }]);
        expect(html).not.toContain('home-player-tile--away');
        expect(html).not.toContain('<button');
    });

    it('gives the remove button a translated, name-carrying accessible label', () => {
        const html = buildHomePlayerTiles([AWAY]);
        expect(html).toContain('aria-label="Remove Kirsten from the lobby"');
    });

    it('escapes the name in both the text and the data attribute', () => {
        const html = buildHomePlayerTiles([{ name: '<img src=x>', connected: false }]);
        expect(html).not.toContain('<img src=x>');
        expect(html).toContain('&lt;img src=x&gt;');
        expect(html).toContain('data-player="&lt;img src=x&gt;"');
    });

    it('keeps the host crown, the guest colour cycle and the TOUR badge intact', () => {
        const html = buildHomePlayerTiles([
            HOST,
            PRESENT,
            { name: 'Lena', connected: true, onboarded: false },
            { ...AWAY, onboarded: false },
        ]);
        expect(html).toContain('home-player-tile--host');
        expect(html).toContain('👑');
        expect(html).toContain('home-player-tile--c1');
        expect(html).toContain('home-player-tile--c2');
        expect(html).toContain('home-player-tile--learning');
        expect(html).toContain('TOUR');
        // Away + still-learning is one tile with both states and a remove button.
        const kirsten = tileFor(html, 'Kirsten');
        expect(kirsten).toContain('home-player-tile--away');
        expect(kirsten).toContain('home-player-tile--learning');
        expect(kirsten.startsWith('<button')).toBe(true);
    });
});

// --- the confirm gate -------------------------------------------------------
// confirmKickPlayer lives in admin.js, which is a DOM-coupled entry module with
// no export for it; compile the declaration out of the shipped file and hand it
// the closure the browser would have (#2701 pattern).
const ADMIN_SRC = readSource('admin.js');
const CONFIRM_KICK = block(ADMIN_SRC, 'function confirmKickPlayer(playerName) {', 'admin.js');


// A tiny event-capable element — mini-dom's `el` has no listener support.
function clickable(id) {
    const node = el(id);
    node.listeners = {};
    node.addEventListener = (type, fn) => { (node.listeners[type] = node.listeners[type] || []).push(fn); };
    node.removeEventListener = (type, fn) => {
        node.listeners[type] = (node.listeners[type] || []).filter((f) => f !== fn);
    };
    node.click = () => (node.listeners.click || []).slice().forEach((fn) => fn());
    return node;
}

/**
 * Compile confirmKickPlayer ONCE per harness so the `_kickModalClose` binding
 * it closes over survives between opens — that binding is what stops a second
 * open from stacking a second pair of click listeners.
 */
function kickHarness({ withModal = true, wsOpen = true } = {}) {
    const sent = [];
    const errors = [];
    const confirmBtn = clickable('kick-player-confirm-btn');
    const cancelBtn = clickable('kick-player-cancel-btn');
    const backdrop = clickable(null);
    const modal = el('kick-player-modal', { children: { '.modal-backdrop': backdrop } });
    modal.classList.add('hidden');
    const message = el('kick-player-message');
    const elements = withModal
        ? {
            'kick-player-modal': modal,
            'kick-player-message': message,
            'kick-player-confirm-btn': confirmBtn,
            'kick-player-cancel-btn': cancelBtn,
        }
        : {};
    const scope = {
        document: doc(elements),
        window: { confirm: vi.fn(() => true) },
        tr: (key, fallback, params) => {
            let out = fallback;
            if (params) Object.keys(params).forEach((k) => { out = out.split('{' + k + '}').join(params[k]); });
            return out;
        },
        sendAdminWs: (payload) => { sent.push(payload); return wsOpen; },
        showError: (msg) => errors.push(msg),
        activateModalFocus: vi.fn(),
        deactivateModalFocus: vi.fn(),
        _kickModalClose: null,
    };
    const run = evaluate([CONFIRM_KICK], 'confirmKickPlayer', scope);
    return { run, sent, errors, modal, message, confirmBtn, cancelBtn, backdrop, scope };
}

describe('#2718 confirmKickPlayer — the confirm gate', () => {
    it('opening the modal sends nothing: a stray tap cannot drop a player', () => {
        const h = kickHarness();
        h.run('Kirsten');
        expect(h.modal.classList.contains('hidden')).toBe(false);
        expect(h.sent).toEqual([]);
    });

    it('names the guest in the confirmation text', () => {
        const h = kickHarness();
        h.run('Kirsten');
        expect(h.message.textContent).toBe('Remove Kirsten from the lobby?');
    });

    it('focuses Cancel, never the destructive button', () => {
        const h = kickHarness();
        h.run('Kirsten');
        expect(h.scope.activateModalFocus).toHaveBeenCalledWith('kick-player-modal', 'kick-player-cancel-btn');
    });

    it('confirming sends exactly the action the server registers', () => {
        const h = kickHarness();
        h.run('Kirsten');
        h.confirmBtn.click();
        expect(h.sent).toEqual([{ type: 'admin', action: 'kick_player', player_name: 'Kirsten' }]);
        expect(h.modal.classList.contains('hidden')).toBe(true);
    });

    it('cancelling sends nothing and closes', () => {
        const h = kickHarness();
        h.run('Kirsten');
        h.cancelBtn.click();
        expect(h.sent).toEqual([]);
        expect(h.modal.classList.contains('hidden')).toBe(true);
    });

    it('tapping the backdrop cancels', () => {
        const h = kickHarness();
        h.run('Kirsten');
        h.backdrop.click();
        expect(h.sent).toEqual([]);
        expect(h.modal.classList.contains('hidden')).toBe(true);
    });

    it('a second open does not stack listeners — one confirm, one kick', () => {
        const h = kickHarness();
        h.run('Kirsten');
        h.cancelBtn.click();
        h.run('Kirsten');
        h.confirmBtn.click();
        expect(h.sent).toHaveLength(1);
    });

    it('an empty name is a no-op — no modal, no send', () => {
        const h = kickHarness();
        h.run('');
        expect(h.modal.classList.contains('hidden')).toBe(true);
        expect(h.sent).toEqual([]);
    });

    it('says so when the socket is down instead of failing silently', () => {
        const h = kickHarness({ wsOpen: false });
        h.run('Kirsten');
        h.confirmBtn.click();
        expect(h.errors).toEqual(['Reconnecting to game server — please try again.']);
    });

    it('falls back to window.confirm when the modal markup is missing', () => {
        const h = kickHarness({ withModal: false });
        h.run('Kirsten');
        expect(h.scope.window.confirm).toHaveBeenCalledWith('Remove Kirsten from the lobby?');
        expect(h.sent).toHaveLength(1);
    });
});

// --- the rejection path -----------------------------------------------------
// The one rejection that realistically fires: the guest reconnected between the
// render that offered the tile and the host's tap, so the server answers
// "Cannot remove a connected player". Before #2718 that landed in the catch-all
// branch of the error dispatcher and was only console.warn'd — the host tapped
// Remove and nothing at all happened on screen.

class FakeWebSocket {
    constructor(url) {
        this.url = url;
        this.readyState = FakeWebSocket.CONNECTING;
        this.sent = [];
        FakeWebSocket.live.push(this);
    }
    send(data) { this.sent.push(data); }
    close() { this.readyState = FakeWebSocket.CLOSED; }
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSED = 3;

async function loadOpenApi() {
    vi.resetModules();
    FakeWebSocket.live = [];
    globalThis.WebSocket = FakeWebSocket;
    globalThis.window = { location: { protocol: 'https:', host: 'ha.local' } };
    globalThis.BeatifyAuth = {
        getAccessToken: vi.fn(async () => 'tok'),
        isCompanionBypassMode: vi.fn(() => false),
    };
    const api = await import('../admin/api.js?ts=' + Math.random());
    await api.connectAdminWebSocket();
    api.getAdminWs().readyState = FakeWebSocket.OPEN;
    return api;
}

describe('#2718 a rejected kick reaches the host', () => {
    afterEach(() => {
        delete globalThis.WebSocket;
        delete globalThis.window;
        delete globalThis.BeatifyAuth;
    });

    it('routes the rejection to the kick handler with the name that failed', async () => {
        const api = await loadOpenApi();
        const kicks = [];
        api.initAdminApi({ showKickError: (...args) => kicks.push(args) });

        expect(api.sendAdminWs({ type: 'admin', action: 'kick_player', player_name: 'Kirsten' })).toBe(true);
        api.handleAdminWsMessage({
            type: 'error',
            code: 'INVALID_ACTION',
            message: 'Cannot remove a connected player',
        });

        expect(kicks).toEqual([['Kirsten', 'INVALID_ACTION', 'Cannot remove a connected player']]);
    });

    it('a successful kick disarms on the state broadcast, so a later error is not blamed on it', async () => {
        const api = await loadOpenApi();
        const kicks = [];
        api.initAdminApi({
            showKickError: (name) => kicks.push(name),
            handleAdminStateUpdate: () => {},
        });

        api.sendAdminWs({ type: 'admin', action: 'kick_player', player_name: 'Kirsten' });
        // The server removes the player and broadcasts state — that is success.
        api.handleAdminWsMessage({ type: 'state', players: [] });
        // An unrelated command error afterwards must not pop a kick toast.
        api.handleAdminWsMessage({ type: 'error', code: 'INVALID_ACTION', message: 'volume' });

        expect(kicks).toEqual([]);
    });

    it('leaves an unrelated command error in the silent catch-all branch', async () => {
        const api = await loadOpenApi();
        const kicks = [];
        const errors = [];
        api.initAdminApi({ showKickError: (n) => kicks.push(n), showError: (m) => errors.push(m) });

        api.handleAdminWsMessage({ type: 'error', code: 'INVALID_ACTION', message: 'set_volume failed' });

        expect(kicks).toEqual([]);
        expect(errors).toEqual([]);
    });
});
