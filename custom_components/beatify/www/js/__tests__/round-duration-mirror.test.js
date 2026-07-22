/**
 * The round-duration bounds in `admin/util.js` claim to mirror `const.py`.
 * Nothing enforced that claim, and they had already drifted: JS shipped
 * `ROUND_DURATION_MIN = 10` against Python's 15, so 10–14 passed
 * `normalizeRoundDuration` and were then rejected by the server with a 400.
 *
 * These tests parse the Python source rather than restating the numbers, so a
 * change on either side that is not mirrored on the other fails here instead of
 * at runtime. Restating them would only pin today's values and would have to be
 * edited in lockstep — which is the thing that was not happening.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
    ROUND_DURATION_MIN,
    ROUND_DURATION_MAX,
    DEFAULT_ROUND_DURATION,
    normalizeRoundDuration,
} from '../admin/util.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONST_PY = readFileSync(
    join(__dirname, '..', '..', '..', 'const.py'),
    'utf8',
);

/**
 * Read a top-level `NAME = <int>` assignment out of const.py.
 *
 * Anchored to the start of a line so an indented occurrence inside a function
 * or a docstring mention cannot be picked up instead of the real constant.
 */
function pyInt(name) {
    const m = new RegExp(`^${name}\\s*=\\s*(\\d+)`, 'm').exec(CONST_PY);
    if (!m) throw new Error(`${name} not found in const.py`);
    return Number(m[1]);
}

describe('round-duration bounds mirror const.py', () => {
    it('finds the Python constants at all', () => {
        // Guards the parser itself: if const.py is renamed or the constants are
        // restructured, this fails loudly instead of the assertions below
        // silently comparing against a throw.
        expect(pyInt('ROUND_DURATION_MIN')).toBeGreaterThan(0);
        expect(pyInt('ROUND_DURATION_MAX')).toBeGreaterThan(0);
        expect(pyInt('DEFAULT_ROUND_DURATION')).toBeGreaterThan(0);
    });

    it('mirrors ROUND_DURATION_MIN', () => {
        expect(ROUND_DURATION_MIN).toBe(pyInt('ROUND_DURATION_MIN'));
    });

    it('mirrors ROUND_DURATION_MAX', () => {
        expect(ROUND_DURATION_MAX).toBe(pyInt('ROUND_DURATION_MAX'));
    });

    it('mirrors DEFAULT_ROUND_DURATION', () => {
        expect(DEFAULT_ROUND_DURATION).toBe(pyInt('DEFAULT_ROUND_DURATION'));
    });

    it('keeps the default inside the range both sides accept', () => {
        expect(DEFAULT_ROUND_DURATION).toBeGreaterThanOrEqual(ROUND_DURATION_MIN);
        expect(DEFAULT_ROUND_DURATION).toBeLessThanOrEqual(ROUND_DURATION_MAX);
    });
});

describe('normalizeRoundDuration rejects what the server rejects', () => {
    it('rejects the band that used to pass the client and 400 at the server', () => {
        // The concrete regression: with MIN=10 these normalised happily.
        for (const seconds of [10, 11, 12, 13, 14]) {
            expect(normalizeRoundDuration(seconds)).toBeNull();
        }
    });

    it('still accepts the lowest value the server accepts', () => {
        expect(normalizeRoundDuration(ROUND_DURATION_MIN)).toBe(ROUND_DURATION_MIN);
    });

    it('accepts every duration the wizard offers', () => {
        // admin.html renders chips for 30 / 45 / 60. Tightening MIN must not
        // make a value the UI can produce unusable.
        for (const seconds of [30, 45, 60]) {
            expect(normalizeRoundDuration(seconds)).toBe(seconds);
        }
    });
});
