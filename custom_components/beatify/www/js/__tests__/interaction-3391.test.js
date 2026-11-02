/**
 * #3391 — interaction fixes that live in markup and CSS.
 *
 * vitest has no layout engine, so the measured half of this issue (target
 * sizes, spacing, the year track's width) is checked by the browser test in
 * tests/ui/test_tap_targets.py. This file pins the rules and attributes that
 * produce those numbers, in the source and in the shipped .min.css, so a later
 * edit that drops one fails here first.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const read = (...p) => readFileSync(join(WWW_DIR, ...p), 'utf8');
const PLAYER = read('player.html');
const ADMIN = read('admin.html');
const DASHBOARD = read('dashboard.html');
const CSS = read('css', 'styles.css').replace(/\/\*[\s\S]*?\*\//g, '');
const MIN = read('css', 'styles.min.css');

function inputTag(html, id) {
    const m = html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`, 's'));
    expect(m, `#${id} in markup`).not.toBeNull();
    return m[0];
}

// Every block for exactly this selector, joined: a later block may add to an
// earlier one (styles.css has two `.slider-arcade` rules on purpose).
function rule(css, selector) {
    const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const blocks = [...css.matchAll(new RegExp(`(?:^|})\\s*${esc}\\s*\\{([^}]*)\\}`, 'gm'))];
    return blocks.length ? blocks.map((m) => m[1]).join('\n') : null;
}

describe('#3391 name fields work with the phone keyboard', () => {
    for (const [page, html, id] of [['player', PLAYER, 'name-input'], ['admin', ADMIN, 'admin-name-input']]) {
        it(`${page} #${id}: no autocorrect, no autocapitalize, no spellcheck, Enter says "go"`, () => {
            const tag = inputTag(html, id);
            expect(tag).toMatch(/autocorrect="off"/);
            expect(tag).toMatch(/autocapitalize="off"/);
            expect(tag).toMatch(/spellcheck="false"/);
            expect(tag).toMatch(/enterkeyhint="go"/);
            expect(tag).toMatch(/aria-describedby="/);
        });
    }

    it('the rejected mark has a style that beats the dark theme focus border', () => {
        expect(CSS).toMatch(/body\.theme-dark \.name-input\.name-input--invalid:focus/);
        expect(MIN).toContain('.name-input--invalid');
    });
});

describe('#3391 year slider: the track spans the full width', () => {
    it('the row wraps and the track is lifted above the four steppers', () => {
        const wrap = rule(CSS, '.slider-arcade');
        expect(wrap).toMatch(/flex-wrap:\s*wrap/);
        const track = rule(CSS, '.slider-arcade-track');
        expect(track).toMatch(/order:\s*-1/);
        expect(track).toMatch(/flex:\s*1 0 100%/);
    });

    it('the steppers share the row below, 44 px high, at least 8 px apart', () => {
        const btn = rule(CSS, '.slider-arcade .slider-btn-year');
        expect(btn).toMatch(/flex:\s*1 1 0/);
        expect(btn).toMatch(/height:\s*44px/);
        expect(rule(CSS, '.slider-arcade')).toMatch(/gap:\s*12px var\(--space-sm\)/);
    });

    it('keeps the markup order (−5 · − · track · + · +5) for the keyboard', () => {
        const ids = [...PLAYER.matchAll(/id="(year-decrement-5|year-decrement|year-slider|year-increment|year-increment-5)"/g)]
            .map((m) => m[1]);
        expect(ids).toEqual(['year-decrement-5', 'year-decrement', 'year-slider', 'year-increment', 'year-increment-5']);
    });

    it('ships in the minified stylesheet', () => {
        expect(MIN).toMatch(/\.slider-arcade-track\{order:-1/);
    });
});

describe('#3391 admin leaderboard ⋮ spacing', () => {
    it('rows with the host control are 52 px, so two 44 px targets sit 8 px apart', () => {
        expect(rule(CSS, '.leaderboard-entry:has(.entry-host-action)')).toMatch(/height:\s*52px/);
        expect(rule(CSS, '.leaderboard-list:has(.entry-host-action)')).toMatch(/padding-top:\s*var\(--space-xs\)/);
    });
});

describe('#3391 destructive confirms are red', () => {
    for (const id of ['kick-player-confirm-btn', 'reset-confirm-btn', 'end-game-confirm-btn', 'new-game-confirm-btn']) {
        it(`#${id} uses btn-danger`, () => {
            const m = ADMIN.match(new RegExp(`<button[^>]*id="${id}"[^>]*>`));
            expect(m).not.toBeNull();
            expect(m[0]).toMatch(/class="btn btn-danger"/);
        });
    }
});

describe('#3391 TV wake banner works with a remote', () => {
    it('both buttons have a visible focus ring', () => {
        expect(DASHBOARD).toMatch(/\.dashboard-wakelock-activate:focus-visible,\s*\.dashboard-wakelock-dismiss:focus-visible\s*\{[^}]*outline:\s*3px solid/);
    });

    it('the banner focuses Activate when it appears', () => {
        const js = read('js', 'dashboard.js');
        const fn = js.slice(js.indexOf('function _showWakeBanner'), js.indexOf('function _initWakeBanner'));
        expect(fn).toMatch(/dashboard-wakelock-activate/);
        expect(fn).toMatch(/\.focus\(/);
    });

    it('the entrance animation stops under reduced motion', () => {
        expect(DASHBOARD).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*\.dashboard-wakelock-banner \{ animation: none; \}/);
    });
});

describe('#3391 tour accepts a sideways swipe', () => {
    it('the browser keeps vertical scrolling, the horizontal pan comes to JS', () => {
        expect(rule(CSS, '.tour-container')).toMatch(/touch-action:\s*pan-y/);
    });
});

describe('#3391 undo toast', () => {
    it('docks at the bottom and its Undo button is a 44 px target', () => {
        expect(rule(CSS, '.beatify-toast-container--bottom')).toMatch(/bottom:/);
        const undo = rule(CSS, '.beatify-toast-undo');
        expect(undo).toMatch(/min-width:\s*44px/);
        expect(undo).toMatch(/min-height:\s*44px/);
    });

    it('does not slide under reduced motion', () => {
        expect(CSS).toMatch(/prefers-reduced-motion: reduce\)\s*\{[^@]*\.beatify-toast-container--bottom \.beatify-toast \{ transform: none; \}/);
    });

    it('the strings exist in all six languages, the removed confirm strings are gone', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            const d = JSON.parse(read('i18n', `${lang}.json`));
            expect(d.steal.pending, lang).toMatch(/\{name\}…$/);
            expect(d.sabotage.pending, lang).toMatch(/\{name\}…$/);
            expect(d.common.undo, lang).toBeTruthy();
            expect(d.steal.confirmTitle, lang).toBeUndefined();
            expect(d.sabotage.confirmTitle, lang).toBeUndefined();
        }
    });
});
