/**
 * #3365 - the phone half of the motion: the guess input answers, and the reveal
 * reel and standings respect the same gate as the TV. The shipped modules run,
 * only their imports and the DOM are stubbed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const flags = vi.hoisted(() => ({ reduced: false }));

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.requestAnimationFrame = () => 1;
global.cancelAnimationFrame = () => {};
global.window = global.window || {};
global.window.matchMedia = () => ({ matches: false, addEventListener: () => {} });
global.window.location = { search: '', pathname: '/', host: 'x', protocol: 'http:' };
global.window.addEventListener = () => {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

function makeEl(id) {
    const classes = new Set();
    const listeners = {};
    const node = {
        id, textContent: '', innerHTML: '', disabled: false, value: '1990', min: '1950', max: '2030', style: {},
        anims: [], attrs: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
        },
        animate: (frames, opts) => {
            const a = { frames, opts, cancel: vi.fn() };
            node.anims.push(a);
            return a;
        },
        setAttribute: (k, v) => { node.attrs[k] = v; },
        removeAttribute: (k) => { delete node.attrs[k]; },
        getAttribute: (k) => node.attrs[k],
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
        fire: (t, self) => (listeners[t] || []).forEach((fn) => fn.call(self || node, { preventDefault() {} })),
    };
    return node;
}
let els = {};
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
    querySelector: () => null,
    querySelectorAll: () => [],
};

vi.mock('../player-utils.js', async (orig) => {
    const real = await orig();
    return Object.assign({}, real, {
        state: { ws: { readyState: 1, send: vi.fn() }, playerName: 'Lena' },
        prefersReducedMotion: () => flags.reduced,
    });
});

const game = await import('../player-game.js');
const reveal = await import('../player-reveal.js');
const { state, previousState } = await import('../player-utils.js');

function ids(list) {
    els = {};
    list.forEach((id) => { els[id] = makeEl(id); });
    return els;
}

describe('#3365 guess input', () => {
    let vibrate;

    beforeEach(() => {
        flags.reduced = false;
        ids(['year-slider', 'selected-year', 'year-display-arc', 'submit-btn', 'year-selector']);
        game.resetSubmissionState();
        ids(['year-slider', 'selected-year', 'year-display-arc', 'submit-btn', 'year-selector']);
        vibrate = vi.fn();
        vi.stubGlobal('navigator', { vibrate });
        vi.useFakeTimers();
    });
    afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

    it('settles the button and buzzes on the ack of a tapped guess', () => {
        game.handleSubmitGuess();
        expect(els['submit-btn'].anims).toHaveLength(0);
        game.handleSubmitAck();
        expect(els['submit-btn'].anims).toHaveLength(1);
        expect(Object.keys(els['submit-btn'].anims[0].frames[0])).toEqual(['transform']);
        expect(vibrate).toHaveBeenCalledTimes(1);
    });

    it('stays still on the ack path a reload takes', () => {
        game.handleSubmitGuess();
        game.handleSubmitAck();
        expect(vibrate).toHaveBeenCalledTimes(1);
        game.resetSubmissionState();
        game.handleSubmitAck();
        expect(els['submit-btn'].anims).toHaveLength(1);
        expect(vibrate).toHaveBeenCalledTimes(1);
    });

    it('stays still on the ack after a rejected guess', () => {
        game.handleSubmitGuess();
        game.handleSubmitAck();
        game.resetSubmissionState();
        game.handleSubmitGuess();
        game.handleSubmitError({ code: 'ALREADY_SUBMITTED' });
        expect(els['submit-btn'].anims).toHaveLength(1);
        expect(vibrate).toHaveBeenCalledTimes(1);
    });

    it('does not carry a tap over to the next round', () => {
        game.handleSubmitGuess();
        game.handleSubmitAck();
        game.resetSubmissionState();
        game.handleSubmitGuess();
        game.resetSubmissionState();
        game.handleSubmitAck();
        expect(vibrate).toHaveBeenCalledTimes(1);
    });

    it('does nothing where the browser has no vibration API', () => {
        vi.stubGlobal('navigator', {});
        game.handleSubmitGuess();
        expect(() => game.handleSubmitAck()).not.toThrow();
        expect(els['submit-btn'].anims).toHaveLength(1);
    });

    it('still buzzes but does not settle under reduced motion', () => {
        flags.reduced = true;
        game.handleSubmitGuess();
        game.handleSubmitAck();
        expect(els['submit-btn'].anims).toHaveLength(0);
        expect(vibrate).toHaveBeenCalledTimes(1);
    });

    it('springs the year on change, replacing a running spring', () => {
        game.initYearSelector();
        const slider = els['year-slider'];
        slider.fire('input', slider);
        slider.fire('input', slider);
        const anims = els['year-display-arc'].anims;
        expect(anims).toHaveLength(2);
        expect(anims[0].cancel).toHaveBeenCalled();
        expect(Object.keys(anims[1].frames[0])).toEqual(['transform']);
    });
});

describe('#3365 phone reveal', () => {
    const SONG = { year: 1988, title: 'T', artist: 'A' };
    const LB = [
        { rank: 1, name: 'Anna', score: 220, rank_change: 3 },
        { rank: 2, name: 'Lena', score: 200, rank_change: -1 },
    ];
    const frame = (extra) => Object.assign({ phase: 'REVEAL', round: 3, song: SONG, leaderboard: LB, players: [] }, extra);
    let rolled;

    beforeEach(() => {
        flags.reduced = false;
        vi.useFakeTimers();
        ids(['correct-year', 'reveal-leaderboard-list', 'reveal-view']);
        state.motionGate = U.createMotionGate({ reduced: () => flags.reduced });
        rolled = vi.spyOn(U, 'rollYear');
        reveal.stopRevealStaging();
        previousState.leaderboard = ['Lena', 'Anna'];
        previousState.players = { Anna: { score: 120 }, Lena: { score: 190 } };
    });
    afterEach(() => {
        reveal.stopRevealStaging();
        rolled.mockRestore();
        delete state.motionGate;
        vi.useRealTimers();
    });

    const enter = () => {
        state.motionGate.enter('PLAYING', 3);
        state.motionGate.enter('REVEAL', 3);
    };

    it('rolls the year once, shorter than the TV, not again on a repeat', () => {
        enter();
        reveal.updateRevealView(frame());
        reveal.updateRevealView(frame());
        vi.advanceTimersByTime(3000);   // #3370: it starts late, with the TV
        expect(rolled).toHaveBeenCalledTimes(1);
        const opts = rolled.mock.calls[0][2];
        expect(opts.base + 3 * opts.step).toBeLessThan(1120);
    });

    it('shows a late phone the year at once', () => {
        state.motionGate.enter('REVEAL', 3);
        reveal.updateRevealView(frame());
        expect(rolled).not.toHaveBeenCalled();
        expect(els['correct-year'].textContent).toBe(1988);
    });

    it('shows the year at once under reduced motion', () => {
        flags.reduced = true;
        enter();
        reveal.updateRevealView(frame());
        expect(rolled).not.toHaveBeenCalled();
        expect(els['correct-year'].textContent).toBe(1988);
    });

    it.each([
        ['Title & Artist', { title_artist_mode: true }],
        ['a voided round', { round_voided: true }],
    ])('does not roll in %s', (_, extra) => {
        enter();
        reveal.updateRevealView(frame(extra));
        expect(rolled).not.toHaveBeenCalled();
    });

    it('does not break on a missing year', () => {
        enter();
        reveal.updateRevealView(frame({ song: { title: 'T' } }));
        expect(els['correct-year'].textContent).toBe('????');
    });

    it('keeps the standings nodes across a repeated render', () => {
        const list = els['reveal-leaderboard-list'];
        enter();
        reveal.renderRevealStandings(frame());
        const first = list.innerHTML;
        list.innerHTML = 'kept';
        reveal.renderRevealStandings(frame());
        expect(list.innerHTML).toBe('kept');
        expect(first).toContain('rstand-row');
    });

    it('holds the old total and travels on the standings beat, once', () => {
        const list = els['reveal-leaderboard-list'];
        const totals = [makeEl('t0'), makeEl('t1')];
        const rows = [Object.assign(makeEl('r0'), { offsetTop: 0 }), Object.assign(makeEl('r1'), { offsetTop: 60 })];
        list.querySelectorAll = (sel) => (sel === '.rstand-total' ? totals : rows);
        enter();
        reveal.renderRevealStandings(frame());
        expect(totals[0].textContent).toBe(120);
        expect(rows[0].anims).toHaveLength(0);
        vi.advanceTimersByTime(3000);
        expect(rows[0].anims[0].frames[0].transform).toBe('translateY(60px)');
        expect(rows[1].anims[0].frames[0].transform).toBe('translateY(-60px)');
        reveal.renderRevealStandings(frame());
        vi.advanceTimersByTime(3000);
        expect(rows[0].anims).toHaveLength(1);
    });

    it('moves nothing for a late phone', () => {
        const list = els['reveal-leaderboard-list'];
        const totals = [makeEl('t0'), makeEl('t1')];
        list.querySelectorAll = (sel) => (sel === '.rstand-total' ? totals : []);
        state.motionGate.enter('REVEAL', 3);
        reveal.renderRevealStandings(frame());
        vi.advanceTimersByTime(4000);
        expect(totals[0].textContent).toBe('');
    });
});
