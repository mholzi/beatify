/**
 * A whole admin page, small enough to hand-roll (#2637, extracted in #2679).
 *
 * vitest runs in the `node` environment here and the repo deliberately carries
 * no jsdom, so a suite that needs to drive real section code builds the DOM it
 * needs. `helpers/mini-dom.js` covers renderers that write into elements a test
 * hands them; this covers the other shape — a module that sets `innerHTML` and
 * then goes looking for the controls it just wrote, which is how every admin
 * section mounts itself.
 *
 * What it adds on top of a DOM: a `window` whose reads of an admin-core name
 * THROW. A section that reaches back into admin.js through `window` fails
 * loudly at the moment it is evaluated, instead of silently no-opping the way
 * `typeof window.x === 'function'` does when nothing ever defined `x` — the
 * defect #2679 was.
 */
import { vi } from 'vitest';

/**
 * Names that belong to the admin core (admin.js) or to what used to be a
 * classic script it handshook with.
 *
 * Six of these still exist on the page on purpose. `BEATIFY_VERSION` is read by
 * playlist-requests.js, a classic script that cannot import from the admin
 * bundle at all. The other five are read by wizard.js, which #2680 moved INTO
 * the bundle — admin.js imports it, so a direct import back would close a cycle
 * and `window` stays as the cycle-breaker. Either way that is a boundary
 * between two entry points or a deliberate cycle-break, not the silent
 * load-order coupling #2637 was about. What must never come back is a module
 * UNDER admin/ reading one of them: those modules are inside the same bundle
 * and can import what they need.
 *
 * The eight that no longer exist are listed too, so re-adding one and quietly
 * depending on it also trips the sentinel.
 */
export const ADMIN_CORE_GLOBALS = [
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
export function sentinelWindow(base) {
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

export function makeElement(tagName = 'div', attrs = {}) {
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
        // `id` and `className` are properties in the DOM but attributes to
        // `querySelector`. A module that builds a node with createElement sets
        // the property (library-ai.js does), so keep the two in step or the
        // node becomes unfindable by the selector that names it.
        get id() { return el.attrs.id || ''; },
        set id(v) { el.attrs.id = String(v); },
        get className() { return [...classes].join(' '); },
        set className(v) {
            classes.clear();
            for (const c of String(v).split(/\s+/).filter(Boolean)) classes.add(c);
            el.attrs.class = String(v);
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
        focus() { el.focused = true; },
        // A module that builds a modal does `createElement` + `innerHTML` +
        // `body.appendChild`; the parent only has to remember the node so the
        // test can reach it, since the module keeps its own reference anyway.
        appendChild(child) { children.push(child); return child; },
        closest: () => null,
        querySelector(sel) { return children.find((c) => matches(c, sel)) || null; },
        querySelectorAll(sel) { return children.filter((c) => matches(c, sel)); },
    };
    return el;
}

/** Turn a markup string into the element stubs its open tags describe. */
export function parseElements(markup) {
    const out = [];
    for (const tag of markup.matchAll(TAG_RE)) {
        const attrs = {};
        for (const a of (tag[2] || '').matchAll(ATTR_RE)) attrs[a[1]] = a[2];
        out.push(makeElement(tag[1], attrs));
    }
    return out;
}

/** Simple-selector match: `tag`, `#id`, `.class`, `[attr]`, `[attr="v"]`. */
export function matches(el, selector) {
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
export function makeDocument(ids) {
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

const savedGlobals = {};

// Timers started while a page is booted. mix.js debounces its preview by 60ms;
// if that fires after the stub `document` is torn down it becomes an unhandled
// error in whichever test file happens to be running next.
const pendingTimers = [];

/** Install the sentinel window + a stub document, then import modules fresh. */
export function bootPage(elementIds, { fetchImpl } = {}) {
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

/**
 * Save the globals `bootPage` overwrites. Call from `beforeEach`.
 */
export function saveGlobals() {
    for (const k of ['window', 'document', 'BeatifyI18n', 'BeatifyAuth', 'localStorage', 'setTimeout']) {
        savedGlobals[k] = globalThis[k];
    }
}

/**
 * Put them back and drop any timer a booted page started. Call from `afterEach`.
 */
export function restoreGlobals() {
    while (pendingTimers.length) globalThis.clearTimeout(pendingTimers.pop());
    for (const [k, v] of Object.entries(savedGlobals)) {
        if (v === undefined) delete globalThis[k];
        else globalThis[k] = v;
    }
    vi.resetModules();
}
