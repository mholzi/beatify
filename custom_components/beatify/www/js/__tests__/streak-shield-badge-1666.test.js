/**
 * The Streak-Shield line must actually reach a player (#1666, #2601).
 *
 * The previous version of this file asserted source strings — that
 * `renderPersonalResult` contained a call to `renderStreakShieldUsed`. It
 * passed for months while the feature was dead: the #1611 reveal rework left
 * `renderPersonalResult` without a caller, so the shield fired, the streak
 * survived, and nothing was ever drawn. A test that string-matches a function
 * cannot tell whether anyone calls it.
 *
 * So these tests call the real `renderStreakShield` against a fake element and
 * assert what ends up in it. The vitest env is `node` (no jsdom), so the
 * globals below model just what the module touches at import time and what the
 * renderer reads.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '../../..');

// player-utils.js reads window.location + window.BeatifyUtils and probes
// prefers-reduced-motion at import time; player-reveal.js pulls it in.
globalThis.window = globalThis;
globalThis.window.BeatifyUtils = {
    t: (key, params) => {
        if (key !== 'reveal.streakShieldUsed') return key;
        return 'Shield used — {streak}-streak saved!'
            .replace('{streak}', String(params && params.streak));
    },
    escapeHtml: (s) => String(s),
};
globalThis.window.location = { search: '' };
globalThis.window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });

/** Minimal fake of the #reveal-streak-shield strip. */
function makeStrip() {
    const classes = new Set(['streak-shield-used', 'hidden']);
    return {
        innerHTML: '',
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
        get hidden() { return classes.has('hidden'); },
    };
}

let strip;
globalThis.document = {
    getElementById: (id) => (id === 'reveal-streak-shield' ? strip : null),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {} }),
    addEventListener() {},
};

const { renderStreakShield } = await import('../player-reveal.js');

describe('Streak-Shield line (#1666, rewired #2601)', () => {
    beforeEach(() => { strip = makeStrip(); });

    it('shows the line when a shield absorbed the round', () => {
        renderStreakShield({ streak_shield_used: true, streak: 5 });
        expect(strip.hidden, 'strip stayed hidden').toBe(false);
        expect(strip.innerHTML).toContain('streak-shield-text');
    });

    it('names the streak it saved', () => {
        // "Shield used" alone does not land; the number is the point (#1666).
        renderStreakShield({ streak_shield_used: true, streak: 5 });
        expect(strip.innerHTML).toContain('5-streak saved');
    });

    it('covers the missed round, where the shield fires just as often', () => {
        // A shield only ever fires on a round the player got wrong, and a
        // timeout is one of those. The old card had a separate branch for it;
        // one element on the card serves both, so this must hold with
        // missed_round set too.
        renderStreakShield({ streak_shield_used: true, streak: 3, missed_round: true });
        expect(strip.hidden).toBe(false);
        expect(strip.innerHTML).toContain('3-streak saved');
    });

    it('stays hidden and empty when no shield fired', () => {
        renderStreakShield({ streak_shield_used: false, streak: 5 });
        expect(strip.hidden, 'strip shown without a shield').toBe(true);
        expect(strip.innerHTML).toBe('');
    });

    it('survives a missing player', () => {
        renderStreakShield(null);
        expect(strip.hidden).toBe(true);
    });

    it('is called from the reveal update path', () => {
        // The failure of #2601 was not a broken renderer — it was a renderer
        // nobody called. Assert the wiring itself.
        const reveal = fs.readFileSync(path.join(ROOT, 'www/js/player-reveal.js'), 'utf8');
        expect(reveal).toContain('renderStreakShield(currentPlayer);');
    });

    it('has an element on the page to render into', () => {
        const html = fs.readFileSync(path.join(ROOT, 'www/player.html'), 'utf8');
        expect(html).toContain('id="reveal-streak-shield"');
    });

    it('has the string in every shipped locale', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'nl', 'it']) {
            const dict = JSON.parse(fs.readFileSync(
                path.join(ROOT, `www/i18n/${lang}.json`), 'utf8'));
            expect(dict.reveal?.streakShieldUsed, `${lang} missing`).toBeTruthy();
            expect(dict.reveal.streakShieldUsed, `${lang} lost the placeholder`)
                .toContain('{streak}');
        }
    });

    it('has a stylesheet rule so the line is not unstyled text', () => {
        const css = fs.readFileSync(path.join(ROOT, 'www/css/styles.css'), 'utf8');
        expect(css).toContain('.streak-shield-used {');
        expect(css).toContain('.streak-shield-text {');
    });
});
