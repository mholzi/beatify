/**
 * #3605 — Title & Artist: the TV "Top Guesses" list ranked every player with
 * "+0" in rounds nobody got anything right. It now lists scorers only and hides
 * the heading when there are none; year mode is unchanged.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const SRC = readSource('dashboard.js');

function run(players, taMode) {
    const heading = el('h');
    heading.classList.add('top-guesses-title');
    const list = el('l');
    list.previousElementSibling = heading;
    const d = doc({ 'reveal-top-guesses-list': list });
    const fn = evaluate([declaration(SRC, 'renderTopGuesses')], 'renderTopGuesses', {
        document: d,
        utils: { escapeHtml: (s) => String(s) },
    });
    fn(players, taMode);
    return { heading, list };
}

describe('#3605 renderTopGuesses', () => {
    const zero = [{ name: 'A', round_score: 0 }, { name: 'B', round_score: 0 }];

    it('TA mode, nobody scored: empty list and hidden heading', () => {
        const { heading, list } = run(zero, true);
        expect(list.innerHTML).toBe('');
        expect(heading.classList.contains('hidden')).toBe(true);
    });

    it('TA mode lists scorers only', () => {
        const { list } = run([...zero, { name: 'C', round_score: 10 }], true);
        expect(list.innerHTML).toContain('C');
        expect(list.innerHTML).not.toContain('>A<');
    });

    it('year mode still lists zero-point guessers', () => {
        const { list, heading } = run(zero, false);
        expect(list.innerHTML).toContain('A');
        expect(heading.classList.contains('hidden')).toBe(false);
    });
});
