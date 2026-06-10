/**
 * State-transition coverage for player-game.js (#1281).
 *
 * player-game.js is one of the large, logic-heavy, previously-untested state
 * files. These tests exercise the real round/control state machine — they
 * import the actual module (no re-implementation) and assert the observable
 * effects on DOM nodes / outgoing WebSocket messages:
 *
 *   - startCountdown / stopCountdown: timer text, warning/critical thresholds,
 *     and the post-deadline `round_timeout` watchdog nudges (#534 / freeze
 *     recovery).
 *   - updateControlBarState: PLAYING vs REVEAL vs other phase → which control
 *     buttons enable/disable and the label they show.
 *   - handleSongStopped / resetSongStoppedState: the Stop-Song toggle (Story 6.2)
 *     and the fact that updateControlBarState('PLAYING') resets a stopped song.
 *   - handleNextRound / resetNextRoundPending: the 2 s debounce latch (#534) that
 *     stops a double next-round send and re-arms on reset.
 *
 * Browser globals are stubbed for the node test env; player-utils.js and
 * player-reveal.js are mocked so the module loads in isolation.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ---- browser-global stubs (must exist before the module is imported) --------
global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
global.window = {
    BeatifyUtils: {
        // identity translator: returns the key so we can assert which label was set
        t: (key) => key,
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

// Minimal element stub with classList + querySelector for nested label/icon spans.
function makeEl(id) {
    const classes = new Set();
    const children = {};
    const el = {
        id,
        textContent: '',
        disabled: false,
        _attrs: {},
        children,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); return classes.has(c); },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => el._attrs[k],
        querySelector: (sel) => children[sel] || null,
    };
    return el;
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
};

vi.mock('../player-utils.js', () => {
    const state = { ws: null };
    return {
        state,
        escapeHtml: (s) => String(s),
        showConfirmModal: async () => true,
        prefersReducedMotion: () => true,
        animateValue: () => {},
        animateScoreChange: () => {},
        showPointsPopup: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
        isStreakMilestone: () => false,
        detectRankChanges: () => ({}),
        updatePreviousState: () => {},
        AnimationUtils: {},
        AnimationQueue: { isRunning: () => false, skipAll: () => {} },
        LEADERBOARD_LAZY_CONFIG: {},
        lazyLeaderboardState: {},
        initLeaderboardObserver: () => {},
        renderLazyLeaderboardRange: () => {},
        renderLeaderboardEntry: () => '',
        calculateInitialVisibleRange: () => [0, 0],
        setupLeaderboardResizeHandler: () => {},
        setEnergyLevel: () => {},
        triggerConfetti: () => {},
        stopConfetti: () => {},
    };
});

const utilsMod = await import('../player-utils.js');
const {
    startCountdown,
    stopCountdown,
    updateControlBarState,
    handleSongStopped,
    resetSongStoppedState,
    handleNextRound,
    resetNextRoundPending,
} = await import('../player-game.js');

// helper: build a control button with a nested .control-label (+ optional icon)
function makeControlBtn(id, withIcon) {
    const btn = makeEl(id);
    btn.children['.control-label'] = makeEl();
    if (withIcon) btn.children['.control-icon'] = makeEl();
    return btn;
}

beforeEach(() => {
    els = {};
    utilsMod.state.ws = null;
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
});

afterEach(() => {
    stopCountdown();
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe('startCountdown / stopCountdown', () => {
    beforeEach(() => {
        els.timer = makeEl('timer');
        els['timer-neon'] = makeEl('timer-neon');
        els['timer-float'] = makeEl('timer-float');
        els['timer-float-num'] = makeEl('timer-float-num');
    });

    it('paints the initial remaining seconds and mirrors them onto the float pill', () => {
        startCountdown(Date.now() + 30_000);
        expect(els.timer.textContent).toBe(30);
        expect(els['timer-float-num'].textContent).toBe(30);
        // plenty of time left → neither warning nor critical
        expect(els.timer.classList.contains('timer--warning')).toBe(false);
        expect(els.timer.classList.contains('timer--critical')).toBe(false);
    });

    it('ticks down once per second', () => {
        startCountdown(Date.now() + 30_000);
        expect(els.timer.textContent).toBe(30);
        vi.advanceTimersByTime(3000);
        expect(els.timer.textContent).toBe(27);
    });

    it('applies the warning class at <=10s and critical at <=5s', () => {
        startCountdown(Date.now() + 11_000);
        expect(els.timer.classList.contains('timer--warning')).toBe(false);
        vi.advanceTimersByTime(1000); // now 10s
        expect(els.timer.classList.contains('timer--warning')).toBe(true);
        expect(els['timer-neon'].classList.contains('timer-neon--warn')).toBe(true);
        vi.advanceTimersByTime(5000); // now 5s
        expect(els.timer.classList.contains('timer--critical')).toBe(true);
        expect(els.timer.classList.contains('timer--warning')).toBe(false);
    });

    it('nudges the server with round_timeout once the deadline passes (watchdog #534)', () => {
        const sent = [];
        utilsMod.state.ws = { readyState: WebSocket.OPEN, send: (m) => sent.push(JSON.parse(m)) };
        startCountdown(Date.now() + 1000);
        expect(sent).toHaveLength(0);
        vi.advanceTimersByTime(1000); // hits 0 → first nudge
        expect(sent.filter((m) => m.type === 'round_timeout')).toHaveLength(1);
        // keeps nudging every 3 ticks past the deadline, not just once
        vi.advanceTimersByTime(3000);
        expect(sent.filter((m) => m.type === 'round_timeout').length).toBeGreaterThanOrEqual(2);
    });

    it('does not nudge while the socket is closed', () => {
        utilsMod.state.ws = { readyState: WebSocket.CLOSED, send: () => { throw new Error('should not send'); } };
        startCountdown(Date.now() + 1000);
        expect(() => vi.advanceTimersByTime(4000)).not.toThrow();
    });

    it('stopCountdown halts further ticks and hides the float', () => {
        startCountdown(Date.now() + 30_000);
        stopCountdown();
        const frozen = els.timer.textContent;
        vi.advanceTimersByTime(5000);
        expect(els.timer.textContent).toBe(frozen);
        expect(els['timer-float'].classList.contains('hidden')).toBe(true);
    });

    it('is a no-op (no throw) when the timer node is absent', () => {
        delete els.timer;
        expect(() => startCountdown(Date.now() + 5000)).not.toThrow();
    });
});

describe('updateControlBarState', () => {
    beforeEach(() => {
        els['stop-song-btn'] = makeControlBtn('stop-song-btn', true);
        els['next-round-admin-btn'] = makeControlBtn('next-round-admin-btn');
        els['end-game-btn'] = makeControlBtn('end-game-btn');
    });

    it('PLAYING enables stop + next (labelled skip) and re-enables End', () => {
        // pre-disable End to prove it gets reset
        els['end-game-btn'].disabled = true;
        els['end-game-btn'].classList.add('is-disabled');

        updateControlBarState('PLAYING');

        const next = els['next-round-admin-btn'];
        expect(next.disabled).toBe(false);
        expect(next.classList.contains('is-disabled')).toBe(false);
        expect(next.querySelector('.control-label').textContent).toBe('game.skip');
        expect(els['stop-song-btn'].disabled).toBe(false);
        expect(els['end-game-btn'].disabled).toBe(false);
        expect(els['end-game-btn'].classList.contains('is-disabled')).toBe(false);
    });

    it('REVEAL labels the next button "next" and keeps it enabled', () => {
        updateControlBarState('REVEAL');
        const next = els['next-round-admin-btn'];
        expect(next.disabled).toBe(false);
        expect(next.querySelector('.control-label').textContent).toBe('game.next');
    });

    it('any other phase disables the next button', () => {
        updateControlBarState('LOBBY');
        const next = els['next-round-admin-btn'];
        expect(next.disabled).toBe(true);
        expect(next.classList.contains('is-disabled')).toBe(true);
    });

    it('PLAYING resets a previously stopped song back to active', () => {
        handleSongStopped();
        expect(els['stop-song-btn'].disabled).toBe(true);
        updateControlBarState('PLAYING');
        expect(els['stop-song-btn'].disabled).toBe(false);
        expect(els['stop-song-btn'].classList.contains('is-stopped')).toBe(false);
    });
});

describe('handleSongStopped / resetSongStoppedState (Story 6.2)', () => {
    beforeEach(() => {
        els['stop-song-btn'] = makeControlBtn('stop-song-btn', true);
    });

    it('marks the button stopped + disabled with a checkmark', () => {
        handleSongStopped();
        const btn = els['stop-song-btn'];
        expect(btn.disabled).toBe(true);
        expect(btn.classList.contains('is-stopped')).toBe(true);
        expect(btn.classList.contains('is-disabled')).toBe(true);
        expect(btn.querySelector('.control-icon').textContent).toBe('✓');
        expect(btn.querySelector('.control-label').textContent).toBe('game.stopped');
    });

    it('reset clears the stopped state and restores the stop icon', () => {
        handleSongStopped();
        resetSongStoppedState();
        const btn = els['stop-song-btn'];
        expect(btn.disabled).toBe(false);
        expect(btn.classList.contains('is-stopped')).toBe(false);
        expect(btn.querySelector('.control-icon').textContent).toBe('⏹️');
        expect(btn.querySelector('.control-label').textContent).toBe('game.stop');
    });
});

describe('handleNextRound / resetNextRoundPending debounce (#534)', () => {
    beforeEach(() => {
        els['next-round-btn'] = makeEl('next-round-btn');
        els['next-round-admin-btn'] = makeControlBtn('next-round-admin-btn');
        // `nextRoundPending` is module-level state; clear it so the latch from a
        // prior test (whose 10s safety timeout got flushed in afterEach) doesn't
        // bleed in and swallow this test's first click.
        resetNextRoundPending();
    });

    function wireSocket() {
        const sent = [];
        utilsMod.state.ws = { readyState: WebSocket.OPEN, send: (m) => sent.push(JSON.parse(m)) };
        return sent;
    }

    it('sends exactly one next_round and latches the buttons disabled', () => {
        const sent = wireSocket();
        handleNextRound();
        expect(sent.filter((m) => m.action === 'next_round')).toHaveLength(1);
        expect(els['next-round-btn'].disabled).toBe(true);
        expect(els['next-round-admin-btn'].disabled).toBe(true);
    });

    it('swallows a rapid second click while pending', () => {
        const sent = wireSocket();
        handleNextRound();
        handleNextRound();
        expect(sent.filter((m) => m.action === 'next_round')).toHaveLength(1);
    });

    it('re-arms after the 10s safety timeout fires', () => {
        const sent = wireSocket();
        handleNextRound();
        vi.advanceTimersByTime(10_000); // safety timeout → resetNextRoundPending
        handleNextRound();
        expect(sent.filter((m) => m.action === 'next_round')).toHaveLength(2);
    });

    it('resetNextRoundPending re-enables the buttons and allows another send', () => {
        const sent = wireSocket();
        handleNextRound();
        resetNextRoundPending();
        expect(els['next-round-btn'].disabled).toBe(false);
        handleNextRound();
        expect(sent.filter((m) => m.action === 'next_round')).toHaveLength(2);
    });

    it('does nothing when the socket is not open', () => {
        utilsMod.state.ws = { readyState: WebSocket.CLOSED, send: () => { throw new Error('no send'); } };
        expect(() => handleNextRound()).not.toThrow();
    });
});
