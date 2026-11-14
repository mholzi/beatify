/**
 * #3504: the 2-line fun-fact hook on the player reveal expands in place
 * (design Variante 1). A "more" button shows only when the text overflows the
 * clamp; the button and the text itself toggle to the full text ("less"),
 * keyboard users get a real <button> with aria-expanded, and the state resets
 * when the fun fact changes or the phase leaves REVEAL, but not on the
 * re-renders every reaction/vote broadcast triggers.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const WWW = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

function makeEl(id) {
    const classes = new Set();
    const listeners = {};
    const el = {
        id,
        textContent: '',
        scrollHeight: 0,
        clientHeight: 0,
        _attrs: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => {
                const want = on === undefined ? !classes.has(c) : on;
                if (want) classes.add(c); else classes.delete(c);
                return classes.has(c);
            },
        },
        setAttribute: (k, v) => { el._attrs[k] = String(v); },
        getAttribute: (k) => el._attrs[k],
        addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
        click: () => (listeners.click || []).forEach((fn) => fn({ stopPropagation() {} })),
    };
    return el;
}

let text;
let btn;
let observers;

global.window = {
    BeatifyUtils: {
        t: (key) => ({ 'reveal.funFactMore': 'mehr', 'reveal.funFactLess': 'weniger' }[key] || key),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.document = {
    getElementById: (id) => ({ 'fun-fact': text, 'fun-fact-toggle': btn }[id] || null),
    querySelector: () => null,
    querySelectorAll: () => [],
};
global.ResizeObserver = class {
    constructor(cb) { this.cb = cb; observers.push(this); }
    observe() {}
};

vi.mock('../player-utils.js', () => ({
    state: {}, escapeHtml: (s) => s, prefersReducedMotion: () => true,
    animateValue: () => {}, previousState: {}, isPreviousStateInitialized: () => false,
    AnimationUtils: {}, updatePreviousState: () => {}, triggerConfetti: () => {},
    stopConfetti: () => {}, isTitleArtistMode: () => false,
    createModalFocusTrap: () => ({}), classifyYearsOff: () => '',
}));
vi.mock('../player-game.js', () => ({ renderArtistReveal: () => {}, renderMovieReveal: () => {} }));
vi.mock('../round-end-choice.js', () => ({ renderVoidedBanner: () => {} }));
vi.mock('../round-settings.js', () => ({ setupRoundSettings: () => {}, renderRoundSettings: () => {} }));

const { renderFunFactToggle, stopRevealCountdown } = await import('../player-reveal.js');

function show(str, overflows) {
    text.textContent = str;
    text.clientHeight = 34;
    text.scrollHeight = overflows ? 84 : 34;
    renderFunFactToggle(str);
}

describe('#3504 expandable fun fact', () => {
    beforeEach(() => {
        text = makeEl('fun-fact');
        btn = makeEl('fun-fact-toggle');
        observers = [];
        stopRevealCountdown();
    });

    it('shows no toggle when the text fits in two lines', () => {
        show('Short fact.', false);
        expect(btn.classList.contains('hidden')).toBe(true);
        expect(text.classList.contains('is-expandable')).toBe(false);
        text.click();
        expect(text.classList.contains('is-expanded')).toBe(false);
    });

    it('shows "more" collapsed, and the button toggles to "less" and back', () => {
        show('A long fact that runs well past two lines.', true);
        expect(btn.classList.contains('hidden')).toBe(false);
        expect(btn.textContent).toBe('mehr');
        expect(btn.getAttribute('aria-expanded')).toBe('false');

        btn.click();
        expect(text.classList.contains('is-expanded')).toBe(true);
        expect(btn.getAttribute('aria-expanded')).toBe('true');
        expect(btn.textContent).toBe('weniger');
        expect(btn.getAttribute('data-i18n')).toBe('reveal.funFactLess');

        btn.click();
        expect(text.classList.contains('is-expanded')).toBe(false);
        expect(btn.textContent).toBe('mehr');
        expect(btn.getAttribute('data-i18n')).toBe('reveal.funFactMore');
    });

    it('tapping the text itself expands and collapses too', () => {
        show('A long fact that runs well past two lines.', true);
        text.click();
        expect(text.classList.contains('is-expanded')).toBe(true);
        text.click();
        expect(text.classList.contains('is-expanded')).toBe(false);
    });

    it('stays expanded across re-renders of the same reveal', () => {
        show('A long fact that runs well past two lines.', true);
        btn.click();
        show('A long fact that runs well past two lines.', true);
        expect(text.classList.contains('is-expanded')).toBe(true);
        expect(btn.classList.contains('hidden')).toBe(false);
    });

    it('collapses for a new fun fact and after the phase leaves REVEAL', () => {
        show('A long fact that runs well past two lines.', true);
        btn.click();
        show('Another long fact for the next round, also long.', true);
        expect(text.classList.contains('is-expanded')).toBe(false);

        btn.click();
        stopRevealCountdown();
        show('Another long fact for the next round, also long.', true);
        expect(text.classList.contains('is-expanded')).toBe(false);
    });

    it('re-measures when the hidden reveal gets laid out', () => {
        text.textContent = 'A long fact that runs well past two lines.';
        renderFunFactToggle(text.textContent); // hidden view: 0 x 0
        expect(btn.classList.contains('hidden')).toBe(true);
        text.clientHeight = 34;
        text.scrollHeight = 84;
        observers.forEach((o) => o.cb());
        expect(btn.classList.contains('hidden')).toBe(false);
    });
});

describe('#3504 markup, styles and strings', () => {
    const html = readFileSync(resolve(WWW, 'player.html'), 'utf8');
    const css = readFileSync(resolve(WWW, 'css/styles.css'), 'utf8');

    it('the toggle is a hidden-by-default button wired to the text', () => {
        const tag = html.match(/<button[^>]*id="fun-fact-toggle"[^>]*>/s);
        expect(tag).not.toBeNull();
        expect(tag[0]).toMatch(/type="button"/);
        expect(tag[0]).toMatch(/aria-controls="fun-fact"/);
        expect(tag[0]).toMatch(/aria-expanded="false"/);
        expect(tag[0]).toMatch(/class="[^"]*\bhidden\b/);
    });

    it('the toggle is a 44 px target and expanded text drops the clamp', () => {
        const rule = css.match(/#reveal-view \.fun-fact-toggle \{[^}]*\}/);
        expect(rule).not.toBeNull();
        expect(rule[0]).toMatch(/min-width:\s*44px/);
        expect(rule[0]).toMatch(/min-height:\s*44px/);
        const expanded = css.match(/#reveal-view \.fun-fact-text\.is-expanded \{[^}]*\}/);
        expect(expanded[0]).toMatch(/-webkit-line-clamp:\s*unset/);
    });

    it.each(['en', 'de', 'fr', 'es', 'nl', 'it'])('%s has both strings', (lang) => {
        const d = JSON.parse(readFileSync(resolve(WWW, `i18n/${lang}.json`), 'utf8'));
        expect(d.reveal.funFactMore).toBeTruthy();
        expect(d.reveal.funFactLess).toBeTruthy();
    });
});
