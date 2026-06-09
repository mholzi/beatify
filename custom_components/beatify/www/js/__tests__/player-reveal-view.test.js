/**
 * State-transition coverage for updateRevealView() in player-reveal.js (#1281).
 *
 * updateRevealView is the central reveal-phase state apply: it's exactly the
 * "State-Drift risk" surface called out in the issue. It imports the real
 * module and asserts the observable DOM effects of one server state payload:
 *
 *   - round / total counters painted from the payload.
 *   - idle-halt notice toggled on `data.idle_halt` (#1012).
 *   - Closest-Wins badge (#442) and intro-round badge (#23) shown/hidden.
 *   - song title / artist / correct-year text, with sane "Unknown" fallbacks.
 *   - admin reveal controls shown only for the admin player, and the next-round
 *     button re-enabled every REVEAL (the #534 re-arm that prevents the button
 *     latching disabled across rounds), with the final-round label swap.
 *
 * The many sub-renderers updateRevealView calls degrade to no-ops here because
 * their DOM targets are absent; the cross-module imports are mocked.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

function makeEl(id) {
    const classes = new Set();
    const children = {};
    const el = {
        id,
        textContent: '',
        innerHTML: '',
        src: '',
        disabled: false,
        onerror: null,
        style: {},
        _attrs: {},
        children,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => {
                const want = on === undefined ? !classes.has(c) : on;
                if (want) classes.add(c); else classes.delete(c);
                return classes.has(c);
            },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => el._attrs[k],
        querySelector: (sel) => children[sel] || null,
    };
    return el;
}

let els;
let querySelectorMap;
global.window = {
    BeatifyUtils: {
        t: (key) => key,
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.WebSocket = { OPEN: 1 };
global.document = {
    getElementById: (id) => els[id] || null,
    querySelector: (sel) => querySelectorMap[sel] || null,
};

const mockState = { playerName: null, lastRevealContext: null };
vi.mock('../player-utils.js', () => ({
    state: mockState,
    escapeHtml: (s) => String(s),
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

const { updateRevealView, stopRevealCountdown } = await import('../player-reveal.js');

function baseEls() {
    els = {
        'reveal-round': makeEl('reveal-round'),
        'reveal-total': makeEl('reveal-total'),
        'reveal-idle-halt': makeEl('reveal-idle-halt'),
        'closest-wins-badge': makeEl('closest-wins-badge'),
        'intro-badge': makeEl('intro-badge'),
        'reveal-album-cover': makeEl('reveal-album-cover'),
        'correct-year': makeEl('correct-year'),
        'song-title': makeEl('song-title'),
        'song-artist': makeEl('song-artist'),
        'reveal-admin-controls': makeEl('reveal-admin-controls'),
        'next-round-btn': makeEl('next-round-btn'),
    };
    // intro badge has an inner [data-i18n] label span
    const introLabel = makeEl();
    els['intro-badge'].children['[data-i18n]'] = introLabel;
    querySelectorMap = {};
}

beforeEach(() => {
    baseEls();
    mockState.playerName = 'Alice';
    mockState.lastRevealContext = null;
});

afterEach(() => {
    stopRevealCountdown();
});

describe('updateRevealView — counters and song info', () => {
    it('paints round / total / title / artist / year from the payload', () => {
        updateRevealView({
            round: 4,
            total_rounds: 12,
            song: { title: 'Africa', artist: 'Toto', year: 1982, album_art: 'x.jpg' },
            players: [],
        });
        expect(els['reveal-round'].textContent).toBe(4);
        expect(els['reveal-total'].textContent).toBe(12);
        expect(els['song-title'].textContent).toBe('Africa');
        expect(els['song-artist'].textContent).toBe('Toto');
        expect(els['correct-year'].textContent).toBe(1982);
    });

    it('falls back to Unknown/???? when song fields are missing', () => {
        updateRevealView({ song: {}, players: [] });
        expect(els['song-title'].textContent).toBe('Unknown Song');
        expect(els['song-artist'].textContent).toBe('Unknown Artist');
        expect(els['correct-year'].textContent).toBe('????');
        // round/total default to 1 / 10
        expect(els['reveal-round'].textContent).toBe(1);
        expect(els['reveal-total'].textContent).toBe(10);
    });

    it('uses the no-artwork SVG when album_art is absent', () => {
        updateRevealView({ song: {}, players: [] });
        expect(els['reveal-album-cover'].src).toBe('/beatify/static/img/no-artwork.svg');
    });
});

describe('updateRevealView — badges and idle-halt (#442 / #23 / #1012)', () => {
    it('toggles the idle-halt notice on data.idle_halt', () => {
        updateRevealView({ song: {}, players: [], idle_halt: true });
        expect(els['reveal-idle-halt'].classList.contains('hidden')).toBe(false);
        baseEls();
        updateRevealView({ song: {}, players: [], idle_halt: false });
        expect(els['reveal-idle-halt'].classList.contains('hidden')).toBe(true);
    });

    it('shows the Closest-Wins badge only in closest_wins_mode', () => {
        updateRevealView({ song: {}, players: [], closest_wins_mode: true });
        expect(els['closest-wins-badge'].classList.contains('hidden')).toBe(false);
        baseEls();
        updateRevealView({ song: {}, players: [], closest_wins_mode: false });
        expect(els['closest-wins-badge'].classList.contains('hidden')).toBe(true);
    });

    it('shows the intro badge only on an intro round', () => {
        updateRevealView({ song: {}, players: [], is_intro_round: true });
        expect(els['intro-badge'].classList.contains('hidden')).toBe(false);
        baseEls();
        updateRevealView({ song: {}, players: [], is_intro_round: false });
        expect(els['intro-badge'].classList.contains('hidden')).toBe(true);
    });
});

describe('updateRevealView — admin controls + next-round re-arm (#534)', () => {
    const adminPlayer = { name: 'Alice', is_admin: true };
    const guestPlayer = { name: 'Alice', is_admin: false };

    it('reveals admin controls and re-enables the next-round button for the admin', () => {
        // simulate a button latched disabled from the previous round
        els['next-round-btn'].disabled = true;
        updateRevealView({ song: {}, players: [adminPlayer] });
        expect(els['reveal-admin-controls'].classList.contains('hidden')).toBe(false);
        expect(els['next-round-btn'].disabled).toBe(false);
        expect(els['next-round-btn'].textContent).toBe('admin.nextRound');
        expect(els['next-round-btn'].classList.contains('is-final')).toBe(false);
    });

    it('switches the button to the final-results label on the last round', () => {
        updateRevealView({ song: {}, players: [adminPlayer], last_round: true });
        expect(els['next-round-btn'].textContent).toBe('leaderboard.finalResults');
        expect(els['next-round-btn'].classList.contains('is-final')).toBe(true);
    });

    it('hides admin controls for a non-admin player', () => {
        updateRevealView({ song: {}, players: [guestPlayer] });
        expect(els['reveal-admin-controls'].classList.contains('hidden')).toBe(true);
    });
});

describe('updateRevealView — context caching', () => {
    it('stashes the current player and song into state.lastRevealContext', () => {
        const me = { name: 'Alice', is_admin: false };
        const song = { title: 'Africa', year: 1982 };
        updateRevealView({ song, players: [me], round_analytics: { total_submitted: 3 } });
        expect(mockState.lastRevealContext).toBeTruthy();
        expect(mockState.lastRevealContext.player).toBe(me);
        expect(mockState.lastRevealContext.song).toBe(song);
        expect(mockState.lastRevealContext.analytics).toEqual({ total_submitted: 3 });
    });
});
