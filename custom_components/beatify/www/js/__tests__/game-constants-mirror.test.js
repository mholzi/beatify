/**
 * `www/js/game-constants.js` claims to mirror `custom_components/beatify/const.py`.
 * This is what enforces the claim.
 *
 * Three separate values had each grown a second (or fifth) home before #2625,
 * #2626 and #2627: the name cap, the auto-advance delays, and the difficulty
 * scoring table. Crossing the Python/JS boundary means one of the two sides has
 * to be a copy — so the copy is parsed out of the Python source and compared,
 * exactly like `round-duration-mirror.test.js` already does for the round
 * bounds. Restating the numbers here instead would only pin today's values and
 * would itself have to be edited in lockstep, which is the thing that was not
 * happening.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
    MAX_NAME_LENGTH,
    VOID_ROUND_REASONS,
    SUDDEN_DEATH_MIN_PLAYERS,
    REACTION_THROTTLE_SECONDS,
    REVEAL_AUTO_ADVANCE_OPTIONS,
    POINTS_EXACT,
    POINTS_WRONG,
    DIFFICULTY_DEFAULT,
    DIFFICULTY_SCORING,
} from '../game-constants.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONST_PY = readFileSync(join(__dirname, '..', '..', '..', 'const.py'), 'utf8');

/** Read a top-level `NAME = <int>` assignment out of const.py. */
function pyInt(name) {
    const m = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*(-?\\d+)`, 'm').exec(CONST_PY);
    if (!m) throw new Error(`${name} not found in const.py`);
    return Number(m[1]);
}

/** Read a top-level `NAME = "..."` assignment, following one level of alias. */
function pyStr(name) {
    const direct = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*['"]([^'"]+)['"]`, 'm').exec(CONST_PY);
    if (direct) return direct[1];
    const alias = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*([A-Z_][A-Z0-9_]*)`, 'm').exec(CONST_PY);
    if (!alias) throw new Error(`${name} not found in const.py`);
    return pyStr(alias[1]);
}

/** Read a top-level `NAME = (1, 2, 3)` / `[1, 2, 3]` of ints. */
function pyIntSeq(name) {
    const m = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*[([]([^)\\]]*)[)\\]]`, 'm').exec(CONST_PY);
    if (!m) throw new Error(`${name} not found in const.py`);
    return m[1]
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part.length > 0)
        .map(Number);
}

/** Read a top-level `NAME = ("a", "b")` / `["a", "b"]` of strings. */
function pyStrSeq(name) {
    const m = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*[([]([^)\\]]*)[)\\]]`, 'm').exec(CONST_PY);
    if (!m) throw new Error(`${name} not found in const.py`);
    return [...m[1].matchAll(/['"]([^'"]+)['"]/g)].map((hit) => hit[1]);
}

/**
 * Read `DIFFICULTY_SCORING` out of const.py as `{ level: { field: int } }`.
 *
 * The levels are keyed by the DIFFICULTY_* aliases (`DIFFICULTY_EASY: {...}`),
 * so each alias is resolved to the string it holds — that way renaming the
 * alias without touching its value keeps this passing, and changing the value
 * fails here rather than at runtime.
 */
function pyDifficultyScoring() {
    const block = /^DIFFICULTY_SCORING[^=]*=\s*\{([\s\S]*?)^\}/m.exec(CONST_PY);
    if (!block) throw new Error('DIFFICULTY_SCORING not found in const.py');
    const table = {};
    const entry = /(DIFFICULTY_[A-Z]+|"[a-z]+"):\s*\{([\s\S]*?)\}/g;
    let m;
    while ((m = entry.exec(block[1])) !== null) {
        const level = m[1].startsWith('"') ? m[1].slice(1, -1) : pyStr(m[1]);
        const fields = {};
        const field = /"([a-z_]+)":\s*(-?\d+)/g;
        let f;
        while ((f = field.exec(m[2])) !== null) fields[f[1]] = Number(f[2]);
        table[level] = fields;
    }
    return table;
}

describe('the parser finds the Python constants at all', () => {
    // Guards the guard: a renamed constant or a restructured table would
    // otherwise make every assertion below compare against a throw.
    it('finds every constant it is about to compare', () => {
        expect(pyInt('MAX_NAME_LENGTH')).toBeGreaterThan(0);
        expect(pyInt('SUDDEN_DEATH_MIN_PLAYERS')).toBeGreaterThan(0);
        expect(pyInt('REACTION_THROTTLE_SECONDS')).toBeGreaterThan(0);
        expect(pyInt('POINTS_EXACT')).toBeGreaterThan(0);
        expect(pyIntSeq('REVEAL_AUTO_ADVANCE_OPTIONS').length).toBeGreaterThan(1);
        expect(pyStrSeq('VOID_ROUND_REASONS').length).toBeGreaterThan(1);
        expect(Object.keys(pyDifficultyScoring())).toHaveLength(3);
    });
});

describe('game-constants.js mirrors const.py', () => {
    it('mirrors MAX_NAME_LENGTH (#2627)', () => {
        expect(MAX_NAME_LENGTH).toBe(pyInt('MAX_NAME_LENGTH'));
    });

    it('mirrors SUDDEN_DEATH_MIN_PLAYERS (#2699)', () => {
        expect(SUDDEN_DEATH_MIN_PLAYERS).toBe(pyInt('SUDDEN_DEATH_MIN_PLAYERS'));
    });

    it('mirrors REACTION_THROTTLE_SECONDS (#2562)', () => {
        expect(REACTION_THROTTLE_SECONDS).toBe(pyInt('REACTION_THROTTLE_SECONDS'));
    });

    it('mirrors REVEAL_AUTO_ADVANCE_OPTIONS (#2626)', () => {
        expect(REVEAL_AUTO_ADVANCE_OPTIONS).toEqual(pyIntSeq('REVEAL_AUTO_ADVANCE_OPTIONS'));
    });

    it('mirrors VOID_ROUND_REASONS (#2646)', () => {
        expect(VOID_ROUND_REASONS).toEqual(pyStrSeq('VOID_ROUND_REASONS'));
    });

    it('mirrors POINTS_EXACT / POINTS_WRONG (#2625)', () => {
        expect(POINTS_EXACT).toBe(pyInt('POINTS_EXACT'));
        expect(POINTS_WRONG).toBe(pyInt('POINTS_WRONG'));
    });

    it('mirrors DIFFICULTY_DEFAULT', () => {
        expect(DIFFICULTY_DEFAULT).toBe(pyStr('DIFFICULTY_DEFAULT'));
    });

    it('mirrors the whole DIFFICULTY_SCORING table (#2625)', () => {
        expect(DIFFICULTY_SCORING).toEqual(pyDifficultyScoring());
    });

    it('offers "off" as an auto-advance choice and nothing negative', () => {
        // The server treats 0 as "off" and every UI renders index 0 first.
        expect(REVEAL_AUTO_ADVANCE_OPTIONS[0]).toBe(0);
        for (const seconds of REVEAL_AUTO_ADVANCE_OPTIONS) {
            expect(seconds).toBeGreaterThanOrEqual(0);
        }
    });

    it('has a scoring row for the default difficulty', () => {
        expect(DIFFICULTY_SCORING[DIFFICULTY_DEFAULT]).toBeDefined();
    });
});
