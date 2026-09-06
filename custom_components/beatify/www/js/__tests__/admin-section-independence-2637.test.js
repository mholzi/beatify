/**
 * #2637 — the admin sections must not reach back into admin.js through `window`.
 *
 * `admin.js` used to publish 14 names on `window` and the extracted sections
 * called back through them. That is a load-order dependency with nothing
 * watching it: a section only worked because admin.js happened to have executed
 * first, and the moment the order changed (or a `.min.js` drifted, as in #1263)
 * the failure showed up at a party rather than in CI.
 *
 * What is asserted here is behaviour, not source text. Every test runs with a
 * `window` whose reads of an admin-core name THROW — so a re-introduced
 * `window.loadStatus?.()` fails loudly at the moment it is evaluated instead of
 * silently no-opping the way the real `typeof … === 'function'` guards did. Then
 * each section is loaded on its own, with admin.js never imported at all, and
 * driven through the controls it renders. If a section needs the core to have
 * run first, it cannot pass.
 *
 * The last block checks the page's script manifest against the bundle's real
 * module graph: no file may be both an input of admin.min.js and a separate
 * `<script>` in admin.html, because that is two copies of one module with an
 * ordering problem between them.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFile } from 'node:fs/promises';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, resolve } from 'node:path';
import { build } from 'esbuild';

const HERE = dirname(fileURLToPath(import.meta.url));
const JS_DIR = resolve(HERE, '..');
const WWW_DIR = resolve(JS_DIR, '..');
const REPO_ROOT = resolve(WWW_DIR, '..', '..', '..');

/**
 * Names that belong to the admin core (admin.js) or to what used to be a
 * classic script it handshook with.
 *
 * Six of these still exist on the page on purpose — wizard.js and
 * playlist-requests.js are separate top-level scripts that cannot import from
 * the admin bundle, so `window` is the only channel they have. That is a
 * boundary between two entry points, not a cycle. What must never come back is
 * a module UNDER admin/ reading one of them: those modules are inside the same
 * bundle and can import what they need.
 *
 * The eight that no longer exist are listed too, so re-adding one and quietly
 * depending on it also trips the sentinel.
 */
const ADMIN_CORE_GLOBALS = [
    // still published by admin.js, for wizard.js / playlist-requests.js only
    'loadStatus',
    'loadSavedSettings',
    'BeatifyHome',
    'BeatifyPersistSetup',
    'BeatifyNoteLocalSetupWrite',
    'BEATIFY_VERSION',
    // removed by #2637 — must not come back
    'escapeHtml',
    'groupPlayersByPlatform',
    'buildRequestRowHtml',
    '_getAdminToken',
    '_setAdminToken',
    '_adminHeaders',
    'clearPlaylistFilters',
    'loadPlaylists',
    '_ttsConfig',
    '_partyLightsConfig',
];

/**
 * A `window` that refuses to hand out an admin-core global.
 *
 * Reads and `in` checks both throw, which covers every shape the old code used:
 * `window.x()`, `window.x?.()`, `typeof window.x === 'function'` and
 * `'x' in window`. Writes are allowed — a section is free to publish something
 * of its own (mix.js exposes `window.BeatifyMixPanel` for the playlist hub).
 */
function sentinelWindow(base) {
    const refuse = (prop) => {
        throw new Error(
            `load-order violation: a module under admin/ read window.${prop}. ` +
            'That name is owned by the admin core, so reading it here means this ' +
            'module only works when admin.js has already run. Pass the dependency ' +
            'in (see initMixTab / initMediaPlayers) or import it.',
        );
    };
    return new Proxy(base, {
        get(target, prop, receiver) {
            if (typeof prop === 'string' && ADMIN_CORE_GLOBALS.includes(prop)) refuse(prop);
            return Reflect.get(target, prop, receiver);
        },
        has(target, prop) {
            if (typeof prop === 'string' && ADMIN_CORE_GLOBALS.includes(prop)) refuse(prop);
            return Reflect.has(target, prop);
        },
    });
}

// ---------------------------------------------------------------------------
// A DOM small enough to hand-roll and real enough to answer the two questions
// the sections ask of it: "did the markup I just wrote land?" and "give me the
// node I want to attach a listener to". vitest runs in the `node` environment
// here, like the rest of this suite.
// ---------------------------------------------------------------------------

const ATTR_RE = /([:a-zA-Z_][-:.\w]*)\s*=\s*"([^"]*)"/g;
const TAG_RE = /<([a-zA-Z][-\w]*)((?:\s+[^<>]*?)?)\/?>/g;

function camel(name) {
    return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

function makeElement(tagName = 'div', attrs = {}) {
    const listeners = new Map();
    const classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
    const dataset = {};
    for (const [k, v] of Object.entries(attrs)) {
        if (k.startsWith('data-')) dataset[camel(k.slice(5))] = v;
    }
    let html = '';
    let children = [];

    const el = {
        tagName: tagName.toUpperCase(),
        attrs: { ...attrs },
        dataset,
        textContent: '',
        value: '',
        disabled: false,
        checked: false,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            toggle: (c, on) => (on === undefined ? (classes.has(c) ? classes.delete(c) : classes.add(c)) : (on ? classes.add(c) : classes.delete(c))),
            contains: (c) => classes.has(c),
        },
        get innerHTML() { return html; },
        set innerHTML(v) {
            html = String(v);
            children = parseElements(html);
        },
        setAttribute(name, value) { el.attrs[name] = String(value); },
        getAttribute(name) { return name in el.attrs ? el.attrs[name] : null; },
        removeAttribute(name) { delete el.attrs[name]; },
        addEventListener(type, fn) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(fn);
        },
        dispatch(type) {
            for (const fn of listeners.get(type) || []) fn({ type, target: el, currentTarget: el });
        },
        click() { el.dispatch('click'); },
        closest: () => null,
        querySelector(sel) { return children.find((c) => matches(c, sel)) || null; },
        querySelectorAll(sel) { return children.filter((c) => matches(c, sel)); },
    };
    return el;
}

/** Turn a markup string into the element stubs its open tags describe. */
function parseElements(markup) {
    const out = [];
    for (const tag of markup.matchAll(TAG_RE)) {
        const attrs = {};
        for (const a of (tag[2] || '').matchAll(ATTR_RE)) attrs[a[1]] = a[2];
        out.push(makeElement(tag[1], attrs));
    }
    return out;
}

/** Simple-selector match: `tag`, `#id`, `.class`, `[attr]`, `[attr="v"]`. */
function matches(el, selector) {
    const parts = selector.trim().match(/(\[[^\]]+\]|[.#]?[-\w]+)/g) || [];
    return parts.every((part) => {
        if (part.startsWith('#')) return el.attrs.id === part.slice(1);
        if (part.startsWith('.')) return el.classList.contains(part.slice(1));
        if (part.startsWith('[')) {
            const m = /^\[([-\w:.]+)(?:=["']?([^"'\]]*)["']?)?\]$/.exec(part);
            if (!m) return false;
            if (!(m[1] in el.attrs)) return false;
            return m[2] === undefined || el.attrs[m[1]] === m[2];
        }
        return el.tagName === part.toUpperCase();
    });
}

/** A `document` backed by a fixed set of elements, keyed by id. */
function makeDocument(ids) {
    const byId = {};
    for (const id of ids) {
        byId[id] = makeElement('div', { id });
    }
    return {
        byId,
        readyState: 'complete',
        getElementById: (id) => byId[id] || null,
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: (tag) => makeElement(tag),
        addEventListener() {},
        body: makeElement('body'),
    };
}

// Timers started while a page is booted. mix.js debounces its preview by 60ms;
// if that fires after the stub `document` is torn down it becomes an unhandled
// error in whichever test file happens to be running next.
const pendingTimers = [];

/** Install the sentinel window + a stub document, then import modules fresh. */
function bootPage(elementIds, { fetchImpl } = {}) {
    vi.resetModules();
    const doc = makeDocument(elementIds);
    const base = {
        BeatifyUtils: { escapeHtml: (s) => String(s == null ? '' : s) },
        BeatifyI18n: { t: (k) => k },
        BeatifyAuth: { fetch: fetchImpl || (async () => ({ ok: true, json: async () => ({}) })) },
        localStorage: {
            _s: {},
            getItem(k) { return k in this._s ? this._s[k] : null; },
            setItem(k, v) { this._s[k] = String(v); },
            removeItem(k) { delete this._s[k]; },
        },
        fetch: fetchImpl || (async () => ({ ok: true, json: async () => ({}) })),
        setTimeout: (fn) => globalThis.setTimeout(fn, 0),
        clearTimeout: (id) => globalThis.clearTimeout(id),
    };
    const win = sentinelWindow(base);
    globalThis.window = win;
    globalThis.document = doc;
    globalThis.BeatifyI18n = base.BeatifyI18n;
    globalThis.BeatifyAuth = base.BeatifyAuth;
    globalThis.localStorage = base.localStorage;
    globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };
    const realSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = (...args) => {
        const id = realSetTimeout(...args);
        pendingTimers.push(id);
        return id;
    };
    savedGlobals.setTimeout = realSetTimeout;
    return doc;
}

const savedGlobals = {};
beforeEach(() => {
    for (const k of ['window', 'document', 'BeatifyI18n', 'BeatifyAuth', 'localStorage', 'setTimeout']) {
        savedGlobals[k] = globalThis[k];
    }
});
afterEach(() => {
    while (pendingTimers.length) globalThis.clearTimeout(pendingTimers.pop());
    for (const [k, v] of Object.entries(savedGlobals)) {
        if (v === undefined) delete globalThis[k];
        else globalThis[k] = v;
    }
    vi.resetModules();
});

// ---------------------------------------------------------------------------

/** Every module under www/js/admin/, discovered so a new section is covered. */
function adminModules() {
    const out = [];
    const walk = (dir) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const p = join(dir, entry.name);
            if (entry.isDirectory()) walk(p);
            else if (entry.isFile() && entry.name.endsWith('.js')) out.push(p);
        }
    };
    walk(join(JS_DIR, 'admin'));
    return out.sort();
}

describe('#2637 a section loads without the admin core', () => {
    it('finds the section modules it is about to import', () => {
        // Guards the guard: an empty sweep would make the test below vacuous.
        const names = adminModules().map((p) => relative(JS_DIR, p));
        expect(names).toContain('admin/sections/mix.js');
        expect(names).toContain('admin/sections/media-players.js');
        expect(names.length).toBeGreaterThan(10);
    });

    it.each(adminModules().map((p) => [relative(JS_DIR, p), p]))(
        '%s evaluates with no admin-core global on the page',
        async (_name, path) => {
            bootPage([]);
            // A throw here is the sentinel: the module reached for something
            // admin.js publishes while admin.js has never been imported.
            await expect(import(/* @vite-ignore */ path)).resolves.toBeTruthy();
        },
    );

    it('tts-settings and party-lights hand over their config as imports', async () => {
        bootPage([]);
        const { ttsConfig } = await import('../tts-settings.js');
        const { partyLightsConfig } = await import('../party-lights.js');
        // Before #2637 these two were classic scripts and the only way to reach
        // them was `window._ttsConfig` — a name the sentinel now refuses.
        const tts = ttsConfig();
        expect(typeof tts.enabled).toBe('boolean');
        expect(Object.keys(tts).filter((k) => k.startsWith('announce_'))).toHaveLength(23);
        const lights = partyLightsConfig();
        expect(typeof lights.enabled).toBe('boolean');
        expect(Array.isArray(lights.entity_ids)).toBe(true);
    });
});

describe('#2637 the media-players Refresh button runs on an injected dependency', () => {
    it('calls the refreshStatus it was given at init', async () => {
        const doc = bootPage(['media-players-list', 'media-player-validation-msg', 'start-game']);
        const { initMediaPlayers, renderMediaPlayers } = await import('../admin/sections/media-players.js');

        const refreshStatus = vi.fn();
        initMediaPlayers({ refreshStatus });
        renderMediaPlayers([]); // no compatible players → the empty state

        const button = doc.byId['media-players-list'].querySelector('[data-action="refresh-status"]');
        expect(button, 'the empty state must offer a Refresh control').not.toBeNull();
        button.click();
        expect(refreshStatus).toHaveBeenCalledTimes(1);
    });

    it('does not blow up when nothing was injected', async () => {
        // The old inline onclick="loadStatus()" needed a page global to exist.
        // Without an injected dependency the button must simply do nothing.
        const doc = bootPage(['media-players-list', 'media-player-validation-msg', 'start-game']);
        const { renderMediaPlayers } = await import('../admin/sections/media-players.js');
        renderMediaPlayers([]);
        const button = doc.byId['media-players-list'].querySelector('[data-action="refresh-status"]');
        expect(() => button.click()).not.toThrow();
    });
});

describe('#2637 the playlists section clears its own filters', () => {
    it('resets the filter state when its Clear button is clicked', async () => {
        const doc = bootPage(['playlists-list', 'playlist-filter-bar', 'start-game']);
        const { adminState } = await import('../admin/state.js');
        const { renderPlaylists, updateActiveFilterTags } = await import('../admin/sections/playlists.js');

        adminState.activeFilters = { decade: '1980s', style: '', region: '', special: '' };
        updateActiveFilterTags();
        renderPlaylists(
            [{ path: '/pl/a.json', name: 'A', is_valid: true, tags: ['1990s'], song_count: 10 }],
            '/pl',
        );

        const clear = doc.byId['playlists-list'].querySelector('[data-action="clear-filters"]');
        expect(clear, 'a filter that matches nothing must offer a way out').not.toBeNull();
        clear.click();

        expect(adminState.activeFilterTags).toEqual(['all']);
        expect(adminState.activeFilters).toEqual({ decade: '', style: '', region: '', special: '' });
        // The re-render happened: the playlist the filter was hiding is back.
        expect(doc.byId['playlists-list'].innerHTML).toContain('/pl/a.json');
    });
});

describe('#2637 the Mix tab refreshes through its injected dependency', () => {
    it('calls refreshStatus after saving the mix as a community playlist', async () => {
        const fetchImpl = vi.fn(async (url) => {
            if (String(url).includes('/playlists/mix')) {
                return { ok: true, json: async () => ({ success: true, path: '/pl/mix.json', song_count: 42 }) };
            }
            return { ok: true, json: async () => ({ success: true, song_count: 42, playlist_count: 3 }) };
        });
        const doc = bootPage(
            ['mix-chip-cloud', 'mix-start', 'mix-save-community', 'mix-error', 'mix-preview-text'],
            { fetchImpl },
        );
        const { adminState } = await import('../admin/state.js');
        const { initMixTab, renderMixChipCloud } = await import('../admin/sections/mix.js');

        const startGame = vi.fn();
        const refreshStatus = vi.fn();
        initMixTab({ startGame, refreshStatus });

        adminState.selectedMediaPlayer = { entityId: 'media_player.kitchen', platform: 'mass' };
        adminState.playlistData = [{ path: '/pl/a.json', name: 'A', is_valid: true, tags: ['1980s'] }];
        renderMixChipCloud();

        const chip = doc.byId['mix-chip-cloud'].querySelector('[data-mix-tag="1980s"]');
        expect(chip, 'a tagged playlist must produce a chip to select').not.toBeNull();
        chip.click(); // select the tag so the mix has something to assemble

        // initMixTab() has already bound #mix-start (it calls bindMixPanel).
        doc.byId['mix-save-community'].checked = true;
        doc.byId['mix-start'].dispatch('click');
        // startMix awaits the assemble POST before the refresh; let it settle.
        await new Promise((r) => setTimeout(r, 0));

        expect(refreshStatus).toHaveBeenCalledTimes(1);
        expect(startGame).toHaveBeenCalledTimes(1);
    });
});

describe('#2637 nothing is both bundled and loaded on its own', () => {
    /**
     * admin.html's `<script src>` list is the page's load order; the bundle's
     * esbuild metafile is its real module graph. A file appearing in both means
     * the page runs two copies of one module and something has to load first —
     * exactly the shape that made `window._ttsConfig` necessary.
     */
    let inputs;
    let scripts;

    beforeEach(async () => {
        if (!inputs) {
            const result = await build({
                entryPoints: [join(JS_DIR, 'admin.js')],
                bundle: true,
                format: 'esm',
                write: false,
                metafile: true,
                logLevel: 'silent',
            });
            inputs = Object.keys(result.metafile.inputs)
                .map((p) => relative(JS_DIR, resolve(REPO_ROOT, p)));
        }
        if (!scripts) {
            const html = await readFile(join(WWW_DIR, 'admin.html'), 'utf8');
            scripts = [...html.matchAll(/<script[^>]+src="\/beatify\/static\/js\/([^"?]+)/g)]
                .map((m) => m[1]);
        }
    });

    it('bundles the two config sections that used to be classic scripts', () => {
        // This is what puts them under `npm run build:check` (#1263).
        expect(inputs).toContain('tts-settings.js');
        expect(inputs).toContain('party-lights.js');
    });

    it('does not also load a bundled module as its own script tag', () => {
        const duplicated = scripts
            .filter((src) => src !== 'admin.min.js')
            .map((src) => src.replace(/\.min\.js$/, '.js'))
            .filter((src) => inputs.includes(src));
        expect(duplicated).toEqual([]);
    });
});
