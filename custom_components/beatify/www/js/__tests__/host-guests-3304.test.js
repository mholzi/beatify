/**
 * #3304 — the host on a phone can sit a guest out and bring one back.
 *
 * #2746 built both actions, but the controls lived on the admin page only. A
 * host running the party from their phone had no way to stop a round waiting on
 * a phone nobody holds. The design gate picked variant B: a "Guests" row in the
 * host drawer, behind it a full-height screen grouped as not connected / in the
 * game / sitting out, and a bottom-sheet confirm before anyone is sat out.
 *
 * What is guarded here, each with its refusal:
 *   - the row exists for the host and for nobody else,
 *   - the groups put each player where the host has to act on them,
 *   - kick_player goes out only after the confirm — cancel sends nothing,
 *   - reinstate_player goes out on one tap,
 *   - the host's own row carries no control.
 *
 * The DOM is a hand-rolled stub (the repo carries no jsdom); the strings are
 * the shipped German, read through the same lookup BeatifyI18n.t performs.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { translator } from './helpers/mini-dom.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WWW = join(__dirname, '..', '..');
const locale = (code) => JSON.parse(readFileSync(join(WWW, 'i18n', `${code}.json`), 'utf8'));
const PLAYER_GAME = readFileSync(join(WWW, 'js', 'player-game.js'), 'utf8');

// ---- a DOM just big enough for the module ---------------------------------

function fakeEl(tag) {
    const classes = new Set();
    const listeners = {};
    const node = {
        tagName: String(tag || 'div').toUpperCase(),
        id: '',
        type: '',
        className: '',
        innerHTML: '',
        attrs: {},
        appended: [],
        removed: false,
        listeners,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c) || String(node.className).split(/\s+/).includes(c),
            toggle: (c, f) => ((f === undefined ? !classes.has(c) : f) ? classes.add(c) : classes.delete(c)),
        },
        setAttribute: (k, v) => { node.attrs[k] = String(v); },
        getAttribute: (k) => (k in node.attrs ? node.attrs[k] : null),
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        appendChild: (child) => {
            node.appended.push(child);
            if (child.id) registry[child.id] = child;
            return child;
        },
        remove: () => { node.removed = true; delete registry[node.id]; },
        querySelector: () => null,
        querySelectorAll: () => [],
    };
    return node;
}

let registry = {};
function isHidden(node) {
    return node.classList.contains('hidden');
}

/** Fire a click whose target sits inside an element carrying `attrs`. */
function clickOn(container, attrs) {
    const hit = {
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
    };
    const target = {
        closest: (sel) => {
            const m = /^\[([\w-]+)\]$/.exec(sel);
            return m && m[1] in attrs ? hit : null;
        },
    };
    (container.listeners.click || []).forEach((fn) => fn({ target }));
}

function setupDom() {
    registry = {};
    const body = fakeEl('body');
    const drawerBody = fakeEl('div');
    drawerBody.id = 'host-drawer-body';
    registry['host-drawer-body'] = drawerBody;
    global.document = {
        body,
        activeElement: null,
        getElementById: (id) => registry[id] || null,
        createElement: (tag) => fakeEl(tag),
        addEventListener: () => {},
        removeEventListener: () => {},
        querySelector: () => null,
    };
    return { body, drawerBody };
}

// ---- globals the player modules read at import time ------------------------
global.window = global.window || {};
global.window.location = global.window.location || { search: '', href: 'http://localhost/beatify/player' };
global.window.matchMedia = global.window.matchMedia || (() => ({ matches: true, addEventListener: () => {} }));
global.window.BeatifyUtils = translator(locale('de'));
global.URLSearchParams = global.URLSearchParams || URLSearchParams;
global.IntersectionObserver = global.IntersectionObserver || class { observe() {} disconnect() {} };
global.WebSocket = global.WebSocket || { OPEN: 1 };
setupDom();

const { state } = await import('../player-utils.js');
const guests = await import('../player-game/host-guests.js');

// ---- the room of the design draft -----------------------------------------
const P = (name, extra = {}) => ({
    name, score: 0, connected: true, is_admin: false,
    eliminated: false, sat_out_by_host: false, rejoin_requested: false, ...extra,
});
const ROOM = () => ({
    phase: 'PLAYING',
    sudden_death_mode: false,
    players: [
        P('Markus', { score: 980, is_admin: true }),
        P('Anna', { score: 1120 }),
        P('Jonas', { score: 410, connected: false }),
        P('Bea', { score: 870 }),
        P('Tom', { score: 620, sat_out_by_host: true }),
    ],
});

let sent;
beforeEach(() => {
    guests.hideHostGuests();
    setupDom();
    sent = [];
    state.isAdmin = true;
    state.ws = { readyState: 1, send: (s) => sent.push(JSON.parse(s)) };
});

describe('#3304 drawer row — host only', () => {
    it('the host gets a "Gäste" row with the count line', () => {
        const { drawerBody } = setupDom();
        guests.renderHostGuests(ROOM());
        const row = registry['host-drawer-guests'];
        expect(row, 'row must be appended to the drawer body').toBeTruthy();
        expect(drawerBody.appended).toContain(row);
        expect(row.innerHTML).toContain('Gäste');
        expect(row.innerHTML).toContain('1 nicht verbunden · 1 sitzt aus');
        expect(row.innerHTML).toContain('›');
    });

    it('a guest never sees the row', () => {
        const { drawerBody } = setupDom();
        state.isAdmin = false;
        guests.renderHostGuests(ROOM());
        expect(registry['host-drawer-guests']).toBeUndefined();
        expect(drawerBody.appended).toHaveLength(0);
    });

    it('a row left from host times is removed once the client is no longer host', () => {
        guests.renderHostGuests(ROOM());
        const row = registry['host-drawer-guests'];
        expect(row).toBeTruthy();
        state.isAdmin = false;
        guests.renderHostGuests(ROOM());
        expect(row.removed).toBe(true);
    });

    it('with nobody to act on, the line says how many are playing', () => {
        const data = ROOM();
        data.players = data.players.filter((p) => p.connected && !p.sat_out_by_host);
        guests.renderHostGuests(data);
        expect(registry['host-drawer-guests'].innerHTML).toContain('3 im Spiel');
    });

    it('player-game.js renders the row from the drawer and closes the screen with it', () => {
        const render = PLAYER_GAME.match(/export function renderHostDrawer\(data\)[\s\S]*?\n}/);
        expect(render[0]).toContain('renderHostGuests(data)');
        const hide = PLAYER_GAME.match(/export function hideHostDrawer\(\)[\s\S]*?\n}/);
        expect(hide[0]).toContain('hideHostGuests()');
    });
});

describe('#3304 guest groups', () => {
    it('groups not connected / in the game / sitting out, host first in the game', () => {
        const g = guests.guestGroups(ROOM().players);
        expect(g.away.map((e) => e.player.name)).toEqual(['Jonas']);
        expect(g.playing.map((e) => e.player.name)).toEqual(['Markus', 'Anna', 'Bea']);
        expect(g.satOut.map((e) => e.player.name)).toEqual(['Tom']);
        expect(g.away[0].action).toBe('sit-out');
        expect(g.satOut[0].action).toBe('reinstate');
    });

    it('the host row has no action', () => {
        const g = guests.guestGroups(ROOM().players);
        const host = g.playing.find((e) => e.player.name === 'Markus');
        expect(host.action).toBeNull();
    });

    it('a disconnected host is still not offered as removable', () => {
        const g = guests.guestGroups([P('Markus', { is_admin: true, connected: false })]);
        expect(g.away).toHaveLength(0);
        expect(g.playing[0].action).toBeNull();
    });

    it('a Sudden Death casualty is listed without a button', () => {
        const g = guests.guestGroups([P('Ede', { eliminated: true, connected: false })], { suddenDeathMode: true });
        expect(g.away).toHaveLength(0);
        expect(g.playing[0].action).toBeNull();
        expect(g.playing[0].eliminated).toBe(true);
    });

    it('no "Bring back" once Sudden Death has cut, or when the return is already parked', () => {
        const cut = guests.guestGroups(
            [P('Ede', { eliminated: true }), P('Tom', { sat_out_by_host: true })],
            { suddenDeathMode: true },
        );
        expect(cut.satOut[0].action).toBeNull();
        const parked = guests.guestGroups([P('Tom', { sat_out_by_host: true, rejoin_requested: true })]);
        expect(parked.satOut[0].action).toBeNull();
        expect(parked.satOut[0].pending).toBe(true);
    });

    it('the screen lists the sections in that order and gives the host row no control', () => {
        const html = guests.guestsScreenHtml(ROOM());
        const away = html.indexOf('Nicht verbunden · 1');
        const playing = html.indexOf('Im Spiel · 3');
        const out = html.indexOf('Sitzt aus · 1');
        expect(away).toBeGreaterThan(-1);
        expect(playing).toBeGreaterThan(away);
        expect(out).toBeGreaterThan(playing);
        expect(html).toContain('‹ Spielverlauf');

        const hostRow = html.split('<div class="host-guests__row').find((r) => r.includes('>Markus'));
        expect(hostRow).toBeTruthy();
        expect(hostRow).toContain('Gastgeber');
        expect(hostRow).not.toContain('data-guest-action');
        // visible button for the absent guest, quiet ⋮ for the ones in the game
        expect(html).toMatch(/host-guests__btn--warn" data-guest-action="sit-out" data-player="Jonas">Aussetzen/);
        expect(html).toMatch(/host-guests__more" data-guest-action="sit-out" data-player="Anna" aria-label="Anna aussetzen lassen">⋮/);
        expect(html).toMatch(/data-guest-action="reinstate" data-player="Tom">Zurückholen/);
    });
});

describe('#3304 actions', () => {
    function openScreen() {
        guests.renderHostGuests(ROOM());
        clickOn(registry['host-drawer-guests'], {});
        const screen = registry['host-guests'];
        expect(screen, 'tapping the row opens the guests screen').toBeTruthy();
        expect(isHidden(screen)).toBe(false);
        return screen;
    }

    it('sitting out sends kick_player only after the confirm', () => {
        const screen = openScreen();
        clickOn(screen, { 'data-guest-action': 'sit-out', 'data-player': 'Anna' });
        expect(sent).toEqual([]);

        const sheet = registry['host-guests-sheet'];
        expect(sheet).toBeTruthy();
        expect(isHidden(sheet)).toBe(false);
        expect(sheet.innerHTML).toContain('Diesen Gast aussetzen lassen?');
        expect(sheet.innerHTML).toContain(
            'Anna spielt dieses Spiel nicht weiter und belegt keinen Platz mehr. Die 1120 Punkte bleiben.');

        clickOn(sheet, { 'data-sheet-action': 'confirm' });
        expect(sent).toEqual([{ type: 'admin', action: 'kick_player', player_name: 'Anna' }]);
        expect(isHidden(sheet)).toBe(true);
    });

    it('cancel sends nothing, and a later confirm has nobody to send', () => {
        const screen = openScreen();
        clickOn(screen, { 'data-guest-action': 'sit-out', 'data-player': 'Jonas' });
        const sheet = registry['host-guests-sheet'];
        clickOn(sheet, { 'data-sheet-action': 'cancel' });
        expect(isHidden(sheet)).toBe(true);
        guests.confirmSitOut();
        expect(sent).toEqual([]);
    });

    it('reinstate sends reinstate_player on one tap', () => {
        const screen = openScreen();
        clickOn(screen, { 'data-guest-action': 'reinstate', 'data-player': 'Tom' });
        expect(sent).toEqual([{ type: 'admin', action: 'reinstate_player', player_name: 'Tom' }]);
        expect(registry['host-guests-sheet']).toBeUndefined();
    });

    it('a client that is not the host sends nothing', () => {
        state.isAdmin = false;
        guests.reinstateGuest('Tom');
        guests.requestSitOut('Anna');
        guests.confirmSitOut();
        expect(sent).toEqual([]);
    });

    it('the back link closes the screen', () => {
        const screen = openScreen();
        clickOn(screen, { 'data-guests-back': '1' });
        expect(isHidden(screen)).toBe(true);
        expect(guests.isGuestsScreenOpen()).toBe(false);
    });
});

describe('#3304 strings exist in every locale', () => {
    const KEYS = [
        'guestsRowTitle', 'guestsAway', 'guestsSatOut', 'guestsSatOutOne', 'guestsAllIn',
        'guestsSectionAway', 'guestsSectionPlaying', 'guestsSectionSatOut', 'guestsHost', 'guestsFooter',
    ];
    it.each(['en', 'de', 'es', 'fr', 'it', 'nl'])('%s', (code) => {
        const admin = locale(code).admin;
        KEYS.forEach((k) => {
            expect(typeof admin[k], `${code}: admin.${k}`).toBe('string');
            expect(admin[k].length).toBeGreaterThan(0);
        });
        ['guestsAway', 'guestsSatOut', 'guestsSatOutOne', 'guestsAllIn'].forEach((k) => {
            expect(admin[k], `${code}: admin.${k} needs {count}`).toContain('{count}');
        });
    });
});
