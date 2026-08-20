/**
 * #2269 — expandMediaPlayersSection() is the destination of the "Select Speaker"
 * button in the start-game error banner.
 *
 * renderMediaPlayers() collapses the section once a speaker is restored from
 * localStorage. That is fine until the speaker disappears: the host then gets a
 * start failure whose fix sits inside a collapsed section below the home hero.
 * The banner button has to undo both halves of the collapse (the class AND the
 * aria-expanded state) and move the viewport there.
 *
 * vitest runs in the node env, so we hand-roll the two nodes involved.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

let section;
let toggle;
let elements;
let scrolls;

function makeNode() {
    const classes = new Set();
    const attrs = {};
    return {
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
        setAttribute: (k, v) => { attrs[k] = String(v); },
        getAttribute: (k) => attrs[k],
    };
}

beforeEach(() => {
    scrolls = [];
    section = makeNode();
    section.classList.add('collapsed');
    section.scrollIntoView = (opts) => scrolls.push(opts);
    toggle = makeNode();
    toggle.setAttribute('aria-expanded', 'false');

    elements = { 'media-players': section, 'media-players-toggle': toggle };
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.BeatifyI18n = { t: (k) => k };
    globalThis.document = {
        getElementById: (id) => elements[id] || null,
        querySelectorAll: () => [],
        querySelector: () => null,
    };
});

afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    vi.restoreAllMocks();
});

describe('expandMediaPlayersSection (#2269)', () => {
    it('un-collapses the section, fixes aria-expanded and scrolls it into view', async () => {
        const mp = await import('../admin/sections/media-players.js');
        mp.expandMediaPlayersSection();

        expect(section.classList.contains('collapsed')).toBe(false);
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(scrolls).toHaveLength(1);
        expect(scrolls[0].block).toBe('start');
    });

    it('is a no-op when the section is not on the page', async () => {
        elements = {};
        const mp = await import('../admin/sections/media-players.js');
        expect(() => mp.expandMediaPlayersSection()).not.toThrow();
    });
});
