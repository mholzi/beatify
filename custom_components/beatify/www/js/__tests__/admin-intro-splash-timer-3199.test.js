/**
 * #3199 — the admin countdown ran while the intro round waited for the host.
 *
 * The TV holds its timer while `intro_splash_pending` is set (#3027); the admin
 * page called startAdminCountdown on every frame, so it counted the placeholder
 * deadline down to a critical-red 0 behind the waiting card. The shipped
 * helpers run here for real; timers and the clock are vitest's fake ones.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const ADMIN = readSource('admin.js');
const SNIPPETS = [
    'var countdownInterval = null;',
    declaration(ADMIN, 'startAdminCountdown', 'admin.js'),
    declaration(ADMIN, 'holdAdminCountdown', 'admin.js'),
];

function makeEl(text = '') {
    const classes = new Set();
    return {
        textContent: text,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
            contains: (c) => classes.has(c),
        },
    };
}

let timerEl;
let api;

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    timerEl = makeEl('--');
    const ctx = { document: { getElementById: (id) => (id === 'admin-timer' ? timerEl : null) } };
    // One evaluation, so both helpers share the module-level countdownInterval.
    api = evaluate(SNIPPETS, '{ start: startAdminCountdown, hold: holdAdminCountdown }', ctx);
});

afterEach(() => {
    vi.useRealTimers();
});

describe('#3199 admin timer while the intro splash is pending', () => {
    it('holds the timer at the round length and nothing ticks', () => {
        api.hold(30);
        expect(timerEl.textContent).toBe(30);
        vi.advanceTimersByTime(40_000);
        expect(timerEl.textContent).toBe(30);
        expect(timerEl.classList.contains('timer--critical')).toBe(false);
    });

    it('stops a countdown that was already running and clears warning colours', () => {
        api.start(1_030_000, 1_000_000);
        vi.advanceTimersByTime(26_000);
        expect(timerEl.classList.contains('timer--critical')).toBe(true);

        api.hold(30);
        expect(timerEl.textContent).toBe(30);
        expect(timerEl.classList.contains('timer--critical')).toBe(false);
        vi.advanceTimersByTime(5_000);
        expect(timerEl.textContent).toBe(30);
    });

    it('counts down again once the flag clears', () => {
        api.hold(30);
        api.start(1_042_000, 1_000_000);
        vi.advanceTimersByTime(3_000);
        expect(timerEl.textContent).toBe(39);
    });
});

describe('#3199 admin playing view', () => {
    it('only starts the countdown when no intro splash is pending', () => {
        const idx = ADMIN.indexOf('holdAdminCountdown(data.round_duration)');
        expect(idx).toBeGreaterThan(-1);
        const around = ADMIN.slice(idx - 80, idx + 200);
        expect(around).toMatch(/if \(data\.intro_splash_pending\)/);
        expect(around).toMatch(/else \{\s*startAdminCountdown\(data\.deadline/);
    });
});
