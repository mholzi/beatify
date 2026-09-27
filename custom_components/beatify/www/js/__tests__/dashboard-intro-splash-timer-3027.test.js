/**
 * #3027 — the TV counted down while the phones waited for the host.
 *
 * In Intro Mode the server sets `intro_splash_pending` and stamps only a
 * placeholder deadline (round_manager.py); the real one arrives when the host
 * confirms the splash. The phones show "waiting for host", but the TV ignored
 * the flag and ran the timer from the placeholder down to a critical-red 0
 * while no music played, then jumped back to full.
 *
 * The shipped renderPlayingView, countdown and round-stats code run here for
 * real (see helpers/js-source.js); only the DOM and the unrelated renderers are
 * stubbed. Timers and the clock are vitest's fake ones.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');
const SNIPPETS = [
    'var lastCountdownDeadline = null;',
    'var countdownInterval = null;',
    ...['renderPlayingView', 'renderRoundStats', 'startCountdown', 'stopCountdown', 'showRestingTimer'].map(
        (name) => declaration(DASHBOARD, name, 'dashboard.js'),
    ),
];

function makeEl(text = '') {
    const classes = new Set();
    return {
        textContent: text,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
        },
    };
}

let els;
let render;

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    els = {
        'dashboard-timer': makeEl('30'),
        'dashboard-time-remaining': makeEl('--'),
        'dashboard-submissions': makeEl(''),
    };
    const noop = () => {};
    render = evaluate(SNIPPETS, 'renderPlayingView', {
        document: { getElementById: (id) => els[id] || null },
        utils: { t: () => '' },
        debug: noop,
        lastRenderedRound: null,
        songStoppedRound: null,
        setSongStoppedChip: noop,
        renderJoinCorner: noop,
        renderLeaderboard: noop,
        renderGhostLeague: noop,
        renderSuddenDeathFinalBanner: noop,
        renderFinaleDoubleBanner: noop,
        renderFinalePlayoffBanner: noop,
    });
});

afterEach(() => {
    vi.useRealTimers();
});

const timer = () => els['dashboard-timer'];

function frame(extra) {
    return {
        phase: 'PLAYING',
        round: 1,
        total_rounds: 10,
        round_duration: 30,
        players: [],
        ...extra,
    };
}

describe('#3027 TV timer while the intro splash is pending', () => {
    it('holds the timer full instead of counting down the placeholder deadline', () => {
        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 30 }));
        expect(timer().textContent).toBe(30);

        // Well past the placeholder deadline: nothing ticks, nothing turns red.
        vi.advanceTimersByTime(40_000);
        expect(timer().textContent).toBe(30);
        expect(timer().classList.contains('timer--critical')).toBe(false);
        expect(timer().classList.contains('timer--warning')).toBe(false);
    });

    it('keeps the stat at full on later pending frames, whose seconds_remaining shrinks', () => {
        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 30 }));
        vi.advanceTimersByTime(27_000);
        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 3 }));
        expect(timer().textContent).toBe(30);
        expect(els['dashboard-time-remaining'].textContent).toBe('30s');
        expect(timer().classList.contains('timer--critical')).toBe(false);
    });

    it('stops a countdown that was already running when the flag appears', () => {
        render(frame({ deadline: 1_030_000, seconds_remaining: 30 }));
        vi.advanceTimersByTime(26_000);
        expect(timer().classList.contains('timer--critical')).toBe(true);

        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 4 }));
        expect(timer().textContent).toBe(30);
        expect(timer().classList.contains('timer--critical')).toBe(false);
        vi.advanceTimersByTime(5_000);
        expect(timer().textContent).toBe(30);
    });

    it('starts counting down on the frame that clears the flag', () => {
        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 30 }));
        vi.advanceTimersByTime(12_000);

        // Host confirmed: the server re-stamps the deadline from now.
        render(frame({ intro_splash_pending: false, deadline: 1_042_000, seconds_remaining: 30 }));
        expect(timer().textContent).toBe(30);
        vi.advanceTimersByTime(3_000);
        expect(timer().textContent).toBe(27);
    });

    it('restarts even when the confirmed deadline equals the placeholder', () => {
        render(frame({ intro_splash_pending: true, deadline: 1_030_000, seconds_remaining: 30 }));
        render(frame({ intro_splash_pending: false, deadline: 1_030_000, seconds_remaining: 30 }));
        vi.advanceTimersByTime(1_000);
        expect(timer().textContent).toBe(29);
    });

    it('leaves a normal round counting down as before', () => {
        render(frame({ deadline: 1_030_000, seconds_remaining: 30 }));
        vi.advanceTimersByTime(25_000);
        expect(timer().textContent).toBe(5);
        expect(timer().classList.contains('timer--critical')).toBe(true);
    });
});
