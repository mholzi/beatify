/**
 * #2625 — the difficulty hint must be a reading of the scoring table, not a
 * second copy of it.
 *
 * `const.py` holds `DIFFICULTY_SCORING`; the wizard restated it in prose under a
 * "keep in sync" comment, and the admin panel restated it again in three
 * languages. The admin copy had already drifted: it promised "Hard: only close
 * guesses score" where the code pays 3 points within ±2 years.
 *
 * The tests below deliberately do NOT check today's sentence. They change the
 * table and require the sentence to change with it — the property that was
 * missing. A test pinning "5 pts within ±7 years" would pass just as happily
 * with the prose back in place.
 */
import { describe, it, expect, afterEach } from 'vitest';

import {
    DIFFICULTY_SCORING,
    POINTS_EXACT,
    difficultyHint,
} from '../game-constants.js';

/** English-fallback translator with `{placeholder}` interpolation. */
const t = (_key, fallback, params) => {
    if (!params) return fallback;
    return Object.keys(params).reduce(
        (out, name) => out.replace(new RegExp(`\\{${name}\\}`, 'g'), params[name]),
        fallback,
    );
};

/** The numbers the finished sentence puts in front of the host. */
function numbersIn(text) {
    return [...text.matchAll(/\d+/g)].map(([n]) => Number(n));
}

/** Run `fn` against a temporarily altered scoring row, then restore it. */
function withScoring(level, patch, fn) {
    const original = { ...DIFFICULTY_SCORING[level] };
    Object.assign(DIFFICULTY_SCORING[level], patch);
    try {
        return fn();
    } finally {
        Object.assign(DIFFICULTY_SCORING[level], original);
    }
}

afterEach(() => {
    // Belt and braces: every helper above restores its own row, but a failed
    // assertion inside `fn` must not leak a patched table into the next test.
    expect(Object.keys(DIFFICULTY_SCORING)).toEqual(['easy', 'normal', 'hard']);
});

describe('the hint states the numbers the code actually pays', () => {
    for (const level of ['easy', 'normal', 'hard']) {
        it(`quotes every band of "${level}" and invents nothing`, () => {
            const scoring = DIFFICULTY_SCORING[level];
            const shown = numbersIn(difficultyHint(level, t));
            const expected = scoring.near_range > 0
                ? [POINTS_EXACT, scoring.close_points, scoring.close_range,
                    scoring.near_points, scoring.near_range]
                : [POINTS_EXACT, scoring.close_points, scoring.close_range, 0];
            expect(shown).toEqual(expected);
        });
    }
});

describe('tuning the table moves the text', () => {
    it('follows a changed close_points', () => {
        const before = difficultyHint('normal', t);
        const after = withScoring('normal', { close_points: 8 }, () => difficultyHint('normal', t));
        expect(after).not.toBe(before);
        expect(numbersIn(after)).toContain(8);
    });

    it('follows a changed near_range', () => {
        const after = withScoring('easy', { near_range: 14 }, () => difficultyHint('easy', t));
        expect(numbersIn(after)).toContain(14);
    });

    it('grows a near clause when a level gains one', () => {
        // This is the drift the admin string was made of: "hard" gaining a near
        // band would have left "only close guesses score" on screen forever.
        const before = difficultyHint('hard', t);
        const after = withScoring('hard', { near_range: 4, near_points: 1 }, () =>
            difficultyHint('hard', t));
        expect(before).toMatch(/otherwise 0/);
        expect(after).not.toMatch(/otherwise 0/);
        expect(numbersIn(after)).toEqual([POINTS_EXACT, 3, 2, 1, 4]);
    });

    it('drops the near clause when a level loses one', () => {
        const after = withScoring('normal', { near_range: 0, near_points: 0 }, () =>
            difficultyHint('normal', t));
        expect(after).toMatch(/otherwise 0/);
        expect(numbersIn(after)).toEqual([POINTS_EXACT, 5, 3, 0]);
    });
});

describe('the shape of the hint', () => {
    it('reads as one finished sentence, not a template', () => {
        for (const level of ['easy', 'normal', 'hard']) {
            const hint = difficultyHint(level, t);
            expect(hint).not.toMatch(/[{}]/);
            expect(hint.endsWith('.')).toBe(true);
        }
    });

    it('gives the three levels three different sentences', () => {
        const hints = ['easy', 'normal', 'hard'].map((l) => difficultyHint(l, t));
        expect(new Set(hints).size).toBe(3);
    });

    it('falls back to the default level for an unknown difficulty', () => {
        expect(difficultyHint('brutal', t)).toBe(difficultyHint('normal', t));
        expect(difficultyHint(undefined, t)).toBe(difficultyHint('normal', t));
    });

    it('asks for the same keys the wizard and the admin panel both use', () => {
        // Both surfaces call this one function, so "the admin text agrees with
        // the wizard text" is true by construction rather than by review.
        const seen = [];
        difficultyHint('easy', (key, fallback, params) => {
            seen.push(key);
            return t(key, fallback, params);
        });
        expect(seen).toEqual([
            'wizard.step4.difficultyBands',
            'wizard.step4.difficultyHintEasy',
        ]);
    });
});
