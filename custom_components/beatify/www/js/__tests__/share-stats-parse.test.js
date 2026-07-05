/**
 * #1664 item 3: structured parse of the emoji share grid (parseShareStats).
 *
 * The vinyl share card used to regex-scrape name/score/stats out of the grid
 * text in the middle of the canvas draw. This locks the extracted parser so the
 * known layout from game/share.py::build_emoji_grid stays covered and edge cases
 * (missing lines, empty input) degrade to blank fields instead of throwing.
 */
import { describe, it, expect, vi } from 'vitest';

global.window = { BeatifyUtils: {} };
global.document = { getElementById: () => null };

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

const { parseShareStats } = await import('../player-end.js');

// Mirrors game/share.py::build_emoji_grid output exactly.
function makeGrid() {
    return [
        '🎵 Beatify — Summer Hits',
        '👑 Alice: 42pts',
        '',
        '🟣🟢🟡🔴🟢',
        '  3/5 correct | 🔥 Best Streak: 4',
        '',
        '🎯 2 Exact | 💰 1/3 Bets',
        '',
        'beatify.fun',
    ].join('\n');
}

describe('parseShareStats (#1664)', () => {
    it('extracts name, score, correct, streak, exact from a well-formed grid', () => {
        expect(parseShareStats(makeGrid())).toEqual({
            playerName: 'Alice',
            score: '42',
            isWinner: true,
            correct: '3/5',
            exact: '2',
            streak: '4',
        });
    });

    it('handles names containing spaces', () => {
        const grid = makeGrid().replace('👑 Alice: 42pts', '👑 Bob the DJ: 7pts');
        const s = parseShareStats(grid);
        expect(s.playerName).toBe('Bob the DJ');
        expect(s.score).toBe('7');
    });

    it('returns blank fields (no throw) for empty / bad input', () => {
        const blank = { playerName: '', score: '', isWinner: false, correct: '', exact: '', streak: '' };
        expect(parseShareStats('')).toEqual(blank);
        expect(parseShareStats(null)).toEqual(blank);
        expect(parseShareStats(undefined)).toEqual(blank);
    });

    it('tolerates a partial grid (only the player line present)', () => {
        const s = parseShareStats('👑 Zoe: 10pts');
        expect(s.playerName).toBe('Zoe');
        expect(s.score).toBe('10');
        expect(s.correct).toBe('');
        expect(s.exact).toBe('');
        expect(s.streak).toBe('');
    });
});
