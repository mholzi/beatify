/**
 * #1867 — the round duration the lobby advertises must be the one start-game sends.
 *
 * Reported symptom: the wizard persisted 45, the lobby chip rendered "45S", and
 * the server ran every round on a 30.0s timer. The chip and the start-game
 * payload read two different sources, so a mismatch was invisible.
 *
 * These tests pin the two halves of the fix: a normalizer that refuses to
 * invent a value, and a chip that renders the value that will actually be sent.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import {
    normalizeRoundDuration,
    applyStoredGameSettings,
    ROUND_DURATION_MIN,
    ROUND_DURATION_MAX,
    DEFAULT_ROUND_DURATION,
} from '../admin/util.js';

describe('normalizeRoundDuration', () => {
    it('passes through valid integers', () => {
        expect(normalizeRoundDuration(30)).toBe(30);
        expect(normalizeRoundDuration(45)).toBe(45);
        expect(normalizeRoundDuration(ROUND_DURATION_MIN)).toBe(ROUND_DURATION_MIN);
        expect(normalizeRoundDuration(ROUND_DURATION_MAX)).toBe(ROUND_DURATION_MAX);
    });

    it('coerces numeric strings — an older build stored them that way', () => {
        expect(normalizeRoundDuration('45')).toBe(45);
        expect(normalizeRoundDuration(' 30 ')).toBe(30);
    });

    it('rounds fractional input to whole seconds', () => {
        expect(normalizeRoundDuration(44.6)).toBe(45);
    });

    it('returns null rather than substituting a different valid value', () => {
        // This is the whole point. The removed flat-admin setTimerDuration
        // clamped every one of these to exactly 30, which is how a game could
        // run a duration nobody picked.
        for (const bad of ['', '  ', 'abc', null, undefined, NaN, Infinity, {}, [], true]) {
            expect(normalizeRoundDuration(bad)).toBeNull();
        }
    });

    it('returns null outside the range the server accepts', () => {
        expect(normalizeRoundDuration(ROUND_DURATION_MIN - 1)).toBeNull();
        expect(normalizeRoundDuration(ROUND_DURATION_MAX + 1)).toBeNull();
        expect(normalizeRoundDuration(0)).toBeNull();
        expect(normalizeRoundDuration(-45)).toBeNull();
    });
});

describe('applyStoredGameSettings — duration hydration (#1867)', () => {
    let adminState;

    beforeEach(() => {
        adminState = { selectedDuration: DEFAULT_ROUND_DURATION };
    });

    it('hydrates a stored duration', () => {
        applyStoredGameSettings(adminState, { duration: 30 });
        expect(adminState.selectedDuration).toBe(30);
    });

    it('hydrates a stored duration that was saved as a string', () => {
        applyStoredGameSettings(adminState, { duration: '30' });
        expect(adminState.selectedDuration).toBe(30);
        expect(typeof adminState.selectedDuration).toBe('number');
    });

    it('keeps the current value when the stored one is unusable', () => {
        for (const bad of [{ duration: 'abc' }, { duration: 999 }, { duration: 0 }, {}]) {
            adminState.selectedDuration = 45;
            applyStoredGameSettings(adminState, bad);
            expect(adminState.selectedDuration).toBe(45);
        }
    });
});

describe('lobby chip and start-game payload agree (#1867)', () => {
    // The chip is built inline in admin.js's home view; this reproduces the
    // expression under test rather than importing the whole admin bundle.
    const renderChip = (stored, adminState) =>
        `${stored.difficulty || 'normal'} · ${adminState.selectedDuration}s · ${(stored.language || 'en').toUpperCase()}`;
    const startPayload = (adminState) => ({ round_duration: adminState.selectedDuration });

    it('agree after normal hydration', () => {
        const stored = { duration: 45, difficulty: 'normal', language: 'de' };
        const adminState = { selectedDuration: DEFAULT_ROUND_DURATION };
        applyStoredGameSettings(adminState, stored);

        expect(renderChip(stored, adminState)).toContain('45s');
        expect(startPayload(adminState).round_duration).toBe(45);
    });

    it('agree even when hydration never ran — the reported failure mode', () => {
        // The stored blob says 45 but adminState was never hydrated from it.
        // Before the fix the chip read the blob (45) and the payload read
        // adminState, so the two could disagree with nothing to see. Now both
        // read adminState: the chip may be "wrong" versus the blob, but it is
        // honest about what the server will be told.
        const stored = { duration: 45, difficulty: 'normal', language: 'de' };
        const adminState = { selectedDuration: 30 };

        expect(renderChip(stored, adminState)).toContain('30s');
        expect(startPayload(adminState).round_duration).toBe(30);
    });
});
