/**
 * Unit tests for the pure spectator-view render helpers extracted into
 * admin/sections/render-helpers.js (#1279, Schritt 4/6).
 *
 * Step 4 begins the View-Section split. These five helpers are the part of
 * admin.js that lifts out without touching the densely-shared setup state, so
 * unlike the deferred setup-sections they ARE cleanly unit-testable. The tests
 * import the real module (the same source esbuild bundles into admin.min.js)
 * and assert the observable DOM/string effects of one data payload each:
 *
 *   - renderAdminLeaderboard   — rank/score/streak/change markup + summary badge,
 *                                with HTML-escaped names.
 *   - renderAdminSubmissionDots — submitted/disconnected classes + steal/bet badges.
 *   - renderAdminResultCards   — score-class buckets, closest-winner badge, the
 *                                missed/exact/off accuracy label (i18n fallback).
 *   - renderAdminChallengeOptions — one read-only option per entry, escaped.
 *   - _providerDisplayName     — provider→label map, '' for unknown/empty.
 *
 * The vitest env is `node` (no jsdom), so a minimal fake `document` plus the
 * window globals these helpers read (`BeatifyUtils.escapeHtml`, `BeatifyI18n.t`)
 * are stubbed. The i18n stub returns the key so the helpers' own
 * `t(...) || 'literal'` fallbacks are exercised exactly as in production when a
 * key is missing.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
    renderAdminLeaderboard,
    renderAdminResultCards,
    renderAdminChallengeOptions,
    renderAdminSubmissionDots,
    _providerDisplayName,
} from '../admin/sections/render-helpers.js';

function realEscape(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

let els;
function makeEl() {
    return { innerHTML: '', textContent: '' };
}

beforeEach(() => {
    els = {};
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: realEscape };
    // i18n stub: return the key (so the helpers fall through to their `|| 'literal'`)
    globalThis.BeatifyI18n = { t: (k) => k };
    globalThis.document = {
        getElementById: (id) => (els[id] || (els[id] = makeEl())),
    };
});

afterEach(() => {
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    delete globalThis.document;
    delete globalThis.window;
});

describe('renderAdminLeaderboard', () => {
    it('renders rank, escaped name and score into the default targets', () => {
        renderAdminLeaderboard([{ rank: 1, name: '<b>Al</b>', score: 42, connected: true }]);
        const html = els['admin-playing-leaderboard-list'].innerHTML;
        expect(html).toContain('#1');
        expect(html).toContain('&lt;b&gt;Al&lt;/b&gt;'); // escaped, no raw <b>
        expect(html).not.toContain('<b>Al</b>');
        expect(html).toContain('42');
        // both default targets get the same html
        expect(els['admin-reveal-leaderboard'].innerHTML).toBe(html);
    });

    it('shows the streak indicator at >=2 and the hot variant at >=5', () => {
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, streak: 2 }]);
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('🔥2');
        expect(els['admin-playing-leaderboard-list'].innerHTML).not.toContain('streak-indicator--hot');
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, streak: 6 }]);
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('streak-indicator--hot');
    });

    it('renders up/down rank-change arrows', () => {
        renderAdminLeaderboard([{ rank: 2, name: 'A', score: 1, rank_change: 3 }]);
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('▲3');
        renderAdminLeaderboard([{ rank: 2, name: 'A', score: 1, rank_change: -2 }]);
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('▼2');
    });

    it('marks a disconnected entry with the away badge', () => {
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, connected: false }]);
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('away-badge');
        expect(els['admin-playing-leaderboard-list'].innerHTML).toContain('leaderboard-entry--disconnected');
    });

    it('writes the top-entry summary badge', () => {
        renderAdminLeaderboard([{ rank: 1, name: 'Winner', score: 99 }]);
        expect(els['admin-playing-leaderboard-summary'].textContent).toBe('Winner — 99');
    });

    it('honours an explicit containerId (single target only)', () => {
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1 }], 'admin-end-leaderboard');
        expect(els['admin-end-leaderboard'].innerHTML).toContain('#1');
        expect(els['admin-playing-leaderboard-list']).toBeUndefined();
    });

    it('is a no-op for a null leaderboard', () => {
        renderAdminLeaderboard(null);
        expect(els['admin-playing-leaderboard-list']).toBeUndefined();
    });
});

describe('renderAdminSubmissionDots', () => {
    it('flags submitted/disconnected and renders steal+bet badges, escaped name', () => {
        renderAdminSubmissionDots([
            { name: 'Bob', submitted: true, bet: true, steal_used: true },
            { name: '<x>', submitted: false, connected: false },
        ]);
        const html = els['admin-submitted-players'].innerHTML;
        expect(html).toContain('is-submitted');
        expect(html).toContain('player-indicator--disconnected');
        expect(html).toContain('player-badge--steal');
        expect(html).toContain('player-badge--bet');
        expect(html).toContain('&lt;x&gt;');
    });

    it('is a no-op when players is missing', () => {
        renderAdminSubmissionDots(undefined);
        // container resolves but is never written → stays empty
        expect(els['admin-submitted-players'].innerHTML).toBe('');
    });
});

describe('renderAdminResultCards', () => {
    it('renders nothing for an empty player list', () => {
        renderAdminResultCards([], false, 1999);
        expect(els['admin-reveal-guesses'].innerHTML).toBe('');
    });

    it('buckets score classes and shows the exact-guess label', () => {
        renderAdminResultCards([{ name: 'A', guess: 1999, years_off: 0, round_score: 10, missed_round: false }], false, 1999);
        const html = els['admin-reveal-guesses'].innerHTML;
        expect(html).toContain('is-score-high'); // >=10
        expect(html).toContain('reveal.exact');  // i18n key fallback for years_off===0
        expect(html).toContain('+10');
    });

    it('shows the Missed label and zero-score class for a missed round', () => {
        renderAdminResultCards([{ name: 'A', missed_round: true, round_score: 0 }], false, 2000);
        const html = els['admin-reveal-guesses'].innerHTML;
        expect(html).toContain('is-score-zero');
        expect(html).toContain('—'); // guess dash
        expect(html).toContain('reveal.noGuessShort');
    });

    it('awards the closest-winner badge in closest-wins mode', () => {
        renderAdminResultCards([
            { name: 'Near', years_off: 1, round_score: 5, missed_round: false },
            { name: 'Far', years_off: 9, round_score: 2, missed_round: false },
        ], true, 2000);
        const html = els['admin-reveal-guesses'].innerHTML;
        expect(html).toContain('closest-winner-badge');
        expect(html).toContain('is-closest-winner');
    });

    it('sorts cards by round_score descending', () => {
        renderAdminResultCards([
            { name: 'Low', round_score: 1, years_off: 5, missed_round: false },
            { name: 'High', round_score: 20, years_off: 0, missed_round: false },
        ], false, 2000);
        const html = els['admin-reveal-guesses'].innerHTML;
        expect(html.indexOf('High')).toBeLessThan(html.indexOf('Low'));
    });
});

describe('renderAdminChallengeOptions', () => {
    it('renders one read-only option per entry (string or object), escaped', () => {
        renderAdminChallengeOptions('opts', ['<A>', { label: 'B' }, { name: 'C' }]);
        const html = els['opts'].innerHTML;
        expect((html.match(/artist-option--readonly/g) || []).length).toBe(3);
        expect(html).toContain('&lt;A&gt;');
        expect(html).toContain('B');
        expect(html).toContain('C');
    });

    it('is a no-op when options is missing', () => {
        renderAdminChallengeOptions('opts', null);
        // container is created on lookup but never written
        expect(els['opts'].innerHTML).toBe('');
    });
});

describe('_providerDisplayName', () => {
    it('falls back to the hard label when no translation exists', () => {
        // Missing translation → t() returns falsy → helper uses its fallbackMap.
        // (Matches prod: `BeatifyI18n.t(key) || fallback` only falls through on a
        // falsy t(); a key-returning t() short-circuits to the key, as in step 2.)
        globalThis.BeatifyI18n = { t: () => '' };
        expect(_providerDisplayName('spotify')).toBe('Spotify');
        expect(_providerDisplayName('apple_music')).toBe('Apple Music');
        expect(_providerDisplayName('youtube_music')).toBe('YouTube Music');
        expect(_providerDisplayName('tidal')).toBe('Tidal');
        expect(_providerDisplayName('deezer')).toBe('Deezer');
    });

    it('returns the i18n value when a translation exists', () => {
        globalThis.BeatifyI18n = { t: () => 'Spotify Premium' };
        expect(_providerDisplayName('spotify')).toBe('Spotify Premium');
    });

    it('returns empty string for unknown or empty providers', () => {
        expect(_providerDisplayName('myspace')).toBe('');
        expect(_providerDisplayName('')).toBe('');
        expect(_providerDisplayName(null)).toBe('');
        expect(_providerDisplayName(undefined)).toBe('');
    });
});
