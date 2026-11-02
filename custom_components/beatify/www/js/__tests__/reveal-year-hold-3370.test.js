/**
 * #3370 - on a live reveal the phone's reel stops with the TV's, and until then
 * nothing on the phone gives the year away. The shipped player module, gate and
 * reel run; only the imports and the DOM are stubbed. The clock is fake, so the
 * numbers below are the ones the code schedules.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const flags = vi.hoisted(() => ({ reduced: false, confetti: [] }));

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
    const node = {
        id, textContent: '', innerHTML: '', style: {}, attrs: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
        },
        animate: () => ({ cancel() {} }),
        setAttribute: (k, v) => { node.attrs[k] = v; },
        removeAttribute: (k) => { delete node.attrs[k]; },
        getAttribute: (k) => node.attrs[k],
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {},
        closest: () => null,
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
        triggerConfetti: (type) => flags.confetti.push(type || 'default'),
        stopConfetti: () => {},
    });
});

const reveal = await import('../player-reveal.js');
const { state, previousState } = await import('../player-utils.js');

const GUESSES = { all_guesses: [{ name: 'Lena', guess: 1990, years_off: 2 }] };
const EMOTIONS = {
    exact: ['x'], exactSub: ['x'], close: ['x'], closeSub: ['x'],
    wrong: ['x'], wrongSub: ['x'], missed: ['x'], missedSub: ['x'],
};
const frame = (extra) => Object.assign({
    phase: 'REVEAL', round: 3, reveal_started_at: 1000,
    song: { year: 1988, title: 'T', artist: 'A' },
    round_analytics: GUESSES,
    players: [{ name: 'Lena', guess: 1990, years_off: 2, round_score: 5 }],
}, extra);

describe('#3370 tvYearReelStopMs - when the TV reel really stops', () => {
    const num = (name) => {
        const m = readSource('dashboard.js').match(new RegExp(`var ${name} = (\\d+);`));
        if (!m) throw new Error(`dashboard.js no longer declares ${name}`);
        return +m[1];
    };
    const reel = () => num('REVEAL_REEL_BASE_MS') + 3 * num('REVEAL_REEL_STEP_MS');
    const wipe = () => num('SCENE_WIPE_IN_MS');

    it('with guesses: wipe, guesses landing, reel, from the dashboard\'s own constants', () => {
        expect(U.tvYearReelStopMs(frame())).toBe(wipe() + num('REVEAL_REEL_AT_MS') + reel());
        expect(U.tvYearReelStopMs(frame())).toBe(2620);
    });

    it('without guesses the TV has nothing to land, so it stops sooner', () => {
        const none = frame({ round_analytics: { all_guesses: [] } });
        expect(U.tvYearReelStopMs(none)).toBe(wipe() + num('REVEAL_LAND_AT_MS') + reel());
        expect(U.tvYearReelStopMs(none)).toBe(1520);
        expect(U.tvYearReelStopMs(frame({ round_analytics: undefined }))).toBe(1520);
    });

    it('counts a guess the way the TV axis does: only a numeric one is a dot', () => {
        const blank = frame({ round_analytics: { all_guesses: [{ name: 'Lena', guess: null }, null] } });
        expect(U.tvYearReelStopMs(blank)).toBe(1520);
    });

    it.each([
        ['Title & Artist', { title_artist_mode: true }],
        ['a voided round', { round_voided: true }],
        ['no year', { song: { title: 'T' } }],
        ['year zero', { song: { year: 0 } }],
    ])('rolls no reel in %s', (_, extra) => {
        expect(U.tvYearReelStopMs(frame(extra))).toBe(0);
    });
});

describe('#3370 the phone holds the year back', () => {
    let rolled;

    beforeEach(() => {
        flags.reduced = false;
        flags.confetti.length = 0;
        vi.useFakeTimers();
        els = {};
        ['correct-year', 'reveal-view', 'reveal-emotion', 'reveal-leaderboard-list']
            .forEach((id) => { els[id] = makeEl(id); });
        els['reveal-emotion'].classList.add('duel-emotion');
        state.motionGate = U.createMotionGate({ reduced: () => flags.reduced });
        rolled = vi.spyOn(U, 'rollYear');
        vi.spyOn(U, 't').mockImplementation((k) => (k === 'reveal.emotions' ? EMOTIONS : k));
        reveal.stopRevealStaging();
        previousState.leaderboard = [];
        previousState.players = {};
    });
    afterEach(() => {
        reveal.stopRevealStaging();
        vi.restoreAllMocks();
        delete state.motionGate;
        vi.useRealTimers();
    });

    const held = () => els['reveal-view'].classList.contains('reveal-year-hold');
    const yearShown = () => els['correct-year'].textContent;
    const stage = () => els['reveal-view'].attrs['data-reveal-stage'];

    /** What player-core does on the frame: gate, beats, then the render. */
    const arrive = (data) => {
        state.motionGate.enter('REVEAL', 3);
        if (state.motionGate.isLive()) reveal.startRevealStaging(data);
        reveal.updateRevealView(data);
    };
    const live = (data) => {
        state.motionGate.enter('PLAYING', 3);
        arrive(data);
    };

    it('with guesses: the reel ends at 2620 ms, exactly when the TV reel does', () => {
        live(frame());
        vi.advanceTimersByTime(1929);
        expect(rolled).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(rolled).toHaveBeenCalledTimes(1);
        const opts = rolled.mock.calls[0][2];
        expect(1930 + opts.base + 3 * opts.step).toBe(U.tvYearReelStopMs(frame()));
        vi.advanceTimersByTime(689);
        expect(held()).toBe(true);
        vi.advanceTimersByTime(1);
        expect(held()).toBe(false);
    });

    it('without guesses: 830 ms hold, the reel ends at 1520 ms', () => {
        live(frame({ round_analytics: { all_guesses: [] }, players: [] }));
        vi.advanceTimersByTime(829);
        expect(rolled).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(rolled).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(689);
        expect(held()).toBe(true);
        vi.advanceTimersByTime(1);
        expect(held()).toBe(false);
    });

    it('keeps the year out of the DOM until the reel starts', () => {
        live(frame());
        expect(yearShown()).toBe('????');
        expect(els['correct-year'].innerHTML).toBe('');
        expect(els['correct-year'].attrs['aria-label']).toBeUndefined();
        vi.advanceTimersByTime(1000);
        expect(yearShown()).toBe('????');
    });

    it('a repeated frame during the hold shows nothing and starts nothing', () => {
        live(frame());
        vi.advanceTimersByTime(500);
        arrive(frame());
        expect(yearShown()).toBe('????');
        expect(held()).toBe(true);
        vi.advanceTimersByTime(1430);
        arrive(frame());
        vi.advanceTimersByTime(2000);
        arrive(frame());
        expect(rolled).toHaveBeenCalledTimes(1);
        expect(held()).toBe(false);
        expect(yearShown()).toBe(1988);
    });

    it('a re-stamped reveal_started_at does not end the hold', () => {
        live(frame());
        vi.advanceTimersByTime(500);
        arrive(frame({ reveal_started_at: 2000 }));
        expect(held()).toBe(true);
        expect(yearShown()).toBe('????');
    });

    it('moves "who got it right" behind the reel, and leaves the standings beat', () => {
        live(frame());
        vi.advanceTimersByTime(2699);
        expect(stage()).toBe('1');
        vi.advanceTimersByTime(1);
        expect(stage()).toBe('2');
        vi.advanceTimersByTime(299);
        expect(stage()).toBe('2');
        vi.advanceTimersByTime(1);
        expect(stage()).toBe('3');
    });

    it.each([
        ['Title & Artist', { title_artist_mode: true }],
        ['a voided round', { round_voided: true }],
    ])('%s holds nothing and keeps the beats', (_, extra) => {
        live(frame(extra));
        expect(held()).toBe(false);
        vi.advanceTimersByTime(1499);
        expect(stage()).toBe('1');
        vi.advanceTimersByTime(1);
        expect(stage()).toBe('2');
        vi.advanceTimersByTime(3000);
        expect(rolled).not.toHaveBeenCalled();
    });

    it('no year holds nothing and shows the fallback', () => {
        live(frame({ song: { title: 'T' }, round_analytics: { all_guesses: [] } }));
        expect(held()).toBe(false);
        expect(yearShown()).toBe('????');
        vi.advanceTimersByTime(3000);
        expect(rolled).not.toHaveBeenCalled();
    });

    it('a late phone or a reload gets the final picture at once', () => {
        arrive(frame());
        expect(held()).toBe(false);
        expect(yearShown()).toBe(1988);
    });

    it('reduced motion gets the final picture at once', () => {
        flags.reduced = true;
        live(frame());
        expect(held()).toBe(false);
        expect(yearShown()).toBe(1988);
    });

    it('a reconnect mid-hold ends it and shows the final picture', () => {
        live(frame());
        vi.advanceTimersByTime(500);
        state.motionGate.reset();
        arrive(frame());
        expect(held()).toBe(false);
        expect(stage()).toBeUndefined();
        expect(yearShown()).toBe(1988);
        vi.advanceTimersByTime(3000);
        expect(rolled).not.toHaveBeenCalled();
    });

    it('voiding the round mid-hold ends it', () => {
        live(frame());
        vi.advanceTimersByTime(500);
        reveal.updateRevealView(frame({ round_voided: true }));
        expect(held()).toBe(false);
        vi.advanceTimersByTime(3000);
        expect(rolled).not.toHaveBeenCalled();
    });

    it('a host correcting the year ends it on the new year, even mid-reel', () => {
        live(frame());
        vi.advanceTimersByTime(2000);
        reveal.updateRevealView(frame({ song: { year: 1991 } }));
        expect(held()).toBe(false);
        expect(yearShown()).toBe(1991);
    });

    it('the round moving on leaves nothing hidden and fires nothing later', () => {
        live(frame({ players: [{ name: 'Lena', guess: 1988, years_off: 0 }] }));
        vi.advanceTimersByTime(500);
        reveal.stopRevealCountdown();
        expect(held()).toBe(false);
        vi.advanceTimersByTime(5000);
        expect(rolled).not.toHaveBeenCalled();
        expect(flags.confetti).toEqual([]);
    });

    it('an exact guess celebrates when the reel stops, not before', () => {
        live(frame({ players: [{ name: 'Lena', guess: 1988, years_off: 0 }] }));
        vi.advanceTimersByTime(2619);
        expect(flags.confetti).toEqual([]);
        vi.advanceTimersByTime(1);
        expect(flags.confetti).toEqual(['default']);
    });

    it('a new record waits too, and a repeated frame does not downgrade it', () => {
        const rec = frame({
            players: [{ name: 'Lena', guess: 1988, years_off: 0 }],
            game_performance: { is_new_record: true },
        });
        live(rec);
        arrive(rec);
        expect(flags.confetti).toEqual([]);
        vi.advanceTimersByTime(2620);
        expect(flags.confetti).toEqual(['record']);
    });

    it('a late phone with an exact guess still celebrates straight away', () => {
        arrive(frame({ players: [{ name: 'Lena', guess: 1988, years_off: 0 }] }));
        expect(flags.confetti).toEqual(['default']);
    });
});

describe('#3370 what the hold hides', () => {
    const css = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
    const rule = css.slice(css.indexOf('#reveal-view.reveal-year-hold'));
    const selectors = rule.slice(0, rule.indexOf('{'));

    it('hides it with visibility, so the layout does not jump', () => {
        expect(rule.slice(rule.indexOf('{'), rule.indexOf('}'))).toContain('visibility: hidden');
    });

    it.each([
        '.duel-emotion',           // "So close!", in the tier colour
        '.duel-gap',               // your guess plus the gap is the year
        '#reveal-chip-row',        // bet won or lost
        '#reveal-sd-standing',     // you are out
        '.score-row',              // points, "2 years off", breakdown sheet
        '#reveal-streak-shield',   // a shield only fires on a wrong answer
        '#collection-section',     // the new card prints the year
        '#fun-fact-container',     // fun facts and chart badges name years
        '#round-stats-btn',        // opens the sheet with all guesses
        '.reveal-report-row',      // report flow carries the year
    ])('on the player page: %s', (sel) => {
        expect(selectors).toContain(`#reveal-view.reveal-year-hold ${sel}`);
    });

    it.each([
        '#admin-reveal-emotion', '#admin-fun-fact-container', '#admin-reveal-personal',
        '#admin-reveal-arc-chip-row', '.guesses-section', '.leaderboard-section',
    ])('on the admin page: %s', (sel) => {
        expect(selectors).toContain(`#admin-reveal-section.reveal-year-hold ${sel}`);
    });

    it('the two standings beats stay behind the stage attribute', () => {
        const html = readFileSync(join(WWW_DIR, 'player.html'), 'utf8');
        expect(html).toMatch(/id="reveal-whogot"[^>]*data-stage="2"/);
        expect(html).toMatch(/id="reveal-leaderboard"[^>]*data-stage="3"/);
    });
});

describe('#3370 the host page', () => {
    const ADMIN = readSource('admin.js');
    let els2;
    let hold;
    let gate;

    const build = () => {
        els2 = { 'admin-reveal-section': makeEl('s'), 'admin-reveal-correct-year': makeEl('y') };
        gate = U.createMotionGate({ reduced: () => false });
        hold = evaluate(
            [declaration(ADMIN, 'clearAdminYearHold'), declaration(ADMIN, 'syncAdminYearHold')],
            '{ sync: syncAdminYearHold, clear: clearAdminYearHold }',
            {
                document: { getElementById: (id) => els2[id] || null },
                utils: U,
                _adminMotionGate: gate,
                _adminYearHold: null,
            },
        );
    };

    beforeEach(() => { vi.useFakeTimers(); build(); });
    afterEach(() => { vi.useRealTimers(); });

    const isHeld = () => els2['admin-reveal-section'].classList.contains('reveal-year-hold');

    it('holds a live reveal until the TV reel stops, then writes the year', () => {
        gate.enter('PLAYING', 3);
        gate.enter('REVEAL', 3);
        expect(hold.sync(frame())).toBe(true);
        expect(isHeld()).toBe(true);
        vi.advanceTimersByTime(2619);
        expect(hold.sync(frame())).toBe(true);
        vi.advanceTimersByTime(1);
        expect(isHeld()).toBe(false);
        expect(els2['admin-reveal-correct-year'].textContent).toBe('1988');
        expect(hold.sync(frame())).toBe(false);
    });

    it('holds nothing for a page that did not watch the round end', () => {
        gate.enter('REVEAL', 3);
        expect(hold.sync(frame())).toBe(false);
        expect(isHeld()).toBe(false);
    });

    it.each([
        ['Title & Artist', { title_artist_mode: true }],
        ['a voided round', { round_voided: true }],
    ])('holds nothing in %s', (_, extra) => {
        gate.enter('PLAYING', 3);
        gate.enter('REVEAL', 3);
        expect(hold.sync(frame(extra))).toBe(false);
    });

    it('a reconnect or a changed year ends the hold', () => {
        gate.enter('PLAYING', 3);
        gate.enter('REVEAL', 3);
        hold.sync(frame());
        expect(hold.sync(frame({ song: { year: 1991 } }))).toBe(false);
        expect(isHeld()).toBe(false);
        gate.enter('PLAYING', 4);
        gate.enter('REVEAL', 4);
        hold.sync(frame());
        expect(isHeld()).toBe(true);
        gate.reset();
        gate.enter('REVEAL', 4);
        expect(hold.sync(frame())).toBe(false);
        expect(isHeld()).toBe(false);
    });

    it('leaving the reveal leaves nothing hidden', () => {
        gate.enter('PLAYING', 3);
        gate.enter('REVEAL', 3);
        hold.sync(frame());
        hold.clear();
        expect(isHeld()).toBe(false);
    });

    it('is wired to the render and the socket', () => {
        const render = declaration(ADMIN, 'renderAdminState');
        expect(render).toContain('_adminMotionGate.enter(data.phase, data.round)');
        expect(render).toContain('clearAdminYearHold()');
        expect(declaration(ADMIN, 'showAdminRevealView')).toContain('syncAdminYearHold(data)');
        expect(ADMIN).toMatch(/onSocketClosed:.*_adminMotionGate\.reset\(\)/);
        expect(readSource('admin/api.js')).toContain('deps.onSocketClosed()');
    });
});
