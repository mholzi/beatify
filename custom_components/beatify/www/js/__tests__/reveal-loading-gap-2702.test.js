/**
 * #2702 — the silent gap between two rounds.
 *
 * `start_round()` blocks for 5-25 s (25 since #2682 raised MA_PLAYBACK_TIMEOUT).
 * The host's phone said "Loading…"; the guests' phones and the TV showed the
 * auto-advance ring stopped at zero and nothing else. A stopped clock does not
 * read as "waiting", it reads as "broken" — which is exactly the complaint the
 * issue records.
 *
 * Two behaviours are covered here, on both surfaces:
 *
 *  1. the ring stops counting and starts turning (`is-waiting`), derived on the
 *     client from what it already knows — the countdown reached zero and no
 *     PLAYING state arrived. No new server frame was added, so there is no
 *     signal for a test to fake: elapsing the clock is the whole trigger.
 *  2. the reveal is staged in three beats on its OWN timer — answer, who got it
 *     right, standings — never gated on a loading signal, because gating it
 *     would make a fast round flash all three at once.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { doc, el, translator } from './helpers/mini-dom.js';
import { locale } from './helpers/js-source.js';

// ---------------------------------------------------------------------------
// Player phone — the module is importable, so it is imported.
// ---------------------------------------------------------------------------

let dom;
global.window = { BeatifyUtils: translator(locale('en')) };
global.document = {
    getElementById: (id) => dom.getElementById(id),
};

vi.mock('../player-utils.js', () => ({
    state: { playerName: 'Lena' },
    escapeHtml: (s) => String(s),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    updatePreviousState: () => {},
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    isTitleArtistMode: () => false,
    createModalFocusTrap: () => ({}),
    classifyYearsOff: () => 'exact',
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const {
    updateRevealCountdown,
    stopRevealCountdown,
    startRevealStaging,
    stopRevealStaging,
    renderRoundWinners,
    phoneStandingsRows,
} = await import('../player-reveal.js');

/** The three elements the ring is made of, plus the reveal root. */
function revealDom() {
    const fg = el(null);
    const chip = el('player-reveal-countdown', { children: { '.reveal-advance-fg': fg } });
    chip.classList.add('hidden');
    return doc({
        'player-reveal-countdown': chip,
        'player-reveal-countdown-num': el('player-reveal-countdown-num'),
        'reveal-view': el('reveal-view'),
        'reveal-whogot': el('reveal-whogot'),
        'reveal-whogot-list': el('reveal-whogot-list'),
        _fg: fg,
    });
}

describe('#2702 player ring: stops counting, starts turning', () => {
    beforeEach(() => { dom = revealDom(); });
    afterEach(() => { stopRevealCountdown(); });

    it('turns once the countdown has run out and the round has not started', () => {
        // 10 s of auto-advance that began 11 s ago: the countdown is over and
        // REVEAL is still on screen. That is the gap, and nothing else marks it.
        updateRevealCountdown({
            reveal_auto_advance: 10,
            reveal_started_at: Date.now() - 11000,
            idle_halt: false,
        });
        const chip = dom.elements['player-reveal-countdown'];
        const num = dom.elements['player-reveal-countdown-num'];
        expect(chip.classList.contains('hidden')).toBe(false);
        expect(chip.classList.contains('is-waiting')).toBe(true);
        // The digit is gone: a "0" is the frozen clock the issue is about.
        expect(num.textContent).toBe('…');
        expect(Number(num.textContent)).toBeNaN();
        // The gauge is gone too — a fixed arc, not "three quarters remaining".
        expect(String(dom.elements._fg.style.strokeDasharray)).toContain(' ');
        expect(chip.getAttribute('aria-busy')).toBe('true');
        // Re-uses a string that already exists in all six locales.
        expect(chip.getAttribute('data-i18n-aria-label')).toBe('game.starting');
    });

    it('counts normally while there is time left', () => {
        updateRevealCountdown({
            reveal_auto_advance: 10,
            reveal_started_at: Date.now(),
            idle_halt: false,
        });
        const chip = dom.elements['player-reveal-countdown'];
        expect(chip.classList.contains('is-waiting')).toBe(false);
        const n = Number(dom.elements['player-reveal-countdown-num'].textContent);
        expect(n).toBeGreaterThan(0);
        expect(n).toBeLessThanOrEqual(10);
    });

    it('leaves the waiting state when the next round brings a fresh countdown', () => {
        updateRevealCountdown({
            reveal_auto_advance: 10, reveal_started_at: Date.now() - 11000, idle_halt: false,
        });
        expect(dom.elements['player-reveal-countdown'].classList.contains('is-waiting')).toBe(true);
        updateRevealCountdown({
            reveal_auto_advance: 10, reveal_started_at: Date.now(), idle_halt: false,
        });
        const chip = dom.elements['player-reveal-countdown'];
        expect(chip.classList.contains('is-waiting')).toBe(false);
        // The drained-gauge geometry is back, not the fixed waiting arc.
        expect(String(dom.elements._fg.style.strokeDasharray)).not.toContain(' ');
        expect(chip.getAttribute('aria-busy')).toBe('false');
    });

    it('drops the waiting state when REVEAL ends', () => {
        updateRevealCountdown({
            reveal_auto_advance: 10, reveal_started_at: Date.now() - 11000, idle_halt: false,
        });
        stopRevealCountdown();
        const chip = dom.elements['player-reveal-countdown'];
        expect(chip.classList.contains('is-waiting')).toBe(false);
        expect(chip.classList.contains('hidden')).toBe(true);
    });
});

describe('#2702 player reveal: three beats on their own clock', () => {
    beforeEach(() => { dom = revealDom(); vi.useFakeTimers(); });
    afterEach(() => { stopRevealStaging(); vi.useRealTimers(); });

    it('runs answer -> who got it right -> standings', () => {
        const root = dom.elements['reveal-view'];
        startRevealStaging({ round: 3, reveal_started_at: 1000 });
        expect(root.getAttribute('data-reveal-stage')).toBe('1');
        vi.advanceTimersByTime(1499);
        expect(root.getAttribute('data-reveal-stage')).toBe('1');
        vi.advanceTimersByTime(1);
        expect(root.getAttribute('data-reveal-stage')).toBe('2');
        vi.advanceTimersByTime(1500);
        expect(root.getAttribute('data-reveal-stage')).toBe('3');
    });

    it('does not rewind on a REVEAL re-broadcast', () => {
        // Reactions and live title/artist voting re-broadcast REVEAL constantly.
        // Restarting the beats there would replay them under the room's nose.
        const root = dom.elements['reveal-view'];
        startRevealStaging({ round: 3, reveal_started_at: 1000 });
        vi.advanceTimersByTime(3000);
        expect(root.getAttribute('data-reveal-stage')).toBe('3');
        startRevealStaging({ round: 3, reveal_started_at: 1000 });
        expect(root.getAttribute('data-reveal-stage')).toBe('3');
    });

    it('starts over for the next reveal', () => {
        const root = dom.elements['reveal-view'];
        startRevealStaging({ round: 3, reveal_started_at: 1000 });
        vi.advanceTimersByTime(3000);
        startRevealStaging({ round: 4, reveal_started_at: 9000 });
        expect(root.getAttribute('data-reveal-stage')).toBe('1');
    });

    it('cuts the beats when the phase leaves REVEAL', () => {
        // No attribute means "show everything" in CSS, which is also what a
        // client whose timers never ran must see.
        const root = dom.elements['reveal-view'];
        startRevealStaging({ round: 3, reveal_started_at: 1000 });
        stopRevealCountdown();
        expect(root.getAttribute('data-reveal-stage')).toBe(null);
        vi.advanceTimersByTime(5000);
        expect(root.getAttribute('data-reveal-stage')).toBe(null);
    });
});

describe('#2702 beat two: who got it right', () => {
    beforeEach(() => { dom = revealDom(); });

    it('lists the three best of the round, best first', () => {
        renderRoundWinners({
            players: [
                { name: 'Jonas', round_score: 80, guess: 1996 },
                { name: 'Lena', round_score: 100, streak_bonus: 20, guess: 1997 },
                { name: 'Sarah', round_score: 40, guess: 1990 },
                { name: 'Tom', round_score: 10, guess: 1980 },
                { name: 'Mia', missed_round: true, round_score: 0 },
            ],
        });
        const html = dom.elements['reveal-whogot-list'].innerHTML;
        expect(dom.elements['reveal-whogot'].classList.contains('hidden')).toBe(false);
        expect(html.indexOf('Lena')).toBeLessThan(html.indexOf('Jonas'));
        expect(html.indexOf('Jonas')).toBeLessThan(html.indexOf('Sarah'));
        expect(html).not.toContain('Tom');   // only three
        expect(html).not.toContain('Mia');   // did not play
        // The streak bonus counts, exactly as the score row and the delta do.
        expect(html).toContain('+120');
        // The reader's own line is marked.
        expect(html).toContain('whogot-row--you');
    });

    it('stays hidden when nobody scored', () => {
        renderRoundWinners({ players: [{ name: 'Jonas', round_score: 0 }] });
        expect(dom.elements['reveal-whogot'].classList.contains('hidden')).toBe(true);
        expect(dom.elements['reveal-whogot-list'].innerHTML).toBe('');
    });
});

describe('#2702 beat three: the phone standings', () => {
    const board = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']
        .map((name, i) => ({ name, rank: i + 1, score: 100 - i }));

    it('shows the podium plus the reader own row', () => {
        const rows = phoneStandingsRows(board, 'J');
        expect(rows.filter((r) => r.entry).map((r) => r.entry.name)).toEqual(['A', 'B', 'C', 'J']);
        // Something was skipped, so it is marked as skipped.
        expect(rows.some((r) => r.gap)).toBe(true);
    });

    it('does not claim an elision when nothing was skipped', () => {
        const rows = phoneStandingsRows(board, 'D');
        expect(rows.filter((r) => r.entry).map((r) => r.entry.name)).toEqual(['A', 'B', 'C', 'D']);
        expect(rows.some((r) => r.gap)).toBe(false);
    });

    it('shows only the podium when the reader is on it', () => {
        const rows = phoneStandingsRows(board, 'B');
        expect(rows.map((r) => r.entry.name)).toEqual(['A', 'B', 'C']);
    });

    it('survives a shorter board and an unknown reader', () => {
        expect(phoneStandingsRows(board.slice(0, 2), 'A').length).toBe(2);
        expect(phoneStandingsRows(board, 'Nobody').length).toBe(3);
        expect(phoneStandingsRows(null, 'A')).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// TV dashboard — an IIFE with no exports, so the shipped declarations are cut
// out and run (the #2701 approach).
// ---------------------------------------------------------------------------

const DASHBOARD = readSource('dashboard.js');

function tvRing() {
    const fg = el(null);
    const label = el(null);
    const chip = el('reveal-countdown', {
        children: { '.chip-countdown-fg': fg, '.chip-countdown-label': label },
    });
    return { chip, fg, label, num: el('reveal-countdown-num') };
}

function runTvCountdown(parts, data) {
    const document_ = doc({
        'reveal-countdown': parts.chip,
        'reveal-countdown-num': parts.num,
    });
    evaluate(
        [
            declaration(DASHBOARD, 'setRevealWaiting', 'dashboard.js'),
            declaration(DASHBOARD, 'updateRevealCountdown', 'dashboard.js'),
        ],
        'updateRevealCountdown',
        {
            document: document_,
            utils: translator(locale('en')),
            _countdownTick: null,
            REVEAL_WAIT_GLYPH: '…',
        },
    )(data);
}

describe('#2702 TV ring', () => {
    it('turns, and renames its label, once the countdown has run out', () => {
        const parts = tvRing();
        runTvCountdown(parts, {
            reveal_auto_advance: 10, reveal_started_at: Date.now() - 11000, idle_halt: false,
        });
        expect(parts.chip.classList.contains('is-waiting')).toBe(true);
        expect(parts.num.textContent).toBe('…');
        expect(parts.label.textContent).toBe('Starting...');
        // #2619: data-i18n follows the text, or a mid-game language switch
        // re-renders a label that is no longer on screen.
        expect(parts.label.getAttribute('data-i18n')).toBe('game.starting');
    });

    it('counts, and reads Auto-advance, while there is time left', () => {
        const parts = tvRing();
        runTvCountdown(parts, {
            reveal_auto_advance: 10, reveal_started_at: Date.now(), idle_halt: false,
        });
        expect(parts.chip.classList.contains('is-waiting')).toBe(false);
        expect(Number(parts.num.textContent)).toBeGreaterThan(0);
        expect(parts.label.getAttribute('data-i18n')).toBe('dashboard.autoAdvance');
    });

    it('hides on idle-halt without leaving a waiting ring behind', () => {
        const parts = tvRing();
        runTvCountdown(parts, {
            reveal_auto_advance: 10, reveal_started_at: Date.now() - 11000, idle_halt: false,
        });
        runTvCountdown(parts, {
            reveal_auto_advance: 10, reveal_started_at: Date.now(), idle_halt: true,
        });
        expect(parts.chip.classList.contains('hidden')).toBe(true);
        expect(parts.chip.classList.contains('is-waiting')).toBe(false);
    });
});

describe('#2702 TV beats', () => {
    function tvStager(root) {
        const document_ = doc({ 'dashboard-reveal': root });
        const scope = {
            document: document_,
            REVEAL_BEAT_2_MS: 1500,
            REVEAL_BEAT_3_MS: 3000,
            _revealStageTimers: [],
            _revealStageKey: null,
        };
        const snippets = [
            declaration(DASHBOARD, '_setRevealStage', 'dashboard.js'),
            declaration(DASHBOARD, 'startRevealStaging', 'dashboard.js'),
            declaration(DASHBOARD, 'stopRevealStaging', 'dashboard.js'),
        ];
        return evaluate(snippets, '({ start: startRevealStaging, stop: stopRevealStaging })', scope);
    }

    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    it('runs the same three beats as the phone', () => {
        const root = el('dashboard-reveal');
        const stager = tvStager(root);
        stager.start({ round: 2, reveal_started_at: 500 });
        expect(root.getAttribute('data-reveal-stage')).toBe('1');
        vi.advanceTimersByTime(1500);
        expect(root.getAttribute('data-reveal-stage')).toBe('2');
        vi.advanceTimersByTime(1500);
        expect(root.getAttribute('data-reveal-stage')).toBe('3');
        stager.stop();
        expect(root.getAttribute('data-reveal-stage')).toBe(null);
    });
});
