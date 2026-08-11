/**
 * Round-count helpers (#1475).
 *
 * The value under test is the one that decides how long someone's evening is,
 * and 0 vs 10 is the difference between "play everything" and "play a tenth of
 * it". Most of these cases exist to pin down that 0 stays 0 whenever the input
 * is anything other than a deliberate positive number.
 */

import { describe, test, expect } from 'vitest';
import {
    MIN_ROUNDS,
    ROUND_PRESETS,
    roundCountOptions,
    clampRoundCount,
    availableSongs,
    estimateGameMinutes,
} from '../round-count.js';

describe('roundCountOptions', () => {
    test('offers every preset plus All and Custom for a large pool', () => {
        const opts = roundCountOptions(100);
        expect(opts.map((o) => o.id)).toEqual([...ROUND_PRESETS, 0, 'custom']);
    });

    test('drops presets the selection cannot fill', () => {
        // 22 songs: "30" would be an offer the game cannot keep.
        expect(roundCountOptions(22).map((o) => o.id)).toEqual([10, 20, 0, 'custom']);
    });

    test('drops a preset equal to the pool — it is the same game as All', () => {
        expect(roundCountOptions(20).map((o) => o.id)).toEqual([10, 0, 'custom']);
    });

    test('keeps All and Custom even when no preset survives', () => {
        expect(roundCountOptions(6).map((o) => o.id)).toEqual([0, 'custom']);
    });

    test('unknown pool shows everything rather than hiding options', () => {
        // Before playlists are picked the pool is 0. Hiding presets there would
        // make the field look broken; the backend clamps anyway.
        expect(roundCountOptions(0).map((o) => o.id)).toEqual([...ROUND_PRESETS, 0, 'custom']);
    });
});

describe('clampRoundCount', () => {
    test('passes a sensible number through', () => {
        expect(clampRoundCount(25, 100)).toBe(25);
    });

    test('lifts anything below the floor to MIN_ROUNDS', () => {
        expect(clampRoundCount(3, 100)).toBe(MIN_ROUNDS);
        expect(clampRoundCount(1, 100)).toBe(MIN_ROUNDS);
    });

    test('a cap at or above the pool collapses to All', () => {
        expect(clampRoundCount(100, 100)).toBe(0);
        expect(clampRoundCount(500, 100)).toBe(0);
    });

    test('parses digit strings from the number input', () => {
        expect(clampRoundCount('25', 100)).toBe(25);
        expect(clampRoundCount('25.9', 100)).toBe(25);
    });

    test('non-numbers fall back to All, never to MIN_ROUNDS', () => {
        // A lost keystroke must not silently start a 10-round game.
        for (const bad of ['', '   ', 'abc', null, undefined, NaN, Infinity, -5, 0, {}]) {
            expect(clampRoundCount(bad, 100)).toBe(0);
        }
    });

    test('unknown pool still enforces the floor', () => {
        expect(clampRoundCount(4, 0)).toBe(MIN_ROUNDS);
        expect(clampRoundCount(4, undefined)).toBe(MIN_ROUNDS);
        expect(clampRoundCount(400, 0)).toBe(400);
    });

    test('a pool below the floor collapses to All', () => {
        // 6 songs cannot honour a 10-round minimum; play them all.
        expect(clampRoundCount(10, 6)).toBe(0);
    });
});

describe('availableSongs', () => {
    const playlists = [
        { path: 'a.json', song_count: 40 },
        { path: 'b.json', song_count: 60 },
        { filename: 'c.json', song_count: 5 },
        { path: 'd.json' },
    ];

    test('sums the selected playlists', () => {
        expect(availableSongs(['a.json', 'b.json'], playlists)).toBe(100);
    });

    test('matches on filename when path is absent', () => {
        expect(availableSongs(['c.json'], playlists)).toBe(5);
    });

    test('a playlist without a count contributes 0 instead of NaN', () => {
        expect(availableSongs(['a.json', 'd.json'], playlists)).toBe(40);
    });

    test('unknown paths and bad arguments give 0', () => {
        expect(availableSongs(['nope.json'], playlists)).toBe(0);
        expect(availableSongs(null, playlists)).toBe(0);
        expect(availableSongs(['a.json'], null)).toBe(0);
    });
});

describe('estimateGameMinutes', () => {
    test('counts the reveal, not just the guessing timer', () => {
        // 20 rounds x (30s guess + 20s reveal) = 1000s ≈ 17 min
        expect(estimateGameMinutes(20, 30)).toBe(17);
    });

    test('never claims a game takes 0 minutes', () => {
        expect(estimateGameMinutes(1, 15)).toBe(1);
    });

    test('0 rounds means "unknown", which the UI renders as no hint', () => {
        expect(estimateGameMinutes(0, 30)).toBe(0);
    });

    test('falls back to the default timer when duration is missing', () => {
        expect(estimateGameMinutes(10, undefined)).toBe(estimateGameMinutes(10, 30));
    });
});
