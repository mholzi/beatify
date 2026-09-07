/**
 * #2645 — the host's pause, and the announcement that goes with it.
 *
 * The scene the issue describes is the pizza arriving in round 7. What the
 * host had was Stop, which takes the music away and lets the clock keep
 * scoring everyone as "missed" — a button that does something other than what
 * its name says is a trap, not a gap, and a pause standing next to it would
 * not have removed the trap.
 *
 * So the shape here is an announcement: the tap pauses immediately, and the
 * reasons are offered afterwards as tiles — with the old Stop as the fourth
 * one, each carrying its consequence in a whole sentence. Three things then
 * decide whether that works, and all three are checked below:
 *
 *  1. **The tile list.** Which tiles exist, which one is lit, and — the one
 *     that is easy to get wrong — that the "Just the music off" swap is only
 *     offered when there is a round left to run on. Out of a pause taken in
 *     the reveal, "the clock keeps running" is a promise about a stopped
 *     clock.
 *  2. **The announcement itself.** A named reason becomes the headline; a bare
 *     Pause says "Pause"; a pause the *server* set is left alone, because
 *     "Pizza is here" over a dead speaker sends the room to wait for a host
 *     who is waiting for a speaker.
 *  3. **The two copies of the reason list agree.** `dashboard.js` is a
 *     standalone IIFE and cannot import `host-pause.js`, so the TV carries its
 *     own copy. A reason added on one side only renders on the wall, in poster
 *     size, as `host_pause_food`.
 *
 * The server half is `tests/unit/test_host_pause_2645.py`.
 */
import { beforeEach, describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { doc, el } from './helpers/mini-dom.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BEATIFY = join(__dirname, '..', '..', '..');

const PLAYER_HTML = readFileSync(join(BEATIFY, 'www', 'player.html'), 'utf8');
const ADMIN_HTML = readFileSync(join(BEATIFY, 'www', 'admin.html'), 'utf8');
const DASHBOARD_HTML = readFileSync(join(BEATIFY, 'www', 'dashboard.html'), 'utf8');
const DASHBOARD_JS = readFileSync(join(BEATIFY, 'www', 'js', 'dashboard.js'), 'utf8');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const locale = (code) =>
    JSON.parse(readFileSync(join(BEATIFY, 'www', 'i18n', `${code}.json`), 'utf8'));

// The page modules reach for browser globals at module scope, so the node env
// needs them stubbed BEFORE the import — same approach as
// host-drawer-sudden-death-2723.test.js.
global.window = global.window || {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { search: '', href: 'http://localhost/beatify/player' },
};
global.URLSearchParams = global.URLSearchParams || URLSearchParams;
global.document = global.document || {
    getElementById: () => null,
    querySelector: () => null,
    createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} } }),
};
global.IntersectionObserver = global.IntersectionObserver || class {
    observe() {}
    disconnect() {}
};

const {
    HOST_PAUSE_GENERIC, HOST_PAUSE_TILES, HOST_PAUSE_CODES,
    isHostPause, hostPauseAnnouncement,
} = await import('../host-pause.js');
const {
    pauseReasonTileModel, PAUSE_TILE_MUSIC_OFF,
    renderHostDrawer, renderPausedAdminActions,
} = await import('../player-game.js');
const { state } = await import('../player-utils.js');

/** The translator the renderers pass in: returns the key, like BeatifyI18n. */
const t = (key) => key;

const codesOf = (tiles) => tiles.map((tile) => tile.code);

describe('#2645 the tile list — what the host is offered, and when', () => {
    it('offers nothing at all for a pause the server set', () => {
        // A speaker failure is not a mislabelled Pause. Handing the host an
        // announcement list there invites them to write "Pizza is here" over
        // an outage, and the room would settle in to wait.
        expect(pauseReasonTileModel({
            pause_reason: 'media_player_error',
            paused_from: 'PLAYING',
        })).toEqual([]);
        expect(pauseReasonTileModel({ pause_reason: 'admin_disconnected' })).toEqual([]);
        expect(pauseReasonTileModel({})).toEqual([]);
        expect(pauseReasonTileModel(null)).toEqual([]);
    });

    it('offers the three announcements for a host pause', () => {
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'REVEAL',
        });
        expect(codesOf(tiles)).toEqual(codesOf(HOST_PAUSE_TILES));
    });

    it('adds the old Stop as a fourth tile while a round is still running', () => {
        // This is the whole variant: Pause and "just the music off" in one
        // list, each with its consequence, at the moment of choosing.
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'PLAYING',
        });
        expect(tiles).toHaveLength(HOST_PAUSE_TILES.length + 1);
        expect(tiles[tiles.length - 1].code).toBe(PAUSE_TILE_MUSIC_OFF);
    });

    it('withholds that fourth tile when the pause interrupted the reveal', () => {
        // "The clock keeps running" would be a promise about a clock that has
        // already stopped — the tile would read as a trap of its own.
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'REVEAL',
        });
        expect(codesOf(tiles)).not.toContain(PAUSE_TILE_MUSIC_OFF);
    });

    it('marks the fourth tile out, and only the fourth', () => {
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'PLAYING',
        });
        expect(tiles.filter((tile) => tile.warn).map((tile) => tile.code))
            .toEqual([PAUSE_TILE_MUSIC_OFF]);
    });

    it('lights exactly the announcement that is currently standing', () => {
        const tiles = pauseReasonTileModel({
            pause_reason: 'host_pause_door',
            paused_from: 'PLAYING',
        });
        expect(tiles.filter((tile) => tile.active).map((tile) => tile.code))
            .toEqual(['host_pause_door']);
    });

    it('lights nothing while the pause is still unnamed', () => {
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'PLAYING',
        });
        expect(tiles.some((tile) => tile.active)).toBe(false);
    });

    it('gives the three announcements the SAME consequence sentence', () => {
        // That sentence is what separates them from Stop. If one of them ever
        // says something else, the list stops being a comparison.
        const tiles = pauseReasonTileModel({ pause_reason: HOST_PAUSE_GENERIC });
        const subs = new Set(tiles.map((tile) => tile.subKey));
        expect(subs.size).toBe(1);
    });

    it('gives the fourth tile a DIFFERENT one', () => {
        const tiles = pauseReasonTileModel({
            pause_reason: HOST_PAUSE_GENERIC,
            paused_from: 'PLAYING',
        });
        const pause = tiles[0];
        const stop = tiles[tiles.length - 1];
        expect(stop.subKey).not.toBe(pause.subKey);
    });
});

describe('#2645 the announcement — reason large, state small', () => {
    it('makes a named reason the headline', () => {
        const a = hostPauseAnnouncement('host_pause_food', t);
        expect(a.named).toBe(true);
        expect(a.headline).toBe('game.pauseReasonFood');
        expect(a.emoji).toBeTruthy();
    });

    it('still announces a pause nobody named', () => {
        // "Wer die Tür aufmacht, ohne einen Grund zu wählen, hat trotzdem
        // pausiert" — the screens then simply say Pause.
        const a = hostPauseAnnouncement(HOST_PAUSE_GENERIC, t);
        expect(a).not.toBeNull();
        expect(a.named).toBe(false);
        expect(a.headline).toBe('game.paused');
    });

    it('leaves a pause the server set alone', () => {
        expect(hostPauseAnnouncement('media_player_error', t)).toBeNull();
        expect(hostPauseAnnouncement('no_songs_available', t)).toBeNull();
        expect(hostPauseAnnouncement('admin_disconnected', t)).toBeNull();
        expect(hostPauseAnnouncement(undefined, t)).toBeNull();
    });

    it('gives every announcement its own emoji', () => {
        const emojis = HOST_PAUSE_TILES.map((tile) => tile.emoji);
        expect(new Set(emojis).size).toBe(emojis.length);
    });

    it('agrees with isHostPause on both sides of the line', () => {
        for (const code of HOST_PAUSE_CODES) expect(isHostPause(code)).toBe(true);
        for (const code of ['media_player_error', 'admin_disconnected', '', undefined]) {
            expect(isHostPause(code)).toBe(false);
        }
    });
});

describe('#2645 the TV keeps a second copy of the list', () => {
    it('carries exactly the reason codes host-pause.js does', () => {
        // dashboard.js is minified standalone, not part of either ESM bundle,
        // so it cannot import the module. This is the seam that would rot.
        const found = new Set(DASHBOARD_JS.match(/'host_pause[a-z_]*'/g) || []);
        const codes = new Set(HOST_PAUSE_CODES.map((c) => `'${c}'`));
        expect(found).toEqual(codes);
    });

    it('resolves the same i18n key for every named reason', () => {
        for (const tile of HOST_PAUSE_TILES) {
            expect(DASHBOARD_JS).toContain(`'${tile.titleKey}'`);
        }
    });

    it('has somewhere to put the reason and the state', () => {
        expect(DASHBOARD_HTML).toContain('id="dashboard-pause-title"');
        expect(DASHBOARD_HTML).toContain('id="dashboard-pause-state"');
        expect(DASHBOARD_HTML).toContain('id="dashboard-pause-icon"');
    });

    it('does not let a translation pass overwrite the announcement', () => {
        // The headline is generated prose. A leftover data-i18n on it means
        // initPageTranslations puts "Game Paused" back over "Pizza is here".
        const title = DASHBOARD_HTML.match(/<h1 id="dashboard-pause-title"[^>]*>/);
        expect(title).not.toBeNull();
        expect(title[0]).not.toContain('data-i18n');
    });
});

describe('#2645 the surfaces the host taps', () => {
    it('gives the phone its pause on the drawer, not a seventh bar button', () => {
        // The control bar already carried six elements on 270 px — that is why
        // #2723 built the drawer in the first place.
        expect(PLAYER_HTML).not.toContain('id="pause-game-btn"');
        expect(PLAYER_HTML).toContain('id="host-drawer-body"');
    });

    it('still ships the drawer body EMPTY — the rows are rendered (#2723)', () => {
        const body = PLAYER_HTML.match(
            /<div id="host-drawer-body"[^>]*>([\s\S]*?)<\/div>/
        );
        expect(body).not.toBeNull();
        expect(body[1].trim()).toBe('');
    });

    it('gives the phone an empty announcement block to render into', () => {
        expect(PLAYER_HTML).toContain('id="paused-announce-block"');
        const list = PLAYER_HTML.match(
            /<div id="paused-reason-tiles"[^>]*>([\s\S]*?)<\/div>/
        );
        expect(list).not.toBeNull();
        expect(list[1].trim()).toBe('');
    });

    it('does not let a translation pass overwrite the phone headline either', () => {
        const title = PLAYER_HTML.match(/<h1 id="paused-title"[^>]*>/);
        expect(title).not.toBeNull();
        expect(title[0]).not.toContain('data-i18n');
    });

    it('puts Pause to the LEFT of Stop on the admin bar', () => {
        // Stop was the leftmost control and reads like the way to halt a game
        // while doing something else entirely. The button a host grabs first
        // should be the one that does what they mean.
        const bar = ADMIN_HTML.split('id="admin-control-bar"', 2)[1]
            .split('</div>\n\n', 1)[0];
        expect(bar.indexOf('id="admin-pause-game"')).toBeGreaterThan(-1);
        expect(bar.indexOf('id="admin-pause-game"'))
            .toBeLessThan(bar.indexOf('id="admin-stop-song"'));
    });

    it('gives the admin page the same announcement panel, empty', () => {
        expect(ADMIN_HTML).toContain('id="admin-host-pause"');
        const list = ADMIN_HTML.match(
            /<div id="admin-pause-reason-tiles"[^>]*>([\s\S]*?)<\/div>/
        );
        expect(list).not.toBeNull();
        expect(list[1].trim()).toBe('');
    });
});

// ---------------------------------------------------------------------------
// The phone, driven through its renderers rather than read as source text
// ---------------------------------------------------------------------------

/** A mini-dom element that can also hold listeners and a dataset. */
function node(id) {
    const n = el(id);
    n.dataset = {};
    n.listeners = {};
    n.addEventListener = (type, fn) => { (n.listeners[type] = n.listeners[type] || []).push(fn); };
    n.fire = (type, ev) => (n.listeners[type] || []).forEach((fn) => fn(ev));
    return n;
}

function page(ids) {
    const map = {};
    for (const id of ids) map[id] = node(id);
    const d = doc(map, {
        createElement: (created) => {
            created.dataset = {};
            created.listeners = {};
            created.addEventListener = (type, fn) => {
                (created.listeners[type] = created.listeners[type] || []).push(fn);
            };
            created.fire = (type, ev) =>
                (created.listeners[type] || []).forEach((fn) => fn(ev));
        },
    });
    return d;
}

/** A click event whose `closest('.pause-reason')` resolves to a tile. */
function tileClick(code) {
    const btn = { getAttribute: (k) => (k === 'data-code' ? code : null) };
    return { target: { closest: (sel) => (sel === '.pause-reason' ? btn : null) } };
}

function sentMessages() {
    return state.ws.sent.map((raw) => JSON.parse(raw));
}

// `debounceAdminAction` is a 500 ms timestamp comparison at module scope, so a
// suite that fires several taps inside one millisecond would have all but the
// first swallowed. Hand it a clock that moves between tests instead.
let fakeNow = 1_000_000;
beforeEach(() => {
    fakeNow += 10_000;
    Date.now = () => fakeNow;
    global.WebSocket = { OPEN: 1 };
    state.isAdmin = true;
    state.ws = {
        readyState: 1,
        sent: [],
        send(raw) { this.sent.push(raw); },
    };
});

describe('#2645 the host drawer carries the pause', () => {
    const IDS = [
        'host-drawer', 'host-drawer-body', 'host-drawer-grip',
    ];

    it('renders a pause row into the drawer body', () => {
        global.document = page(IDS);

        renderHostDrawer({ players: [] });

        const rows = global.document.elements['host-drawer-body'].appended;
        expect(rows.map((r) => r.id)).toContain('host-drawer-pause');
    });

    it('puts it FIRST, above Sudden Death', () => {
        // It is the row a host reaches for while carrying a pizza box; the
        // arming switch below it is not.
        global.document = page(IDS);

        renderHostDrawer({ players: [] });

        const rows = global.document.elements['host-drawer-body'].appended;
        expect(rows[0].id).toBe('host-drawer-pause');
    });

    it('says what the pause does, not just what it is called', () => {
        global.document = page(IDS);

        renderHostDrawer({ players: [] });

        const row = global.document.elements['host-drawer-body'].appended[0];
        expect(row.innerHTML).toContain('admin.pauseGame');
        expect(row.innerHTML).toContain('admin.pauseGameSub');
    });

    it('pauses on the tap — it does not open a reason picker first', () => {
        // A host with a doorbell going has one thing to do. Making them label
        // the pause before the music stops would be the second-worst pause
        // button available.
        global.document = page(IDS);
        renderHostDrawer({ players: [] });
        const row = global.document.elements['host-drawer-body'].appended[0];

        row.fire('click');

        expect(sentMessages()).toEqual([
            { type: 'admin', action: 'pause_game', reason: HOST_PAUSE_GENERIC },
        ]);
    });

    it('shows nothing to a guest', () => {
        state.isAdmin = false;
        global.document = page(IDS);

        renderHostDrawer({ players: [] });

        expect(global.document.elements['host-drawer-body'].appended).toEqual([]);
        expect(global.document.elements['host-drawer'].classes.has('hidden')).toBe(true);
    });
});

describe('#2645 the pause screen, as the host sees it', () => {
    const IDS = [
        'paused-admin-actions', 'paused-resume-btn', 'paused-end-btn',
        'paused-announce-block', 'paused-reason-tiles',
    ];

    function paused(data) {
        global.document = page(IDS);
        renderPausedAdminActions(data);
        return global.document.elements;
    }

    it('shows the announcement list for a pause the host set', () => {
        const els = paused({ pause_reason: HOST_PAUSE_GENERIC, paused_from: 'PLAYING' });
        expect(els['paused-announce-block'].classes.has('hidden')).toBe(false);
        expect(els['paused-reason-tiles'].innerHTML).toContain('host_pause_food');
    });

    it('hides it — and empties it — for a pause the server set', () => {
        const els = paused({ pause_reason: 'media_player_error', paused_from: 'PLAYING' });
        expect(els['paused-announce-block'].classes.has('hidden')).toBe(true);
        expect(els['paused-reason-tiles'].innerHTML).toBe('');
    });

    it('sends the chosen announcement without leaving the pause', () => {
        const els = paused({ pause_reason: HOST_PAUSE_GENERIC, paused_from: 'PLAYING' });

        els['paused-reason-tiles'].fire('click', tileClick('host_pause_food'));

        expect(sentMessages()).toEqual([
            { type: 'admin', action: 'pause_game', reason: 'host_pause_food' },
        ]);
    });

    it('sends a plain stop for the fourth tile, never another pause', () => {
        // The tile is the old Stop. If it sent `pause_game` it would be a
        // fourth pause reason wearing Stop's sentence — the exact confusion
        // this variant exists to end.
        const els = paused({ pause_reason: HOST_PAUSE_GENERIC, paused_from: 'PLAYING' });

        els['paused-reason-tiles'].fire('click', tileClick(PAUSE_TILE_MUSIC_OFF));

        expect(sentMessages()).toEqual([{ type: 'admin', action: 'stop_song' }]);
    });

    it('shows a guest no announcement list at all', () => {
        state.isAdmin = false;
        const els = paused({ pause_reason: HOST_PAUSE_GENERIC, paused_from: 'PLAYING' });
        expect(els['paused-admin-actions'].classes.has('hidden')).toBe(true);
        expect(els['paused-reason-tiles'].innerHTML).toBe('');
    });
});

describe('#2645 strings exist in every locale', () => {
    const GAME_KEYS = [
        'pauseReasonFood', 'pauseReasonDoor', 'pauseReasonAway', 'pauseReasonSub',
        'pauseMusicOff', 'pauseMusicOffSub', 'pausedLabel', 'pausedClockStopped',
        'pausedHintHost', 'pausedGuessesSaved',
    ];
    const ADMIN_KEYS = [
        'pauseGame', 'pauseGameSub', 'pauseAnnouncement', 'pauseOnEveryScreen', 'resume',
    ];

    it.each(LOCALES)('%s carries every new key as a string', (code) => {
        const d = locale(code);
        for (const k of GAME_KEYS) {
            expect(typeof d.game?.[k], `game.${k} in ${code}`).toBe('string');
            expect(d.game[k].length).toBeGreaterThan(0);
        }
        for (const k of ADMIN_KEYS) {
            expect(typeof d.admin?.[k], `admin.${k} in ${code}`).toBe('string');
            expect(d.admin[k].length).toBeGreaterThan(0);
        }
    });

    it.each(LOCALES)('%s resolves every reason title the tiles ask for', (code) => {
        const d = locale(code);
        for (const tile of HOST_PAUSE_TILES) {
            const leaf = tile.titleKey.split('.').reduce((n, p) => (n || {})[p], d);
            expect(typeof leaf, `${tile.titleKey} in ${code}`).toBe('string');
        }
    });

    it.each(LOCALES.filter((c) => c !== 'en'))(
        '%s actually translated the two sentences that carry the difference',
        (code) => {
            // These two are the whole defusing: one says the clock stopped, the
            // other says it did not. Five locales left in English would leave
            // the trap exactly where it was.
            const en = locale('en');
            expect(locale(code).game.pauseReasonSub).not.toBe(en.game.pauseReasonSub);
            expect(locale(code).game.pauseMusicOffSub).not.toBe(en.game.pauseMusicOffSub);
        }
    );

    it('never puts HTML inside a translated string', () => {
        for (const code of LOCALES) {
            const d = locale(code);
            for (const k of GAME_KEYS) expect(d.game[k]).not.toMatch(/<[a-z/]/i);
            for (const k of ADMIN_KEYS) expect(d.admin[k]).not.toMatch(/<[a-z/]/i);
        }
    });

    it('leaves the pauseRecovery subtree intact', () => {
        // admin.pauseRecovery is an OBJECT. A string written to a key one
        // character away from it would take the #805 banner's whole message
        // set with it, silently.
        for (const code of LOCALES) {
            expect(typeof locale(code).admin.pauseRecovery).toBe('object');
            expect(locale(code).admin.pauseRecovery.mediaPlayerError).toBeTruthy();
        }
    });
});
