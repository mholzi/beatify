/**
 * Tests for the Title & Artist presentation helpers in utils.js (#1180).
 *
 * utils.js is a classic global IIFE (window.BeatifyUtils = (...)()), shared by
 * the spectator dashboard (an IIFE that can't be imported directly). These pure
 * helpers back the TV live-vote tally bars and the resolved verdict chips, so
 * unit-testing them covers the TV path's logic without a dashboard refactor.
 */
import { describe, it, expect } from 'vitest';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

describe('BeatifyUtils.taVerdictLabel (#1180)', () => {
    it('shows ✓ +points when accepted', () => {
        expect(U.taVerdictLabel(true, 5)).toBe('✓ +5');
        expect(U.taVerdictLabel(true, 3)).toBe('✓ +3');
    });

    it('shows ✗ when rejected (points ignored)', () => {
        expect(U.taVerdictLabel(false, 5)).toBe('✗');
        expect(U.taVerdictLabel(false, 0)).toBe('✗');
    });

    it('defaults missing points to 0', () => {
        expect(U.taVerdictLabel(true)).toBe('✓ +0');
    });
});

describe('BeatifyUtils.taTallyPercents (#1180)', () => {
    it('splits cast votes to integer percentages summing to 100', () => {
        expect(U.taTallyPercents(3, 1)).toEqual({ yes: 75, no: 25 });
        expect(U.taTallyPercents(1, 2)).toEqual({ yes: 33, no: 67 });
        expect(U.taTallyPercents(1, 0)).toEqual({ yes: 100, no: 0 });
    });

    it('returns 0/0 when no votes are cast', () => {
        expect(U.taTallyPercents(0, 0)).toEqual({ yes: 0, no: 0 });
        expect(U.taTallyPercents()).toEqual({ yes: 0, no: 0 });
    });
});
