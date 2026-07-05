/**
 * #1663 item 4 — Depleting Ring-Countdown (player-game/timer.js).
 *
 * The arcade neon timer gains an SVG ring that drains as the round runs out and
 * escalates cyan → amber (≤10s) → red (≤5s), mirroring the number's
 * warning/critical thresholds. This asserts the ring's stroke-dashoffset tracks
 * remaining/total and the colour-escalation classes flip at the right seconds.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// timer.js only imports { state } from player-utils — keep the mock tiny.
vi.mock('../player-utils.js', () => ({ state: {} }));

let timerEl, timerNeon, fgCircle, floatEl, floatNum;
function makeClassList() {
    return {
        _set: new Set(),
        add() { for (var i = 0; i < arguments.length; i++) this._set.add(arguments[i]); },
        remove() { for (var i = 0; i < arguments.length; i++) this._set.delete(arguments[i]); },
        toggle(c, on) { if (on) this._set.add(c); else this._set.delete(c); return this._set.has(c); },
        contains(c) { return this._set.has(c); },
    };
}
function installDom() {
    fgCircle = { style: {} };
    timerEl = { textContent: '', classList: makeClassList(), setAttribute() {} };
    timerNeon = {
        classList: makeClassList(),
        querySelector: (sel) => (sel === '.timer-neon-ring-fg' ? fgCircle : null),
    };
    floatEl = { classList: makeClassList() };
    floatNum = { textContent: '' };
    global.window = {};
    global.document = {
        getElementById: (id) => {
            if (id === 'timer') return timerEl;
            if (id === 'timer-neon') return timerNeon;
            if (id === 'timer-float') return floatEl;
            if (id === 'timer-float-num') return floatNum;
            return null;
        },
    };
    // timer.js guards smooth-correct behind `typeof requestAnimationFrame`.
    global.requestAnimationFrame = undefined;
    global.IntersectionObserver = undefined;
}

const RING_C = 2 * Math.PI * 33;
const { startCountdown, stopCountdown } = await import('../player-game/timer.js');

describe('#1663 item 4 — depleting ring', () => {
    beforeEach(() => { vi.useFakeTimers(); installDom(); });
    afterEach(() => { stopCountdown(); vi.useRealTimers(); });

    it('starts full at the fresh countdown start', () => {
        startCountdown(Date.now() + 30000, 30);
        // Full ring → offset ~0 (whole circumference drawn).
        expect(parseFloat(fgCircle.style.strokeDashoffset)).toBeCloseTo(0, 1);
        expect(String(fgCircle.style.strokeDasharray)).toBe(String(RING_C));
    });

    it('drains proportionally and escalates to critical near the end', () => {
        startCountdown(Date.now() + 30000, 30);
        // Tick forward to 5s remaining (25s elapsed).
        vi.advanceTimersByTime(25000);
        expect(timerEl.textContent).toBe(5);
        // frac = 5/30 → offset = C * (1 - 5/30).
        const expected = RING_C * (1 - 5 / 30);
        expect(parseFloat(fgCircle.style.strokeDashoffset)).toBeCloseTo(expected, 1);
        // Colour escalation: ≤5s = critical, not warn.
        expect(timerNeon.classList.contains('timer-neon-ring--critical')).toBe(true);
        expect(timerNeon.classList.contains('timer-neon-ring--warn')).toBe(false);
    });

    it('uses the amber warn class in the 6–10s band', () => {
        startCountdown(Date.now() + 30000, 30);
        vi.advanceTimersByTime(22000); // 8s remaining
        expect(timerEl.textContent).toBe(8);
        expect(timerNeon.classList.contains('timer-neon-ring--warn')).toBe(true);
        expect(timerNeon.classList.contains('timer-neon-ring--critical')).toBe(false);
    });

    it('resets the ring on stopCountdown', () => {
        startCountdown(Date.now() + 30000, 30);
        vi.advanceTimersByTime(25000);
        stopCountdown();
        expect(fgCircle.style.strokeDashoffset).toBe('0');
        expect(timerNeon.classList.contains('timer-neon-ring--critical')).toBe(false);
        expect(timerNeon.classList.contains('timer-neon-ring--warn')).toBe(false);
    });
});
