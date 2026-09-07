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
 * The design gate (05.09.2026) chose **variant C** over the greyed-tile-with-
 * a-× that was built first, so the assertions below moved with it:
 *
 * 1. `buildHomePlayerTiles` — the grid now answers ONE question, who is
 *    playing. An away guest is not a dimmed tile any more; they are not in the
 *    grid at all.
 * 2. `buildHomeAwayList` — the rows underneath, each carrying **the duration**.
 *    That is the point of the variant rather than trim: four minutes away is
 *    the bathroom, twelve minutes away is gone, and every other shape handed
 *    the host only "not currently connected". A row without its duration is
 *    variant A with extra steps, so it is pinned here.
 * 3. `formatAwayDuration` — reads a SERVER number (`away_seconds`). A
 *    browser-side timer would restart at every host reload and report "just
 *    now" for a guest who left before dinner.
 * 4. `confirmKickPlayer` — a tap opens the modal and sends NOTHING; only the
 *    confirm sends `kick_player`. The guard against a misplaced tap at a party
 *    dropping a player. Unchanged by the gate.
 * 5. `handleAdminWsMessage` — a rejected kick reaches the host as a message
 *    instead of dying in `console.warn`. Unchanged by the gate.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
    buildHomePlayerTiles,
    buildHomeAwayList,
    buildHomePlayerCount,
    formatAwayDuration,
} from '../admin/sections/render-helpers.js';
import { block, evaluate, readSource } from './helpers/js-source.js';
import { el, doc } from './helpers/mini-dom.js';

function realEscape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

const AWAY = { name: 'Kirsten', connected: false, is_admin: false, away_seconds: 240 };
const PRESENT = { name: 'Jonas', connected: true, is_admin: false };
const HOST = { name: 'Markus', connected: true, is_admin: true };

const I18N = {
    'lobby.away': 'away',
    'lobby.awayHeading': 'Away',
    'lobby.awayJustNow': 'just now',
    'lobby.awayMinutes': '{count} min',
    'lobby.awayHours': '{count} h',
    'admin.home.guestCount': '{count} guests',
    'admin.home.guestCountOne': '1 guest',
    'admin.home.guestsHere': '{count} here',
    'admin.kickPlayerAria': 'Remove {name} from the lobby',
    'admin.kickPlayerRemove': 'Remove',
};

// One tile's markup, sliced out of the concatenated grid by the player's name.
function tileFor(html, name) {
    return html
        .split(/(?=<div[^>]*class="home-player-tile)/)
        .filter(Boolean)
        .find((t) => t.includes('>' + name + '<'));
}

// One away row, sliced out of the list the same way.
function rowFor(html, name) {
    return html
        .split(/(?=<li class="home-away-row">)/)
        .filter(Boolean)
        .find((r) => r.includes('>' + name + '<'));
}

function installI18n() {
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: realEscape };
    globalThis.BeatifyI18n = {
        t: (k, params) => {
            let v = I18N[k];
            if (v === undefined) return k;
            if (params) Object.keys(params).forEach((pn) => { v = v.split('{' + pn + '}').join(params[pn]); });
            return v;
        },
    };
}
function removeI18n() {
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    delete globalThis.window;
}

describe('buildHomePlayerTiles — the grid is who is playing', () => {
    beforeEach(installI18n);
    afterEach(removeI18n);

    it('leaves an away guest out of the grid entirely (variant C)', () => {
        // Variant A dimmed the tile in place. C removes it, so nothing
        // removable ever borders something untouchable.
        const html = buildHomePlayerTiles([PRESENT, AWAY]);
        expect(html).toContain('Jonas');
        expect(html).not.toContain('Kirsten');
        expect(html).not.toContain('home-player-tile--away');
    });

    it('renders no buttons at all — the grid is display only', () => {
        const html = buildHomePlayerTiles([HOST, PRESENT, AWAY]);
        expect(html).not.toContain('<button');
        expect(html).not.toContain('home-player-tile--removable');
        expect(html).not.toContain('home-player-tile-remove');
    });

    it('keeps an away HOST in the grid, marked away and not removable', () => {
        // admin_kick_player refuses the admin, and the host's own phone must
        // not vanish from its own lobby. So the state shows, the action does not.
        const html = buildHomePlayerTiles([{ ...HOST, connected: false }]);
        expect(html).toContain('Markus');
        expect(html).toContain('home-player-tile--away');
        expect(html).toContain('>away<');
        expect(html).not.toContain('<button');
    });

    it('a payload with no `connected` field keeps everybody in the grid', () => {
        // REST polls and older servers omit it; `=== false` is the guard, so a
        // missing field must not empty the lobby.
        const html = buildHomePlayerTiles([{ name: 'Nina', is_admin: false }]);
        expect(html).toContain('Nina');
        expect(html).not.toContain('home-player-tile--away');
    });

    it('gives the remaining guests contiguous colours, with no gap where an away guest sat', () => {
        const html = buildHomePlayerTiles([HOST, PRESENT, AWAY, { name: 'Lena', connected: true }]);
        expect(html).toContain('home-player-tile--host');
        expect(html).toContain('👑');
        expect(tileFor(html, 'Jonas')).toContain('home-player-tile--c1');
        // Lena is the second RENDERED guest, so she takes c2 — the away guest
        // between them does not burn a colour slot.
        expect(tileFor(html, 'Lena')).toContain('home-player-tile--c2');
    });

    it('keeps the TOUR badge on a present guest still in the tour', () => {
        const html = buildHomePlayerTiles([{ name: 'Lena', connected: true, onboarded: false }]);
        expect(html).toContain('home-player-tile--learning');
        expect(html).toContain('TOUR');
    });
});

describe('buildHomeAwayList — the rows underneath, with the duration', () => {
    beforeEach(installI18n);
    afterEach(removeI18n);

    it('is empty when nobody is away, so the lobby looks untouched', () => {
        expect(buildHomeAwayList([HOST, PRESENT])).toBe('');
    });

    it('renders one row per away guest with initial, name and a quiet heading', () => {
        const html = buildHomeAwayList([PRESENT, AWAY]);
        expect(html).toContain('>Away<');
        expect(html).toContain('class="home-away-initial" aria-hidden="true">K<');
        expect(html).toContain('>Kirsten<');
        expect(html).not.toContain('Jonas');
    });

    it('shows HOW LONG they have been away — the whole reason variant C won', () => {
        // Without this the host is told only "not currently connected" and is
        // asked for a decision that cannot be made from it. 4 min is the
        // bathroom; 12 min is gone.
        const html = buildHomeAwayList([
            { name: 'Tim', connected: false, away_seconds: 240 },
            { name: 'Kira', connected: false, away_seconds: 745 },
        ]);
        expect(rowFor(html, 'Tim')).toContain('>4 min<');
        expect(rowFor(html, 'Kira')).toContain('>12 min<');
    });

    it('labels the button with a WORD, never a × glyph', () => {
        const html = buildHomeAwayList([AWAY]);
        expect(html).toContain('class="home-away-remove"');
        expect(html).toContain('>Remove</button>');
        expect(html).not.toContain('×');
    });

    it('carries the guest name on the button for the confirm card to name', () => {
        const html = buildHomeAwayList([AWAY]);
        expect(html).toContain('data-player="Kirsten"');
        expect(html).toContain('aria-label="Remove Kirsten from the lobby"');
    });

    it('never lists the host, even when the host is away', () => {
        expect(buildHomeAwayList([{ ...HOST, connected: false, away_seconds: 600 }])).toBe('');
    });

    it('omits the duration cell rather than invent one when the server sent none', () => {
        // An older server, or a record that predates the disconnect stamp. A
        // wrong duration is worse than a missing one — the host acts on it.
        const html = buildHomeAwayList([{ name: 'Tim', connected: false }]);
        expect(html).toContain('>Tim<');
        expect(html).not.toContain('home-away-since');
        expect(html).toContain('>Remove</button>');
    });

    it('escapes the name in the text, the data attribute and the label', () => {
        const html = buildHomeAwayList([{ name: '<img src=x>', connected: false, away_seconds: 90 }]);
        expect(html).not.toContain('<img src=x>');
        expect(html).toContain('&lt;img src=x&gt;');
        expect(html).toContain('data-player="&lt;img src=x&gt;"');
    });
});

describe('formatAwayDuration — a server number, rounded down', () => {
    beforeEach(installI18n);
    afterEach(removeI18n);

    it('says "just now" under a minute — there is no grace period, so this is the common first state', () => {
        expect(formatAwayDuration(0)).toBe('just now');
        expect(formatAwayDuration(59)).toBe('just now');
    });

    it('counts whole minutes, rounding down so "4 min" means at least four', () => {
        expect(formatAwayDuration(60)).toBe('1 min');
        expect(formatAwayDuration(299)).toBe('4 min');
        expect(formatAwayDuration(3599)).toBe('59 min');
    });

    it('switches to hours past sixty minutes', () => {
        expect(formatAwayDuration(3600)).toBe('1 h');
        expect(formatAwayDuration(7300)).toBe('2 h');
    });

    it('returns nothing for a missing or nonsensical value', () => {
        expect(formatAwayDuration(null)).toBe('');
        expect(formatAwayDuration(undefined)).toBe('');
        expect(formatAwayDuration(-5)).toBe('');
        expect(formatAwayDuration('12')).toBe('');
    });
});

describe('buildHomePlayerCount — total vs present', () => {
    beforeEach(installI18n);
    afterEach(removeI18n);

    it('stays silent while everybody is present — the grid IS the count', () => {
        expect(buildHomePlayerCount([HOST, PRESENT])).toBe('');
    });

    it('separates total from present once the grid stops showing everyone', () => {
        const html = buildHomePlayerCount([HOST, PRESENT, AWAY, { name: 'Kira', connected: false }]);
        expect(html).toContain('4 guests · 2 here');
    });

    it('uses the singular for a lobby of one', () => {
        expect(buildHomePlayerCount([{ name: 'Tim', connected: false }])).toContain('1 guest · 0 here');
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
