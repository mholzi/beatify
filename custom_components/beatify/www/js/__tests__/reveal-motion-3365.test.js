/**
 * #3365 - motion for the reveal, TV scene changes, podium and guess input.
 *
 * The animations themselves are for the browser and the live test. What can go
 * wrong silently is the logic around them, and that is what runs here against
 * the shipped code: the order things happen in, that a repeated render never
 * starts anything twice, that a late client or reduced motion gets the final
 * picture, and that missing data breaks nothing.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { el } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;
const DASHBOARD = readSource('dashboard.js');
const CONSTS = `
    var REVEAL_LAND_AT_MS = 180, REVEAL_LAND_TOTAL_MS = 1000, REVEAL_LAND_MS = 420,
        REVEAL_REEL_AT_MS = 1280, REVEAL_REEL_BASE_MS = 520, REVEAL_REEL_STEP_MS = 200,
        REVEAL_GLOW_AFTER_REEL_MS = 80, REVEAL_ROWS_AFTER_REEL_MS = 280, ROW_TRAVEL_MS = 620,
        MOTION_EASE = 'ease', _revealReel = null, _revealReelEndsAt = 0, _rowCount = null;
    var SCENE_WIPE_PHASES = { LOBBY: true, PLAYING: true, REVEAL: true, END: true };
    var SCENE_WIPE_IN_MS = 220, SCENE_WIPE_OUT_MS = 260;
    var PODIUM_BUILD = [['podium-3', 200], ['podium-2', 800], ['podium-1', 1800]];
    var PODIUM_RISE_MS = 520, PODIUM_BUILD_MS = 2320;
`;
const src = (name) => declaration(DASHBOARD, name, 'dashboard.js');

/** An element that records what it was asked to animate. */
function animated(id, extra) {
    const node = el(id);
    node.anims = [];
    node.animate = (frames, opts) => {
        const a = { frames, opts, cancel: vi.fn() };
        node.anims.push(a);
        return a;
    };
    return Object.assign(node, extra);
}

describe('#3365 createMotionGate - who gets to see the motion', () => {
    const gate = (reduced = false) => U.createMotionGate({ reduced: () => reduced });

    it('is live when REVEAL follows PLAYING of the same round', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        expect(g.enter('REVEAL', 3)).toBe(true);
        expect(g.once('reel')).toBe(true);
    });

    it('starts nothing twice when the same phase renders again', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        g.enter('REVEAL', 3);
        expect(g.once('reel')).toBe(true);
        g.enter('REVEAL', 3);
        g.enter('REVEAL', 3);
        expect(g.once('reel')).toBe(false);
        expect(g.isLive()).toBe(true);
    });

    it('gives a client that loads into a reveal the final picture', () => {
        const g = gate();
        expect(g.enter('REVEAL', 3)).toBe(false);
        expect(g.once('reel')).toBe(false);
    });

    it('gives a client back from a dropped socket the final picture', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        g.reset();
        expect(g.enter('REVEAL', 3)).toBe(false);
    });

    it('is not live when rounds were missed, or after a pause', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        expect(g.enter('REVEAL', 4)).toBe(false);
        g.enter('PAUSED', 4);
        expect(g.enter('REVEAL', 4)).toBe(false);
    });

    it('never plays under reduced motion', () => {
        const g = gate(true);
        g.enter('PLAYING', 3);
        expect(g.enter('REVEAL', 3)).toBe(false);
        expect(g.once('reel')).toBe(false);
    });

    it('is live on END only when a round came before', () => {
        const g = gate();
        expect(g.enter('END', 9)).toBe(false);
        const h = gate();
        h.enter('REVEAL', 9);
        expect(h.enter('END', 9)).toBe(true);
    });

    it('plays again for the next round', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        g.enter('REVEAL', 3);
        g.once('reel');
        g.enter('PLAYING', 4);
        g.enter('REVEAL', 4);
        expect(g.once('reel')).toBe(true);
    });
});

describe('#3365 guessLandingPlan', () => {
    it('lands the furthest first and the closest last', () => {
        const plan = U.guessLandingPlan([2, 9, 0, 5], 1000, 420);
        expect(plan.map((s) => s.index)).toEqual([1, 3, 0, 2]);
        expect(plan[0].delay).toBe(0);
        expect(plan[1].delay).toBeGreaterThan(0);
    });

    it.each([2, 4, 12, 40])('takes the same total time for %i players', (n) => {
        const plan = U.guessLandingPlan(Array(n).fill(1), 1000, 420);
        expect(plan[n - 1].delay + 420).toBe(1000);
    });

    it('survives one guess, no guesses and junk', () => {
        expect(U.guessLandingPlan([3], 1000, 420)).toEqual([{ index: 0, delay: 0 }]);
        expect(U.guessLandingPlan([], 1000, 420)).toEqual([]);
        expect(U.guessLandingPlan([undefined, 2], 1000, 420)[0].index).toBe(1);
    });
});

describe('#3365 rowTravelPlan', () => {
    const rows = (...keys) => keys.map((key, index) => ({ key, index }));

    it('moves a row from its real old place, as many places as it gained', () => {
        expect(U.rowTravelPlan(rows('Anna', 'Micha', 'Lea'), { Micha: 0, Lea: 1, Anna: 2 })).toEqual([
            { to: 0, from: 2 }, { to: 1, from: 0 }, { to: 2, from: 1 },
        ]);
    });

    it('leaves rows alone that did not move, or have no old place', () => {
        expect(U.rowTravelPlan(rows('A', 'B'), { A: 0, B: 1 })).toEqual([]);
        expect(U.rowTravelPlan(rows('New', 'B'), { B: 1 })).toEqual([]);
        expect(U.rowTravelPlan(rows('A'), null)).toEqual([]);
    });

    it('clamps an old place that is not on screen to the nearest shown row', () => {
        // Phone: podium plus your own row at place 8. You were 6th.
        const shown = [{ key: 'A', index: 0 }, { key: 'B', index: 1 }, { key: 'C', index: 2 }, { key: 'Me', index: 7 }];
        const order = { A: 7, B: 0, C: 1, Me: 5 };
        const plan = U.rowTravelPlan(shown, order);
        expect(plan).toContainEqual({ to: 0, from: 3 });
        expect(plan.find((m) => m.to === 3)).toBeUndefined();
    });
});

describe('#3365 rollYear', () => {
    let host;
    let cols;
    const OPTS = { delay: 100, base: 520, step: 200 };

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('setTimeout', setTimeout);
        cols = [];
        host = animated('year', {
            querySelectorAll: () => {
                cols = (host.innerHTML.match(/year-reel-col/g) || []).map((_, i) => {
                    const translate = new RegExp('translateY\\(-(\\d+)em\\)', 'g');
                    const matches = [...host.innerHTML.matchAll(translate)];
                    return animated('col' + i, { style: { transform: 'translateY(-' + matches[i][1] + 'em)' } });
                });
                return cols;
            },
        });
    });
    afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

    it('ends every column on the real digit', () => {
        ['1', '9', '8', '0'].forEach((d, i) => {
            const digits = U.yearReelDigits(d, i);
            expect(digits[digits.length - 1]).toBe(d);
        });
    });

    it('stops the digits left to right, later columns longer', () => {
        U.rollYear(host, 1988, OPTS);
        const durations = cols.map((c) => c.anims[0].opts.duration);
        expect(durations).toEqual([520, 720, 920, 1120]);
        cols.forEach((c) => {
            expect(c.anims[0].opts.delay).toBe(100);
            expect(c.anims[0].opts.fill).toBe('backwards');
            // Only ever transform.
            Object.keys(c.anims[0].frames[0]).forEach((k) => expect(k).toBe('transform'));
        });
    });

    it('rests on the plain text when it stops, even with no frame ever run', () => {
        const reel = U.rollYear(host, 1988, OPTS);
        expect(reel.active()).toBe(true);
        expect(host.attrs['aria-label']).toBe('1988');
        expect(host.classList.contains('year-reel-host')).toBe(true);
        vi.advanceTimersByTime(100 + 1120 + 60);
        expect(host.classList.contains('year-reel-host')).toBe(false);
        expect(reel.active()).toBe(false);
        expect(host.textContent).toBe('1988');
        expect(host.attrs['aria-label']).toBeUndefined();
    });

    it('does not write over the element once it has stopped', () => {
        const reel = U.rollYear(host, 1988, OPTS);
        reel.finish();
        host.textContent = '2001';
        reel.finish();
        expect(host.textContent).toBe('2001');
    });

    it.each(['????', 'undefined', ''])('shows %j as text, no reel', (year) => {
        const reel = U.rollYear(host, year, OPTS);
        expect(reel.active()).toBe(false);
        expect(host.textContent).toBe(year);
        expect(host.innerHTML).toBe('');
    });

    it('falls back to the text where the browser cannot animate', () => {
        const plain = el('year');
        const reel = U.rollYear(plain, 1988, OPTS);
        expect(reel.active()).toBe(false);
        expect(plain.textContent).toBe('1988');
    });
});

describe('#3365 TV reveal sequence', () => {
    function stage(offs) {
        const dots = offs.map((off, i) => {
            const d = animated('dot' + i);
            d.setAttribute('data-off', off);
            return d;
        });
        const span = animated('span');
        const marker = animated('marker');
        const plot = el('guess-axis-plot');
        plot.querySelectorAll = (sel) => (sel === '.guess-axis-dot' ? dots : [span]);
        plot.querySelector = (sel) => (sel === '.guess-axis-marker' ? marker : null);
        const row = animated('reveal-year-row');
        const yearEl = el('reveal-year');
        const timers = [];
        const roll = vi.fn(() => ({ active: () => true, finish() {}, year: '1988' }));
        const play = evaluate(CONSTS + src('playRevealSequence'), 'playRevealSequence', {
            document: { getElementById: (id) => ({ 'guess-axis-plot': plot, 'reveal-year': yearEl, 'reveal-year-row': row })[id] },
            utils: { guessLandingPlan: U.guessLandingPlan, rollYear: roll },
            _revealStageTimers: timers,
        });
        return { play, dots, span, marker, plot, row, roll };
    }

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('lands the guesses before the line and the reel, furthest first', () => {
        const s = stage([2, 9, 0]);
        s.play(1988);
        const start = (d) => d.anims[0].opts.delay;
        expect(start(s.dots[1])).toBeLessThan(start(s.dots[0]));
        expect(start(s.dots[0])).toBeLessThan(start(s.dots[2]));
        const lastLanding = start(s.dots[2]) + s.dots[2].anims[0].opts.duration;
        expect(s.marker.anims[0].opts.delay).toBeGreaterThanOrEqual(lastLanding);
        expect(s.roll.mock.calls[0][2].delay).toBe(s.marker.anims[0].opts.delay);
    });

    it('holds the colours and the span back until the reel stands', () => {
        const s = stage([2, 0]);
        const rowsAt = s.play(1988);
        expect(s.plot.classList.contains('guess-axis--hold')).toBe(true);
        expect(s.span.anims[0].opts.delay).toBe(2480);
        vi.advanceTimersByTime(2479);
        expect(s.plot.classList.contains('guess-axis--hold')).toBe(true);
        vi.advanceTimersByTime(1);
        expect(s.plot.classList.contains('guess-axis--hold')).toBe(false);
        // Only the closest guess pops.
        expect(s.dots[1].anims).toHaveLength(2);
        expect(s.dots[0].anims).toHaveLength(1);
        expect(rowsAt).toBe(2680);
    });

    it('does not wait for guesses that are not there', () => {
        const s = stage([]);
        const rowsAt = s.play(1988);
        expect(s.roll.mock.calls[0][2].delay).toBe(180);
        expect(s.plot.classList.contains('guess-axis--hold')).toBe(false);
        expect(rowsAt).toBe(180 + 1120 + 280);
    });

    it('animates transform and opacity only', () => {
        const s = stage([3, 1]);
        s.play(1988);
        vi.advanceTimersByTime(3000);
        [...s.dots, s.span, s.marker, s.row].forEach((node) => {
            node.anims.forEach((a) => a.frames.forEach((f) => {
                Object.keys(f).filter((k) => k !== 'offset').forEach((k) => expect(['transform', 'opacity']).toContain(k));
            }));
        });
    });
});

describe('#3365 TV standings', () => {
    function board() {
        const row = (key, top) => {
            const score = el('score-' + key);
            const node = animated('row-' + key, { offsetHeight: 40, offsetTop: top });
            node.setAttribute('data-row-key', key);
            node.querySelector = () => score;
            node.score = score;
            return node;
        };
        const rows = [row('Anna', 0), row('Micha', 44), row('Lea', 88)];
        return { container: { children: rows }, rows };
    }
    const LB = [{ name: 'Anna', score: 220 }, { name: 'Micha', score: 200 }, { name: 'Lea', score: 175 }];
    const BEFORE = { round: 3, order: { Micha: 0, Lea: 1, Anna: 2 }, score: { Micha: 190, Lea: 170, Anna: 120 } };

    function setup() {
        return evaluate(
            CONSTS + src('playRowTravel') + src('finishRowCount') + '\nvar api = { play: playRowTravel, finish: finishRowCount };',
            'api',
            { utils: { rowTravelPlan: U.rowTravelPlan } },
        );
    }

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('sends each row from its old place and holds the old score until it sets off', () => {
        const b = board();
        setup().play(b.container, LB, BEFORE, 2680);
        expect(b.rows[0].anims[0].frames[0].transform).toBe('translateY(88px)');
        expect(b.rows[1].anims[0].frames[0].transform).toBe('translateY(-44px)');
        expect(b.rows[0].anims[0].opts).toMatchObject({ delay: 2680, fill: 'backwards' });
        expect(b.rows[0].score.textContent).toBe(120);
        vi.advanceTimersByTime(2680 + 300);
        expect(b.rows[0].score.textContent).toBeGreaterThan(120);
        expect(b.rows[0].score.textContent).toBeLessThan(220);
    });

    it('ends every count on the final score', () => {
        const b = board();
        setup().play(b.container, LB, BEFORE, 100);
        vi.advanceTimersByTime(100 + 620 + 100);
        expect(b.rows.map((r) => r.score.textContent)).toEqual([220, 200, 175]);
    });

    it('leaves nothing on the old score when the sequence is cut', () => {
        const b = board();
        const api = setup();
        api.play(b.container, LB, BEFORE, 2680);
        api.finish();
        expect(b.rows.map((r) => r.score.textContent)).toEqual([220, 200, 175]);
        vi.advanceTimersByTime(5000);
        expect(b.rows.map((r) => r.score.textContent)).toEqual([220, 200, 175]);
    });

    it('does not touch hidden rows of a capped board', () => {
        const b = board();
        b.rows[2].offsetHeight = 0;
        setup().play(b.container, LB, BEFORE, 0);
        expect(b.rows[2].anims).toHaveLength(0);
    });
});

describe('#3365 scene wipe', () => {
    const should = (...args) => evaluate(CONSTS + src('shouldWipeScene'), 'shouldWipeScene')(...args);

    it('wipes between the scenes the room watches', () => {
        expect(should('PLAYING', 'REVEAL', false)).toBe(true);
        expect(should('LOBBY', 'PLAYING', false)).toBe(true);
        expect(should('REVEAL', 'END', false)).toBe(true);
    });

    it('does not wipe on a first frame, a repeat, a pause or reduced motion', () => {
        expect(should(null, 'REVEAL', false)).toBe(false);
        expect(should('REVEAL', 'REVEAL', false)).toBe(false);
        expect(should('PLAYING', 'PAUSED', false)).toBe(false);
        expect(should('PAUSED', 'PLAYING', false)).toBe(false);
        expect(should('PLAYING', 'REVEAL', true)).toBe(false);
    });

    function frames(wipeEl) {
        const render = vi.fn();
        const apply = evaluate(
            CONSTS + 'var _sceneWipeHold = null, _lastScenePhase = null;' +
                src('shouldWipeScene') + src('playSceneWipe') + src('_applyFrame'),
            '_applyFrame',
            {
                document: { getElementById: () => wipeEl },
                _reducedMotion: () => false,
                _renderFrame: render,
            },
        );
        return { apply, render };
    }

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('draws the new scene once, under the cover, with the newest frame', () => {
        const wipe = animated('dashboard-wipe');
        const { apply, render } = frames(wipe);
        apply({ phase: 'PLAYING', game_id: 'g', round: 1 });
        expect(render).toHaveBeenCalledTimes(1);

        apply({ phase: 'REVEAL', game_id: 'g', round: 1, v: 1 });
        apply({ phase: 'REVEAL', game_id: 'g', round: 1, v: 2 });
        expect(render).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(220);
        expect(render).toHaveBeenCalledTimes(2);
        expect(render.mock.calls[1][0].v).toBe(2);
        // Uncovers in the same task; only ever transform.
        expect(wipe.anims).toHaveLength(2);
        wipe.anims.forEach((a) => a.frames.forEach((f) => expect(Object.keys(f)).toEqual(['transform'])));
        expect(wipe.anims[0].cancel).toHaveBeenCalled();
    });

    it('does not wipe again for a repeated frame of the same scene', () => {
        const wipe = animated('dashboard-wipe');
        const { apply, render } = frames(wipe);
        apply({ phase: 'REVEAL', game_id: 'g', round: 1 });
        apply({ phase: 'REVEAL', game_id: 'g', round: 1, v: 2 });
        expect(wipe.anims).toHaveLength(0);
        expect(render).toHaveBeenCalledTimes(2);
    });

    it('draws straight away when the browser cannot animate', () => {
        const { apply, render } = frames(el('dashboard-wipe'));
        apply({ phase: 'PLAYING', game_id: 'g', round: 1 });
        apply({ phase: 'REVEAL', game_id: 'g', round: 1 });
        expect(render).toHaveBeenCalledTimes(2);
    });

    it('uncovers even if drawing the scene throws', () => {
        const wipe = animated('dashboard-wipe');
        const { apply, render } = frames(wipe);
        apply({ phase: 'PLAYING', game_id: 'g', round: 1 });
        render.mockImplementationOnce(() => { throw new Error('boom'); });
        apply({ phase: 'REVEAL', game_id: 'g', round: 1 });
        expect(() => vi.advanceTimersByTime(220)).toThrow('boom');
        expect(wipe.anims).toHaveLength(2);
    });
});

describe('#3365 podium', () => {
    const places = {};
    const build = () => {
        ['podium-1', 'podium-2', 'podium-3'].forEach((c) => { places[c] = animated(c); });
        return evaluate(CONSTS + src('playPodiumBuild'), 'playPodiumBuild', {
            document: { querySelector: (sel) => places[sel.split('.')[1]] || null },
        });
    };

    it('builds 3, 2, pause, 1', () => {
        build()(0);
        const at = (c) => places[c].anims[0].opts.delay;
        expect(at('podium-3')).toBeLessThan(at('podium-2'));
        const gapToSecond = at('podium-2') - at('podium-3');
        const gapToWinner = at('podium-1') - at('podium-2');
        expect(gapToWinner).toBeGreaterThan(gapToSecond);
        expect(places['podium-3'].anims[0].opts.fill).toBe('backwards');
    });

    it('waits for the closing moment to uncover the stage', () => {
        build()(3600);
        expect(places['podium-3'].anims[0].opts.delay).toBe(3800);
    });

    it('survives a missing stand', () => {
        const play = evaluate(CONSTS + src('playPodiumBuild'), 'playPodiumBuild', {
            document: { querySelector: () => null },
        });
        expect(() => play(0)).not.toThrow();
    });

    function endView(gate, confetti, timers) {
        return evaluate(CONSTS + 'var endConfettiPlayedFor = null;' + src('renderEndView'), 'renderEndView', {
            document: { getElementById: () => null, querySelector: () => null },
            utils: { podiumStands: (lb) => ({ stands: lb.slice(0, 3), rest: lb.slice(3) }), podiumMedal: () => '', t: (k) => k, escapeHtml: (s) => s },
            _motionGate: gate,
            playClosingMoment: () => false,
            playPodiumBuild: gate.spy,
            renderSuddenDeathLastStanding: () => {},
            renderStatsComparison: () => {},
            renderSuperlatives: () => {},
            renderHighlights: () => {},
            endAvatarGradient: () => '',
            triggerConfetti: confetti,
            setTimeout: (fn, ms) => { timers.push(ms); fn(); },
        });
    }
    const END = { game_id: 'g', leaderboard: [{ name: 'A', rank: 1, score: 5 }] };

    it('fires the winner confetti after the winner stands, and builds once', () => {
        const gate = U.createMotionGate();
        gate.enter('REVEAL', 9);
        gate.enter('END', 9);
        gate.spy = vi.fn();
        const confetti = vi.fn();
        const timers = [];
        const render = endView(gate, confetti, timers);
        render(END);
        render(END);
        expect(gate.spy).toHaveBeenCalledTimes(1);
        expect(timers).toEqual([2320]);
        expect(confetti).toHaveBeenCalledTimes(1);
    });

    it('shows a late client the podium as it stands', () => {
        const gate = U.createMotionGate();
        gate.enter('END', 9);
        gate.spy = vi.fn();
        const confetti = vi.fn();
        const timers = [];
        endView(gate, confetti, timers)(END);
        expect(gate.spy).not.toHaveBeenCalled();
        expect(timers).toEqual([]);
    });
});

describe('#3365 reveal confetti waits for the reel', () => {
    const body = () => {
        const text = src('renderRevealView');
        return text.slice(text.indexOf('var confettiType = null;'));
    };
    function run(gate, data, reelEndsAt) {
        const confetti = vi.fn();
        const timers = [];
        const fn = new Function('data', 'players', '_motionGate', '_revealReelEndsAt', 'triggerConfetti', '_revealStageTimers', 'setTimeout',
            "'use strict';" + body().replace(/\}\s*$/, ''));
        fn(data, data.players, gate, reelEndsAt, confetti, timers, (cb, ms) => { timers.push({ cb, ms }); return 1; });
        return { confetti, timers };
    }
    const live = () => {
        const g = U.createMotionGate();
        g.enter('PLAYING', 1);
        g.enter('REVEAL', 1);
        return g;
    };
    const EXACT = { players: [{ years_off: 0 }] };

    it('holds an exact-guess burst until the reel stands', () => {
        const { confetti, timers } = run(live(), EXACT, Date.now() + 2400);
        expect(confetti).not.toHaveBeenCalled();
        const queued = timers.find((t) => t.ms);
        expect(queued.ms).toBeGreaterThan(2000);
        queued.cb();
        expect(confetti).toHaveBeenCalledWith('exact');
    });

    it('fires a record at once when no reel runs (Title & Artist)', () => {
        const { confetti } = run(live(), { players: [], game_performance: { is_new_record: true } }, 0);
        expect(confetti).toHaveBeenCalledWith('record');
    });

    it('does not fire again on a repeated render', () => {
        const g = live();
        run(g, EXACT, 0);
        expect(run(g, EXACT, 0).confetti).not.toHaveBeenCalled();
    });

    it('does not fire for a client that came late', () => {
        const g = U.createMotionGate();
        g.enter('REVEAL', 1);
        expect(run(g, EXACT, 0).confetti).not.toHaveBeenCalled();
    });
});

describe('#3365 the TV render stays one paint per change', () => {
    it('keeps the coalescer in front of the wipe', () => {
        expect(DASHBOARD).toContain('createRenderCoalescer(_applyFrame, { isEqual: _stateRenderEqual })');
    });

    it('does not call the renderer from anywhere else', () => {
        expect(DASHBOARD.match(/_applyStateRender\(/g)).toHaveLength(2);
    });

    it('stops a running reel only for a changed answer', () => {
        const text = src('renderRevealView');
        const piece = text.slice(text.indexOf('var reelRunning'), text.indexOf("if (!reelRunning) yearEl.textContent"));
        const paint = (reel, year) => {
            const yearEl = { textContent: 'reel' };
            new Function('_revealReel', 'song', 'yearEl', `'use strict';${piece}if (!reelRunning) yearEl.textContent = song.year || '????';`)(reel, { year }, yearEl);
            return yearEl.textContent;
        };
        const running = { active: () => true, year: '1988', finish: vi.fn() };
        expect(paint(running, 1988)).toBe('reel');
        expect(running.finish).not.toHaveBeenCalled();
        expect(paint(running, 1990)).toBe(1990);
        expect(running.finish).toHaveBeenCalled();
        expect(paint(null, undefined)).toBe('????');
    });
});
