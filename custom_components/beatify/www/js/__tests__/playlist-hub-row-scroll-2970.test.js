/**
 * #2970: "+ Add" in the playlist hub must not throw the row back to its start.
 *
 * The hub rebuilds its body from HTML on every selection change. That put every
 * horizontal shelf at scrollLeft 0, so the card just added scrolled out of
 * view, in the genre rows and in search results alike. `_withRowScroll` wraps
 * the rebuild and carries each row's position across it, matched by shelf
 * title. The fake host below rebuilds its rows from the HTML it is given, the
 * way a browser does — fresh elements, scrolled to 0.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { _withRowScroll } from '../playlist-hub.js';
import { JS_DIR } from './helpers/js-source.js';

/** A body whose innerHTML setter builds fresh shelves, each unscrolled. */
function fakeHost() {
    const host = {
        scrollTop: 0,
        shelves: [],
        set innerHTML(html) {
            this.shelves = [...String(html).matchAll(/class="plh-shelf-title">([^<]*)</g)].map((m) => {
                const row = { scrollLeft: 0 };
                const title = { textContent: m[1] };
                return {
                    row,
                    querySelector: (sel) => (sel === '.plh-cards' ? row : sel === '.plh-shelf-title' ? title : null),
                };
            });
        },
        querySelectorAll(sel) {
            return sel === '.plh-shelf' ? this.shelves : [];
        },
    };
    return host;
}

const shelf = (title) => `<div class="plh-shelf"><div class="plh-shelf-title">${title}</div><div class="plh-cards"></div></div>`;

describe('#2970 the hub keeps each row where it was across a re-render', () => {
    it('restores the scroll offset of every row by title', () => {
        const host = fakeHost();
        host.innerHTML = shelf('Pop') + shelf('Other');
        host.shelves[0].row.scrollLeft = 640;
        host.shelves[1].row.scrollLeft = 1280;

        _withRowScroll(host, () => { host.innerHTML = shelf('Pop') + shelf('Other'); });

        expect(host.shelves[0].row.scrollLeft).toBe(640);
        expect(host.shelves[1].row.scrollLeft).toBe(1280);
    });

    it('matches rows by title when a new shelf appears above them', () => {
        // The first pick makes the local "Your picks"-style shelf appear on top.
        const host = fakeHost();
        host.innerHTML = shelf('Pop') + shelf('Other');
        host.shelves[1].row.scrollLeft = 900;

        _withRowScroll(host, () => { host.innerHTML = shelf('Most played') + shelf('Pop') + shelf('Other'); });

        expect(host.shelves[0].row.scrollLeft).toBe(0);
        expect(host.shelves[1].row.scrollLeft).toBe(0);
        expect(host.shelves[2].row.scrollLeft).toBe(900);
    });

    it('keeps the search results row too', () => {
        const host = fakeHost();
        host.innerHTML = shelf('Results');
        host.shelves[0].row.scrollLeft = 420;
        _withRowScroll(host, () => { host.innerHTML = shelf('Results'); });
        expect(host.shelves[0].row.scrollLeft).toBe(420);
    });

    it('keeps the body scrolled where it was', () => {
        const host = fakeHost();
        host.innerHTML = shelf('Pop');
        host.scrollTop = 300;
        _withRowScroll(host, () => { host.scrollTop = 0; host.innerHTML = shelf('Pop'); });
        expect(host.scrollTop).toBe(300);
    });

    it('wraps the tab body render, which "+ Add" goes through', () => {
        const src = readFileSync(join(JS_DIR, 'playlist-hub.js'), 'utf8');
        const body = src.slice(src.indexOf('function _renderTabBody('), src.indexOf('function _rowKeys('));
        expect(body).toMatch(/_withRowScroll\(host, \(\) => \{[\s\S]*_renderBundled\(host\)[\s\S]*\}\);/);
        // and the pill click still re-renders through it
        const click = src.slice(src.indexOf("const check = e.target.closest('[data-plh-check]')"));
        expect(click.slice(0, 300)).toContain('_renderTabBody()');
    });
});
