/**
 * #2648 — "now the 90s!" without throwing the room out.
 *
 * The end screen used to offer two doors: Rematch, which replayed the same
 * playlist, and New Game, which redirected the host to the admin page and told
 * every guest to scan the QR code again. Variant B of the design gate replaces
 * the menu with the choice itself.
 *
 * These tests drive the shipped modules rather than grepping their source, so
 * they are about behaviour:
 *
 *  1. **The request.** Picking the playlist that just played must still send
 *     the historic rematch — no `playlists` field. Only a real change puts one
 *     on the wire. That single decision is what keeps the swap from becoming a
 *     second lifecycle nobody tested.
 *  2. **The guest sentence.** This is the whole issue in one line. A guest who
 *     was never disconnected must never be told to scan anything, and must be
 *     told their name is safe — in their own language.
 *  3. **The grid.** Names arrive from JSON files a user may have written, so
 *     they go in as text, never as markup; and search has to find a playlist
 *     from a one-handed phone typo without accents.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const WWW = join(HERE, '..', '..');
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

const i18n = {};
for (const l of LOCALES) {
    i18n[l] = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
}
const lookup = (obj, key) =>
    key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);

// ---- the smallest DOM these renderers need --------------------------------
function makeNode(tag) {
    const classes = new Set();
    const node = {
        tagName: String(tag).toUpperCase(),
        textContent: '',
        type: '',
        disabled: false,
        onclick: null,
        children: [],
        attrs: {},
        set className(v) {
            classes.clear();
            String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
        },
        get className() { return [...classes].join(' '); },
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
            toggle: (c, force) => {
                const want = force === undefined ? !classes.has(c) : !!force;
                if (want) classes.add(c); else classes.delete(c);
                return want;
            },
        },
        setAttribute(k, v) { node.attrs[k] = String(v); },
        getAttribute(k) { return k in node.attrs ? node.attrs[k] : null; },
        appendChild(child) { node.children.push(child); return child; },
        focus() { node.focused = true; },
        set innerHTML(v) { if (!v) node.children.length = 0; node._html = v; },
        get innerHTML() { return node._html || ''; },
    };
    return node;
}

let locale = 'en';
const byId = {};
global.window = {
    BeatifyUtils: {
        t: (key, params) => {
            const value = lookup(i18n[locale], key);
            if (typeof value !== 'string') return key;
            if (!params || typeof params === 'string') return value;
            return Object.keys(params).reduce(
                (s, p) => s.replace(new RegExp(`\\{${p}\\}`, 'g'), params[p]),
                value,
            );
        },
    },
};
global.document = {
    getElementById: (id) => byId[id] || null,
    createElement: (tag) => makeNode(tag),
};

vi.mock('../player-utils.js', () => ({
    state: { playerName: null, ws: null },
    escapeHtml: (s) => String(s),
    showConfirmModal: () => {},
    AnimationQueue: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    showView: () => {},
}));
vi.mock('../notify.js', () => ({ showToast: () => {} }));

const picker = await import('../player-next-playlist.js');
const { renderGuestWaiting, hostNameOf } = await import('../player-end.js');

/** A payload shaped like `/beatify/api/next-playlists`. */
function payload(overrides = {}) {
    return Object.assign(
        {
            current: ['eighties.json'],
            suggested: [
                { paths: ['eighties.json'], name: '80s Hits', extra: 0, song_count: 120, reason: 'current' },
                { paths: ['nineties.json'], name: '90s Hits', extra: 0, song_count: 100, reason: 'recent' },
                { paths: ['disco.json'], name: 'Disco & Funk', extra: 0, song_count: 92, reason: 'recent' },
            ],
            all: [
                { path: 'eighties.json', name: '80s Hits', song_count: 120 },
                { path: 'nineties.json', name: '90s Hits', song_count: 100 },
                { path: 'disco.json', name: 'Disco & Funk', song_count: 92 },
                { path: 'roeyksopp.json', name: 'Röyksopp Deep Cuts', song_count: 40 },
                { path: 'kids.json', name: 'Songs for Kids', song_count: 55 },
            ],
        },
        overrides,
    );
}

beforeEach(() => {
    locale = 'en';
    for (const k of Object.keys(byId)) delete byId[k];
    picker.setPickerState(payload());
});

// ---------------------------------------------------------------------------
// 1. What goes on the wire
// ---------------------------------------------------------------------------

describe('#2648 the rematch request', () => {
    it('sends nothing extra when the host keeps the playlist that just played', () => {
        // setPickerState pre-selects the first tile, which is the current one.
        expect(picker.selectedPlaylists()).toBeNull();
    });

    it('names the new playlist once the host picks a different tile', () => {
        picker.pickerState().selected = ['nineties.json'];
        expect(picker.selectedPlaylists()).toEqual(['nineties.json']);
    });

    it('sends the whole selection back when the last game used several playlists', () => {
        picker.setPickerState(payload({
            current: ['eighties.json', 'disco.json'],
            suggested: [
                {
                    paths: ['eighties.json', 'disco.json'],
                    name: '80s Hits', extra: 1, song_count: 212, reason: 'current',
                },
                { paths: ['nineties.json'], name: '90s Hits', extra: 0, song_count: 100, reason: 'recent' },
            ],
        }));
        expect(picker.selectedPlaylists()).toBeNull();       // still "the same again"
        picker.pickerState().selected = ['nineties.json'];
        expect(picker.selectedPlaylists()).toEqual(['nineties.json']);
    });

    it('sends nothing when nothing could be loaded, so the button still replays', () => {
        picker.setPickerState({ current: [], suggested: [], all: [] });
        expect(picker.selectedPlaylists()).toBeNull();
    });

    it('keeps the pick when the end screen re-renders', async () => {
        // A guest closing their tab re-runs updateEndView. Before the load
        // guard that re-fetched and snapped `selected` back to the first tile,
        // so a host who had picked 90s Hits and was reaching for the button
        // would have started 80s Hits instead.
        byId['next-playlist-grid'] = makeNode('div');
        byId['player-rematch-btn'] = makeNode('button');
        picker.invalidateNextPlaylists();   // beforeEach installed a payload
        let fetches = 0;
        const fetchJson = async () => { fetches += 1; return payload(); };

        await picker.loadNextPlaylists(fetchJson);
        picker.pickerState().selected = ['nineties.json'];

        await picker.loadNextPlaylists(fetchJson);

        expect(fetches).toBe(1);
        expect(picker.selectedPlaylists()).toEqual(['nineties.json']);

        // A new game moves the history on, so the next podium fetches again.
        picker.invalidateNextPlaylists();
        await picker.loadNextPlaylists(fetchJson);
        expect(fetches).toBe(2);
        expect(picker.selectedPlaylists()).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// 2. The sentence the guest reads
// ---------------------------------------------------------------------------

describe('#2648 the guest is told to stay, not to rescan', () => {
    it('names the host and promises the name survives', () => {
        const box = makeNode('div');
        box.classList.add('hidden');
        renderGuestWaiting(box, 'Markus');

        const texts = box.children.map((c) => c.textContent);
        expect(texts[0]).toContain('Markus');
        expect(texts[1]).toBe(i18n.en.leaderboard.staysConnected);
        expect(box.classList.contains('hidden')).toBe(false);
    });

    it('never repeats the sentence the issue is about, in any locale', () => {
        for (const l of LOCALES) {
            locale = l;
            const box = makeNode('div');
            renderGuestWaiting(box, 'Ana');
            const joined = box.children.map((c) => c.textContent).join(' ');
            expect(joined, `${l}`).not.toContain('Scan the QR code');
            expect(joined, `${l}`).not.toBe('');
            expect(joined, `${l}`).not.toContain('{name}');
        }
    });

    it('renders each locale in its own words, not English', () => {
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            locale = l;
            const box = makeNode('div');
            renderGuestWaiting(box, 'Ana');
            expect(box.children[1].textContent, `${l}: keep-line`)
                .toBe(i18n[l].leaderboard.staysConnected);
            expect(box.children[1].textContent, `${l}: keep-line translated`)
                .not.toBe(i18n.en.leaderboard.staysConnected);
        }
    });

    it('falls back to a nameless sentence when the host runs the game from the admin page', () => {
        const box = makeNode('div');
        renderGuestWaiting(box, '');
        expect(box.children[0].textContent).toBe(i18n.en.leaderboard.hostPickingNoName);
    });

    it('finds the host in the leaderboard, and admits when there is none', () => {
        expect(hostNameOf([
            { name: 'Ana', is_admin: false },
            { name: 'Markus', is_admin: true },
        ])).toBe('Markus');
        expect(hostNameOf([{ name: 'Ana', is_admin: false }])).toBe('');
        expect(hostNameOf(null)).toBe('');
    });

    it('does nothing when the block is absent', () => {
        expect(() => renderGuestWaiting(null, 'Markus')).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// 3. The grid and the search
// ---------------------------------------------------------------------------

describe('#2648 the tile grid', () => {
    it('marks the playlist just played and always ends with a way into the catalogue', () => {
        const grid = makeNode('div');
        picker.renderTiles(grid, picker.pickerState().tiles, ['eighties.json'], () => {});

        expect(grid.children).toHaveLength(4);            // three tiles + search
        expect(grid.children[0].classList.contains('is-selected')).toBe(true);
        expect(grid.children[0].getAttribute('aria-pressed')).toBe('true');
        expect(grid.children[0].children[1].textContent).toBe(i18n.en.leaderboard.nextJustPlayed);
        expect(grid.children[1].children[1].textContent).toBe('100 songs');
        expect(grid.children[3].classList.contains('next-tile--search')).toBe(true);
        expect(grid.children[3].children[0].textContent).toBe('All 5');
    });

    it('puts a playlist name in as text, never as markup', () => {
        const grid = makeNode('div');
        const evil = [{ paths: ['x.json'], name: '<img src=x onerror=alert(1)>', extra: 0, song_count: 3, reason: 'recent' }];
        picker.renderTiles(grid, evil, [], () => {});
        expect(grid.children[0].children[0].textContent).toBe('<img src=x onerror=alert(1)>');
        expect(grid.innerHTML).toBe('');
    });

    it('says how many other playlists a multi-playlist tile carries', () => {
        const tile = { paths: ['a.json', 'b.json'], name: '80s Hits', extra: 1, song_count: 212, reason: 'current' };
        expect(picker.tileSubtitle(tile)).toBe('+1 more');
    });

    it('labels the primary button with the playlist it will start, per locale', () => {
        for (const l of LOCALES) {
            locale = l;
            const label = picker.goLabel({ paths: ['nineties.json'], name: '90s Hits' });
            expect(label, `${l}`).toContain('90s Hits');
            expect(label, `${l}`).not.toContain('{name}');
        }
    });
});

describe('#2648 searching the whole catalogue', () => {
    const all = picker.pickerState;

    it('puts a name that starts with the query above one that merely contains it', () => {
        const hits = picker.filterPlaylists(all().all, 'songs');
        expect(hits.map((h) => h.name)).toEqual(['Songs for Kids']);

        const disco = picker.filterPlaylists(all().all, 'disco');
        expect(disco.map((h) => h.name)).toEqual(['Disco & Funk']);
    });

    it('finds an accented name from an unaccented typing', () => {
        const hits = picker.filterPlaylists(all().all, 'roy');
        expect(hits.map((h) => h.name)).toEqual(['Röyksopp Deep Cuts']);
    });

    it('shows the head of the catalogue rather than a blank panel for an empty query', () => {
        expect(picker.filterPlaylists(all().all, '')).toHaveLength(5);
    });

    it('stops at the result limit so a phone does not render sixty rows', () => {
        const many = Array.from({ length: 80 }, (_, i) => ({ path: `p${i}.json`, name: `Party ${i}`, song_count: 10 }));
        expect(picker.filterPlaylists(many, 'party')).toHaveLength(picker.SEARCH_RESULT_LIMIT);
    });

    it('says so when nothing matches', () => {
        const results = makeNode('div');
        picker.renderResults(results, picker.filterPlaylists(all().all, 'zzzz'), [], () => {});
        expect(results.children[0].textContent).toBe(i18n.en.leaderboard.nextNoResults);
    });
});
