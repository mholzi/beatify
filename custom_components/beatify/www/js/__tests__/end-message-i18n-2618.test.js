/**
 * #2618 — the player end screen must not fall back to English literals.
 *
 * `handleGameEnded` wrote `'<p>Thanks for playing!</p>'` and
 * `'<p class="rejoin-hint">Scan the QR code again to join the next game.</p>'`
 * straight into `#end-player-message`. Both sentences landed in the middle of
 * an otherwise fully translated page, on every game end, in every language.
 *
 * The rendering now lives in `player-end.js` (`renderEndPlayerMessage`) and
 * resolves both sentences through i18n. This drives that function with a real
 * locale file behind `t()`, so the test fails the moment either sentence is a
 * literal again.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WWW = join(__dirname, '..', '..');
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

const i18n = {};
for (const l of LOCALES) {
    i18n[l] = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
}
const lookup = (obj, key) =>
    key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);

// ---- a DOM small enough to render two <p> into ----------------------------
function makeNode(tag) {
    const classes = new Set();
    return {
        tagName: tag.toUpperCase(),
        textContent: '',
        children: [],
        set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
        get className() { return [...classes].join(' '); },
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
        appendChild(child) { this.children.push(child); return child; },
        set innerHTML(v) { if (!v) this.children.length = 0; this._html = v; },
        get innerHTML() { return this._html || ''; },
    };
}

// `locale` is swapped per test; player-end.js reads window.BeatifyUtils once at
// module load, so the object identity has to stay stable.
let locale = 'en';
global.window = {
    BeatifyUtils: {
        t: (key) => {
            const v = lookup(i18n[locale], key);
            return v === undefined ? key : v; // t() returns the key on a miss
        },
    },
};
global.document = { getElementById: () => null, createElement: (tag) => makeNode(tag) };

vi.mock('../player-utils.js', () => ({
    state: { playerName: null },
    escapeHtml: (s) => String(s),
    showConfirmModal: () => {},
    AnimationQueue: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    showView: () => {},
}));
vi.mock('../notify.js', () => ({ showToast: () => {} }));

const { renderEndPlayerMessage } = await import('../player-end.js');

function render(loc) {
    locale = loc;
    const container = makeNode('div');
    container.classList.add('hidden');
    renderEndPlayerMessage(container);
    return container;
}

describe('#2618 end-screen message is translated', () => {
    beforeEach(() => { locale = 'en'; });

    it('both sentences exist as keys in all six locales', () => {
        for (const l of LOCALES) {
            expect(lookup(i18n[l], 'leaderboard.thanksEmoji'), `${l}: thanksEmoji`).toBeTruthy();
            expect(lookup(i18n[l], 'leaderboard.rejoinHint'), `${l}: rejoinHint`).toBeTruthy();
        }
    });

    it('renders the German sentences for a German guest', () => {
        const container = render('de');
        const texts = container.children.map((c) => c.textContent);

        expect(texts).toEqual([
            i18n.de.leaderboard.thanksEmoji,
            i18n.de.leaderboard.rejoinHint,
        ]);
        // The exact literals the bug shipped — neither may survive in any form.
        expect(texts.join(' ')).not.toContain('Thanks for playing');
        expect(texts.join(' ')).not.toContain('Scan the QR code again');
    });

    it('renders every locale in its own language, never English', () => {
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            const texts = render(l).children.map((c) => c.textContent);
            expect(texts[0], `${l}: thanks`).toBe(i18n[l].leaderboard.thanksEmoji);
            expect(texts[1], `${l}: hint`).toBe(i18n[l].leaderboard.rejoinHint);
            expect(texts[1], `${l}: hint is translated`).not.toBe(i18n.en.leaderboard.rejoinHint);
        }
    });

    it('keeps the rejoin-hint class and unhides the block', () => {
        const container = render('en');
        expect(container.children).toHaveLength(2);
        expect(container.children[1].className).toBe('rejoin-hint');
        expect(container.classList.contains('hidden')).toBe(false);
    });

    it('does nothing when the block is absent', () => {
        expect(() => renderEndPlayerMessage(null)).not.toThrow();
    });
});
