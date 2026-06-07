/**
 * Regression test for the Title & Artist "Crowd Court" voted state (#1180, #1243).
 *
 * Two halves of the fix are covered:
 *  1. setupTitleArtistVoting records the player's own 👍/👎 into state.taMyVotes
 *     when a vote button is clicked.
 *  2. renderTitleArtistReveal restores that voted state on every re-render
 *     (chosen button lit + ✓, other dimmed, "tap to change" caption) — the
 *     server only broadcasts aggregate tallies, so before the fix the optimistic
 *     highlight was wiped on the next innerHTML rebuild. A new song resets it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// vitest runs in node env — stub browser globals BEFORE importing the module
// so its top-level `var utils = window.BeatifyUtils || {};` doesn't throw.
global.window = {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.WebSocket = { OPEN: 1 };

// Minimal element stub: classList + innerHTML + the bits the countdown touches.
function makeEl() {
    const classes = new Set();
    return {
        innerHTML: '',
        textContent: '',
        style: { setProperty: () => {} },
        setAttribute: () => {},
        removeAttribute: () => {},
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
    };
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
};

const mockState = { lastRevealContext: null, playerName: null, taMyVotes: undefined };
vi.mock('../player-utils.js', () => ({
    state: mockState,
    escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    animateScoreChange: () => {},
    showPointsPopup: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    isStreakMilestone: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const { renderTitleArtistReveal, setupTitleArtistVoting } = await import('../player-reveal.js');

// A REVEAL-shape title_artist_challenge with one OTHER player's near-miss.
function makeTa(overrides = {}) {
    return {
        correct_title: 'Bohemian Rhapsody',
        correct_artist: 'Queen',
        results: [{ player: 'Alice', title: 'Bohemian Rhapsody', title_status: 'exact' }],
        near_misses: [
            { id: 'Mia:title', player: 'Mia', field: 'title', guess: 'Bohem Rapsody', votes_yes: 2, votes_no: 1 },
        ],
        voting_open: true,
        ...overrides,
    };
}

describe('Title & Artist voted state persistence (#1180, #1243)', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        els = {
            'ta-reveal-section': makeEl(),
            'ta-reveal-truth': makeEl(),
            'ta-reveal-own': makeEl(),
            'ta-voting': makeEl(),
            'ta-voting-cards': makeEl(),
            'ta-voting-countdown': makeEl(),
        };
        mockState.playerName = 'Alice';
        mockState.lastRevealContext = { revealStartedAt: 1_000_000 };
        mockState.taMyVotes = undefined;
        mockState._taRevealTruth = undefined;
    });

    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
    });

    it('shows a "Wrong" pill for a wrong own result, not "Skipped"', () => {
        // A wrong-but-typed guess must read as Wrong (red), never Skipped.
        const ta = makeTa({ results: [
            { player: 'Alice', title: 'Beatles', artist: 'Beatles', title_status: 'wrong', artist_status: 'wrong' },
        ] });
        renderTitleArtistReveal(ta, { is_admin: false });
        const own = els['ta-reveal-own'].innerHTML;
        expect(own).toContain('ta-pill--wrong');
        expect(own).toContain('titleArtist.statusWrong');
        expect(own).not.toContain('ta-pill--skipped');
    });

    it('renders fresh vote buttons with no voted markup before the player votes', () => {
        renderTitleArtistReveal(makeTa(), { is_admin: false });
        const html = els['ta-voting-cards'].innerHTML;
        expect(html).toContain('ta-vote-btn--yes');
        expect(html).toContain('ta-vote-btn--no');
        expect(html).not.toContain('ta-vote-actions--voted');
        expect(html).not.toContain('is-chosen');
        expect(html).not.toContain('ta-voted-caption');
    });

    it('restores the voted state on re-render (the regression)', () => {
        // 1) First broadcast: fresh render establishes the round.
        renderTitleArtistReveal(makeTa(), { is_admin: false });
        // 2) Player votes 👍 (the handler writes this; simulated here).
        mockState.taMyVotes['Mia:title'] = true;
        // 3) Next broadcast re-renders the same song with an updated tally.
        renderTitleArtistReveal(makeTa({ near_misses: [
            { id: 'Mia:title', player: 'Mia', field: 'title', guess: 'Bohem Rapsody', votes_yes: 3, votes_no: 1 },
        ] }), { is_admin: false });

        const html = els['ta-voting-cards'].innerHTML;
        expect(html).toContain('ta-vote-actions--voted');
        // The yes button is the chosen one, not the no button.
        expect(html).toMatch(/ta-vote-btn--yes is-chosen/);
        expect(html).not.toMatch(/ta-vote-btn--no is-chosen/);
        expect(html).toContain('ta-voted-caption');
        expect(html).toContain('👍');
    });

    it('marks the 👎 button when the player voted no', () => {
        renderTitleArtistReveal(makeTa(), { is_admin: false });
        mockState.taMyVotes['Mia:title'] = false;
        renderTitleArtistReveal(makeTa(), { is_admin: false });

        const html = els['ta-voting-cards'].innerHTML;
        expect(html).toMatch(/ta-vote-btn--no is-chosen/);
        expect(html).not.toMatch(/ta-vote-btn--yes is-chosen/);
    });

    it('resets the vote memory when a new song is revealed', () => {
        renderTitleArtistReveal(makeTa(), { is_admin: false });
        mockState.taMyVotes['Mia:title'] = true;
        renderTitleArtistReveal(makeTa(), { is_admin: false });
        expect(els['ta-voting-cards'].innerHTML).toContain('ta-vote-actions--voted');

        // New round: different correct_title. Same near-miss id can recur, but
        // it's a brand-new vote opportunity — the prior choice must clear.
        renderTitleArtistReveal(
            makeTa({ correct_title: 'Africa', correct_artist: 'Toto' }),
            { is_admin: false }
        );
        const html = els['ta-voting-cards'].innerHTML;
        expect(html).not.toContain('ta-vote-actions--voted');
        expect(html).not.toContain('is-chosen');
        expect(mockState.taMyVotes['Mia:title']).toBeUndefined();
    });
});

describe('setupTitleArtistVoting records the vote (#1243)', () => {
    let handler;
    let sentMessages;

    beforeEach(() => {
        sentMessages = [];
        handler = null;
        mockState.taMyVotes = undefined;
        mockState.ws = { readyState: 1, send: (m) => sentMessages.push(JSON.parse(m)) };

        // cardsEl captures the delegated click handler so the test can fire it.
        const cardsEl = {
            addEventListener: (_evt, fn) => { handler = fn; },
        };
        els = { 'ta-voting-cards': cardsEl };
    });

    function fireVote(nearmissId, accept) {
        const card = {
            querySelector: () => ({ classList: { add: () => {} } }),
            querySelectorAll: () => [],
        };
        const btn = {
            getAttribute: (a) => (a === 'data-nearmiss-id' ? nearmissId : accept ? '1' : '0'),
            closest: (sel) => (sel === '.ta-vote-btn' ? btn : sel === '.ta-vote-card' ? card : null),
            classList: { add: () => {}, remove: () => {} },
        };
        handler({ target: { closest: (sel) => (sel === '.ta-vote-btn' ? btn : null) } });
    }

    it('writes the choice into state.taMyVotes and sends the vote', () => {
        setupTitleArtistVoting();
        expect(handler).toBeTypeOf('function');

        fireVote('Mia:title', true);
        expect(mockState.taMyVotes['Mia:title']).toBe(true);
        expect(sentMessages).toEqual([
            { type: 'title_artist_vote', nearmiss_id: 'Mia:title', accept: true },
        ]);

        // Changing the vote overwrites the stored choice (last vote wins).
        fireVote('Mia:title', false);
        expect(mockState.taMyVotes['Mia:title']).toBe(false);
    });
});

describe('Title & Artist resolution moment (#1243)', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        els = {
            'ta-reveal-section': makeEl(),
            'ta-reveal-truth': makeEl(),
            'ta-reveal-own': makeEl(),
            'ta-voting': makeEl(),
            'ta-voting-title': makeEl(),
            'ta-voting-cards': makeEl(),
            'ta-voting-countdown': makeEl(),
        };
        mockState.playerName = 'Alice';
        mockState.lastRevealContext = { revealStartedAt: 1_000_000 };
        mockState.taMyVotes = undefined;
        mockState._taRevealTruth = undefined;
    });

    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
    });

    function resolvedTa() {
        return {
            correct_title: 'Bohemian Rhapsody',
            correct_artist: 'Queen',
            results: [],
            near_misses: [],
            voting_open: false,
            near_miss_outcomes: [
                { id: 'Mia:title', player: 'Mia', field: 'title', guess: 'Bohem Rapsody', votes_yes: 2, votes_no: 1, accepted: true, points: 5 },
                { id: 'Sam:artist', player: 'Sam', field: 'artist', guess: 'that band', votes_yes: 0, votes_no: 4, accepted: false, points: 0 },
            ],
        };
    }

    it('renders accepted ✓ +points and rejected ✗ outcome cards', () => {
        renderTitleArtistReveal(resolvedTa(), { is_admin: false });
        const html = els['ta-voting-cards'].innerHTML;

        expect(html).toContain('ta-outcome-card--accepted');
        expect(html).toContain('ta-outcome-card--rejected');
        expect(html).toContain('✓ +5');
        expect(html).toContain('✗');
        // Final tallies are shown on the verdict cards.
        expect(html).toContain('👍 2 · 👎 1');
        // No live vote buttons in the decided view.
        expect(html).not.toContain('ta-vote-btn');
    });

    it('swaps the header to "decided" and hides the countdown', () => {
        renderTitleArtistReveal(resolvedTa(), { is_admin: false });
        expect(els['ta-voting-title'].textContent).toBe('titleArtist.closeCallsDecided');
        expect(els['ta-voting-countdown'].classList.contains('hidden')).toBe(true);
    });

    it('still shows live vote cards (not outcomes) while voting is open', () => {
        const openTa = resolvedTa();
        openTa.voting_open = true;
        openTa.near_misses = [
            { id: 'Mia:title', player: 'Mia', field: 'title', guess: 'Bohem Rapsody', votes_yes: 2, votes_no: 1 },
        ];
        renderTitleArtistReveal(openTa, { is_admin: false });
        const html = els['ta-voting-cards'].innerHTML;
        expect(html).toContain('ta-vote-btn');
        expect(html).not.toContain('ta-outcome-card');
    });
});
