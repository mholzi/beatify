/**
 * #3379 - motion for what a round means for each player. The shipped modules
 * run; only the DOM and their imports are stubbed, and the clock is fake. Each
 * test names a way the feature could go wrong for a real person: a result that
 * lands after "who got it", a bet payout that shows a made-up number, a tally
 * that rebuilds under the thumb, a TV that animates layout.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const flags = vi.hoisted(() => ({ reduced: false }));

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.requestAnimationFrame = () => 1;
global.cancelAnimationFrame = () => {};
global.window = global.window || {};
global.window.matchMedia = () => ({ matches: flags.reduced, addEventListener: () => {} });
global.window.location = { search: '', pathname: '/', host: 'x', protocol: 'http:' };
global.window.addEventListener = () => {};
global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

function makeEl(id, extra = {}) {
    const classes = new Set();
    const node = {
        id, textContent: '', innerHTML: '', style: {}, attrs: {}, anims: [], children: [],
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
        },
        animate(frames, opts) {
            const a = { frames, opts, cancel: vi.fn() };
            node.anims.push(a);
            return a;
        },
        setAttribute: (k, v) => { node.attrs[k] = v; },
        removeAttribute: (k) => { delete node.attrs[k]; },
        getAttribute: (k) => node.attrs[k],
        querySelector: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {},
        closest: () => null,
        ...extra,
    };
    return node;
}

let els = {};
let selectors = {};
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
    querySelector: (sel) => selectors[sel] || null,
    querySelectorAll: () => [],
    body: makeEl('body'),
};

await import('../utils.js');
const U = global.window.BeatifyUtils;

vi.mock('../player-utils.js', async (orig) => {
    const real = await orig();
    return Object.assign({}, real, {
        state: { ws: { readyState: 1, send: vi.fn() }, playerName: 'Lena' },
        prefersReducedMotion: () => flags.reduced,
        triggerConfetti: () => {},
        stopConfetti: () => {},
    });
});

const reveal = await import('../player-reveal.js');
const game = await import('../player-game.js');
const end = await import('../player-end.js');
const { state, previousState } = await import('../player-utils.js');

const EMOTIONS = {
    exact: ['x'], exactSub: ['x'], close: ['x'], closeSub: ['x'],
    wrong: ['x'], wrongSub: ['x'], missed: ['x'], missedSub: ['x'],
};

beforeEach(() => {
    flags.reduced = false;
    els = {};
    selectors = {};
});

describe('#3379 countUp', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('starts on the start value and always lands on the end text', () => {
        const el = makeEl('n');
        U.countUp(el, 0, 80, { delay: 200, duration: 380, format: (n) => '+' + n, end: '+80' });
        expect(el.textContent).toBe('+0');
        vi.advanceTimersByTime(200 + 380 + 120);
        expect(el.textContent).toBe('+80');
        expect(el._countRun).toBeNull();
    });

    it('a render during the count moves where it lands, not the live digits', () => {
        const el = makeEl('n');
        U.countUp(el, 0, 80, { format: (n) => '+' + n, end: '+80' });
        U.setCountedText(el, '+90');
        expect(el.textContent).toBe('+0');
        vi.advanceTimersByTime(1000);
        expect(el.textContent).toBe('+90');
        U.setCountedText(el, '+95');
        expect(el.textContent).toBe('+95');
    });

    it('reduced motion writes the end straight away', () => {
        flags.reduced = true;
        const el = makeEl('n');
        expect(U.countUp(el, 0, 80, { end: '+80' })).toBeNull();
        expect(el.textContent).toBe('+80');
    });

    it('with hold it stays registered until the caller steps on', () => {
        const el = makeEl('n');
        const run = U.countUp(el, 0, 40, { duration: 100, hold: 1000, end: '140' });
        vi.advanceTimersByTime(500);
        expect(el._countRun).toBe(run);
        vi.advanceTimersByTime(1000);
        expect(el.textContent).toBe('140');
    });
});

describe('#3379 resultPointsPlan - the values the points pass through', () => {
    const plan = (p) => reveal.resultPointsPlan(p).map((s) => [s.to, s.chip]);

    it('a plain round counts straight to the total', () => {
        expect(plan({ round_score: 80, base_score: 80, speed_bonus: 0 })).toEqual([[80, null]]);
    });

    it('a won bet counts to the points before the bet, then jumps to the payout', () => {
        // 30 accuracy + 10 speed = 40, x3 = 120, plus a 20 streak milestone.
        const p = { round_score: 120, base_score: 30, speed_bonus: 10, bet_outcome: 'won', streak: 3, streak_bonus: 20 };
        expect(plan(p)).toEqual([[40, null], [120, 'bet'], [140, 'streak']]);
    });

    it('Finale x2 on top of the bet still divides evenly and is kept', () => {
        const p = { round_score: 240, base_score: 40, speed_bonus: 0, bet_outcome: 'won' };
        expect(plan(p)).toEqual([[40, null], [240, 'bet']]);
    });

    it('without the pre-bet speed bonus the bet step is left out, not guessed', () => {
        const p = { round_score: 120, base_score: 30, bet_outcome: 'won', streak: 3, streak_bonus: 20 };
        expect(plan(p)).toEqual([[120, null], [140, 'streak']]);
        const odd = { round_score: 125, base_score: 30, speed_bonus: 10, bet_outcome: 'won' };
        expect(plan(odd)).toEqual([[125, null]]);
    });

    it('artist and other bonuses ride along from the first step', () => {
        const p = { round_score: 120, base_score: 40, speed_bonus: 0, bet_outcome: 'won', artist_bonus: 10 };
        expect(plan(p)).toEqual([[50, null], [130, 'bet']]);
    });

    it('nothing to count for a miss or a zero round', () => {
        expect(plan({ missed_round: true })).toEqual([]);
        expect(plan({ round_score: 0 })).toEqual([]);
        expect(plan(null)).toEqual([]);
    });
});

describe('#3379 the personal result lands in order after the reel', () => {
    const frame = (player) => ({
        phase: 'REVEAL', round: 3, reveal_started_at: 1000,
        song: { year: 1988, title: 'T', artist: 'A' },
        round_analytics: { all_guesses: [] },
        players: [Object.assign({ name: 'Lena', guess: 1990, years_off: 2 }, player)],
    });
    let gap, scoreRow, row, betChip, streakChip;

    beforeEach(() => {
        vi.useFakeTimers();
        ['correct-year', 'reveal-emotion', 'reveal-leaderboard-list', 'reveal-total-pts', 'score-row-subtitle',
            'duel-your-year', 'duel-gap-count', 'duel-gap-unit']
            .forEach((id) => { els[id] = makeEl(id); });
        els['reveal-emotion'].classList.add('duel-emotion');
        gap = makeEl('gap');
        scoreRow = makeEl('score');
        els['reveal-view'] = makeEl('reveal-view', {
            querySelector: (sel) => ({ '.duel-gap': gap, '.score-row': scoreRow }[sel] || null),
        });
        betChip = makeEl('bet');
        streakChip = makeEl('streak');
        row = makeEl('reveal-chip-row', {
            querySelector: (sel) => (sel.includes('bet') ? betChip : sel.includes('streak') ? streakChip : null),
        });
        els['reveal-chip-row'] = row;
        state.motionGate = U.createMotionGate({ reduced: () => flags.reduced });
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

    const live = (data) => {
        state.motionGate.enter('PLAYING', 3);
        state.motionGate.enter('REVEAL', 3);
        reveal.startRevealStaging(data);
        reveal.updateRevealView(data);
    };
    const pts = () => els['reveal-total-pts'].textContent;
    const ends = (a) => (a.opts.delay || 0) + a.opts.duration;

    it('verdict, gap, score row in sequence, all done within 0.6 s of the reel stop', () => {
        const data = frame({ round_score: 80, base_score: 80, speed_bonus: 0 });
        const stopAt = U.tvYearReelStopMs(data);
        live(data);
        vi.advanceTimersByTime(stopAt);
        const emo = els['reveal-emotion'].anims.at(-1);
        expect(emo.opts.delay).toBe(0);
        expect(gap.anims[0].opts.delay).toBeGreaterThan(emo.opts.delay);
        expect(scoreRow.anims[0].opts.delay).toBeGreaterThan(gap.anims[0].opts.delay);
        [emo, gap.anims[0], scoreRow.anims[0]].forEach((a) => expect(ends(a)).toBeLessThanOrEqual(600));
        expect(pts()).toBe('+0');
        vi.advanceTimersByTime(599);
        expect(pts()).toBe('+80');
    });

    it('does not move "who got it": beat two still comes 80 ms after the reel stop', () => {
        const data = frame({ round_score: 80, base_score: 80, speed_bonus: 0 });
        const stopAt = U.tvYearReelStopMs(data);
        live(data);
        vi.advanceTimersByTime(stopAt + 79);
        expect(els['reveal-view'].attrs['data-reveal-stage']).toBe('1');
        vi.advanceTimersByTime(1);
        expect(els['reveal-view'].attrs['data-reveal-stage']).toBe('2');
    });

    it('a won bet: counts to 40, the bet chip springs and the number jumps, then the streak', () => {
        const data = frame({
            years_off: 0, guess: 1988, round_score: 120, base_score: 30, speed_bonus: 10,
            bet_outcome: 'won', streak: 3, streak_bonus: 20,
        });
        const stopAt = U.tvYearReelStopMs(data);
        live(data);
        expect(pts()).toBe('+140');
        vi.advanceTimersByTime(stopAt);
        vi.advanceTimersByTime(700);
        expect(pts()).toBe('+40');
        expect(betChip.anims[0].opts.delay).toBe(750);
        expect(streakChip.anims[0].opts.delay).toBe(1350);
        vi.advanceTimersByTime(150);
        expect(pts()).toBe('+120');
        vi.advanceTimersByTime(600);
        expect(pts()).toBe('+140');
    });

    it('a repeated frame mid-count does not clobber the count, and lands on the new total', () => {
        const data = frame({ round_score: 80, base_score: 80, speed_bonus: 0 });
        const stopAt = U.tvYearReelStopMs(data);
        live(data);
        vi.advanceTimersByTime(stopAt + 100);
        reveal.updateRevealView(frame({ round_score: 90, base_score: 90, speed_bonus: 0 }));
        expect(pts()).toBe('+0');
        vi.advanceTimersByTime(1000);
        expect(pts()).toBe('+90');
    });

    it('leaving the reveal lands the points at once', () => {
        const data = frame({ round_score: 80, base_score: 80, speed_bonus: 0 });
        live(data);
        vi.advanceTimersByTime(U.tvYearReelStopMs(data) + 250);
        reveal.stopRevealStaging();
        expect(pts()).toBe('+80');
    });

    it('a reconnect into the reveal (not live) shows the final picture, nothing moves', () => {
        const data = frame({ round_score: 80, base_score: 80, speed_bonus: 0 });
        state.motionGate.enter('REVEAL', 3);
        reveal.updateRevealView(data);
        vi.advanceTimersByTime(5000);
        expect(pts()).toBe('+80');
        expect(gap.anims).toHaveLength(0);
        expect(scoreRow.anims).toHaveLength(0);
    });
});

describe('#3379 Title & Artist: the tally grows in place', () => {
    function card() {
        const parts = {
            '.ta-tally-yes': makeEl('y'), '.ta-tally-no': makeEl('n'),
            '.ta-tally-fill--yes': makeEl('fy'), '.ta-tally-fill--no': makeEl('fn'),
        };
        return makeEl('card', { querySelector: (s) => parts[s] || null, parts });
    }
    let cards, verdicts, setHtml;

    beforeEach(() => {
        vi.useFakeTimers();
        ['ta-reveal-section', 'ta-reveal-truth', 'ta-reveal-own', 'ta-voting', 'ta-voting-title']
            .forEach((id) => { els[id] = makeEl(id); });
        els['ta-voting-countdown'] = makeEl('ta-voting-countdown');
        els['ta-voting-countdown'].style.setProperty = () => {};
        cards = [];
        verdicts = [makeEl('v1'), makeEl('v2')];
        setHtml = vi.fn();
        const cardsEl = makeEl('ta-voting-cards', {
            querySelectorAll: (s) => (s === '.ta-outcome-verdict' ? verdicts : []),
        });
        Object.defineProperty(cardsEl, 'innerHTML', {
            get: () => '',
            set: (v) => { setHtml(v); cardsEl.children = v && v.includes('ta-vote-card') ? [card()] : []; },
        });
        els['ta-voting-cards'] = cardsEl;
        cards = () => cardsEl.children;
        vi.spyOn(U, 't').mockImplementation((k) => k);
        state.playerName = 'Lena';
    });
    afterEach(() => {
        vi.restoreAllMocks();
        vi.clearAllTimers();
        vi.useRealTimers();
    });

    const ta = (yes, no, extra) => Object.assign({
        correct_title: 'Song ' + (extra && extra.song || 1), correct_artist: 'A', voting_open: true,
        vote_seconds_remaining: 20, results: [],
        near_misses: [{ id: 'nm1', player: 'Max', field: 'title', guess: 'Sng', votes_yes: yes, votes_no: no }],
    }, extra);

    it('a new vote updates numbers and widths without rebuilding the card', () => {
        reveal.renderTitleArtistReveal(ta(1, 1), { is_admin: false });
        expect(setHtml).toHaveBeenCalledTimes(1);
        const c = cards()[0];
        reveal.renderTitleArtistReveal(ta(3, 1), { is_admin: false });
        expect(setHtml).toHaveBeenCalledTimes(1);
        expect(cards()[0]).toBe(c);
        expect(c.parts['.ta-tally-yes'].textContent).toBe('👍 3');
        expect(c.parts['.ta-tally-fill--yes'].style.width).toBe('75%');
        expect(c.parts['.ta-tally-fill--no'].style.width).toBe('25%');
    });

    it('anything but the tally (here: the host role) rebuilds the cards', () => {
        reveal.renderTitleArtistReveal(ta(1, 1), { is_admin: false });
        reveal.renderTitleArtistReveal(ta(1, 1), { is_admin: true });
        expect(setHtml).toHaveBeenCalledTimes(2);
    });

    const decided = (extra) => ta(3, 1, Object.assign({
        voting_open: false,
        near_miss_outcomes: [
            { player: 'Max', field: 'title', guess: 'Sng', accepted: true, points: 10, votes_yes: 3, votes_no: 1 },
            { player: 'Ben', field: 'artist', guess: 'B', accepted: false, votes_yes: 0, votes_no: 2 },
        ],
    }, extra));

    it('the verdicts stamp in once, one after the other, on a phone that watched the vote', () => {
        reveal.renderTitleArtistReveal(ta(1, 1, { song: 7 }), {});
        reveal.renderTitleArtistReveal(decided({ song: 7 }), {});
        expect(verdicts.map((v) => v.anims[0].opts.delay)).toEqual([0, 80]);
        verdicts[0].anims[0].frames.forEach((f) => expect(Object.keys(f).filter((k) => k !== 'offset').sort()).toEqual(['opacity', 'transform']));
        reveal.renderTitleArtistReveal(decided({ song: 7 }), {});
        expect(verdicts[0].anims).toHaveLength(1);
    });

    it('a phone that only saw the decided cards gets them without a stamp', () => {
        reveal.renderTitleArtistReveal(decided({ song: 8 }), {});
        expect(verdicts[0].anims).toHaveLength(0);
    });

    it('reduced motion: no stamp', () => {
        flags.reduced = true;
        reveal.renderTitleArtistReveal(ta(1, 1, { song: 9 }), {});
        reveal.renderTitleArtistReveal(decided({ song: 9 }), {});
        expect(verdicts[0].anims).toHaveLength(0);
    });
});

describe('#3379 phone: the special-round chip springs in', () => {
    it('springs for Finale x2 and the tiebreaker, not for a plain last round', () => {
        els['last-round-banner'] = makeEl('last-round-banner');
        game.playRoundStartMotion({ finale_double_active: true });
        game.playRoundStartMotion({ finale_playoff_active: true });
        game.playRoundStartMotion({ last_round: true });
        expect(els['last-round-banner'].anims).toHaveLength(2);
        expect(els['last-round-banner'].anims[0].opts.fill).toBe('backwards');
    });

    it('reduced motion: nothing', () => {
        flags.reduced = true;
        els['last-round-banner'] = makeEl('last-round-banner');
        game.playRoundStartMotion({ finale_double_active: true });
        expect(els['last-round-banner'].anims).toHaveLength(0);
    });
});

describe('#3379 phone end: your rank counts down to yours', () => {
    it('from at most four places behind, never past the last place', () => {
        expect(end.endRankCountdown(4, 8)).toEqual([8, 7, 6, 5]);
        expect(end.endRankCountdown(4, 10)).toEqual([8, 7, 6, 5]);
        expect(end.endRankCountdown(2, 3)).toEqual([3]);
        expect(end.endRankCountdown(1, 1)).toEqual([]);
        expect(end.endRankCountdown(5, 5)).toEqual([]);
        expect(end.endRankCountdown(undefined, 5)).toEqual([]);
    });

    describe('on the end screen', () => {
        let card;
        beforeEach(() => {
            vi.useFakeTimers();
            ['your-final-rank', 'your-final-score', 'stat-best-streak', 'stat-rounds', 'stat-bets']
                .forEach((id) => { els[id] = makeEl(id); });
            card = makeEl('card');
            selectors['#end-view .your-result'] = card;
            vi.spyOn(U, 't').mockImplementation((k) => (k === 'leaderboard.points' ? 'points' : k));
            state.motionGate = U.createMotionGate({ reduced: () => flags.reduced });
            state.playerName = 'Lena';
            global.window.scrollTo = () => {};
        });
        afterEach(() => {
            vi.restoreAllMocks();
            delete state.motionGate;
            vi.useRealTimers();
        });
        const data = () => ({
            phase: 'END', game_id: 'g1', round: 10,
            leaderboard: ['A', 'B', 'C', 'Lena', 'E', 'F'].map((name, i) => ({
                name, rank: i + 1, score: 1000 - i * 100, best_streak: 2, rounds_played: 10, bets_won: 1,
            })),
        });

        it('waits for the TV podium, then counts down and lands; repeats change nothing', () => {
            state.motionGate.enter('REVEAL', 10);
            state.motionGate.enter('END', 10);
            end.updateEndView(data());
            const rank = els['your-final-rank'];
            expect(rank.textContent).toBe('#6');
            expect(card.anims[0].opts.delay).toBe(2120);
            vi.advanceTimersByTime(2320 + 110);
            expect(rank.textContent).toBe('#5');
            end.updateEndView(data());
            expect(rank.textContent).toBe('#5');
            vi.advanceTimersByTime(2 * 110);
            expect(rank.textContent).toBe('#4');
            vi.advanceTimersByTime(2000);
            expect(els['your-final-score'].textContent).toBe('700 points');
            expect(card.anims).toHaveLength(1);
        });

        it('a reload onto the end screen shows the final picture', () => {
            state.motionGate.enter('END', 10);
            end.updateEndView(data());
            expect(els['your-final-rank'].textContent).toBe('#4');
            expect(els['your-final-score'].textContent).toBe('700 points');
            expect(card.anims).toHaveLength(0);
        });
    });
});

describe('#3379 TV: special-round announcement and pause, transform and opacity only', () => {
    const DASHBOARD = readSource('dashboard.js');
    const src = (name) => declaration(DASHBOARD, name, 'dashboard.js');
    const consts = (names) => names.map((n) => {
        const m = DASHBOARD.match(new RegExp(`\\n    var ${n} = [^;]+;`));
        if (!m) throw new Error(`dashboard.js no longer declares ${n}`);
        return m[0];
    }).join('\n');
    const onlyCheap = (anims) => anims.forEach((a) => a.frames.forEach((f) => {
        Object.keys(f).filter((k) => k !== 'offset').forEach((k) => expect(['transform', 'opacity']).toContain(k));
    }));

    function announce(pillVisible, reduced = false) {
        const pill = makeEl('pill', { getBoundingClientRect: () => ({ left: 900, top: 40, width: 300, height: 40 }) });
        if (!pillVisible) pill.classList.add('hidden');
        const hidden = makeEl('other');
        hidden.classList.add('hidden');
        const content = makeEl('content');
        const play = evaluate(
            consts(['ANNOUNCE_AT_MS', 'ANNOUNCE_MS', 'ANNOUNCE_SCALE']) + 'var MOTION_EASE = "ease";' +
                src('playSpecialRoundAnnounce'),
            'playSpecialRoundAnnounce',
            {
                _reducedMotion: () => reduced,
                window: { innerWidth: 1920, innerHeight: 1080 },
                document: {
                    getElementById: (id) => (id === 'dashboard-finale-banner-playing' ? pill : hidden),
                    querySelector: () => content,
                    documentElement: {},
                },
            },
        );
        play();
        return { pill, content };
    }

    it('the pill starts large in the middle and flies home; the round underneath dims', () => {
        const { pill, content } = announce(true);
        expect(pill.anims).toHaveLength(1);
        const first = pill.anims[0].frames[0].transform;
        // centre of 1920x1080 minus the pill centre (1050, 60)
        expect(first).toContain('translate(-90px,480px)');
        expect(pill.anims[0].frames.at(-1).transform).toBe('none');
        expect(pill.anims[0].opts.duration).toBe(1400);
        onlyCheap(pill.anims);
        onlyCheap(content.anims);
        expect(pill.classList.contains('is-announcing')).toBe(true);
    });

    it('nothing when no special pill shows, or with reduced motion', () => {
        expect(announce(false).pill.anims).toHaveLength(0);
        expect(announce(true, true).pill.anims).toHaveLength(0);
    });

    it('is played once per round the TV saw begin', () => {
        const frame = src('_renderFrame');
        expect(frame).toMatch(/takeRoundStart\(\)/);
        expect(frame).toMatch(/if \(roundStart\) playSpecialRoundAnnounce\(\)/);
    });

    function pauseFrames() {
        const render = vi.fn();
        const entrance = vi.fn();
        const card = makeEl('card');
        const view = makeEl('dashboard-paused');
        const apply = evaluate(
            consts(['SCENE_WIPE_IN_MS', 'SCENE_WIPE_OUT_MS', 'PAUSE_EXIT_MS']) +
                'var SCENE_WIPE_PHASES = { LOBBY: true, PLAYING: true, REVEAL: true, END: true };' +
                'var _sceneWipeHold = null, _lastScenePhase = null;' +
                src('shouldWipeScene') + src('playSceneWipe') + src('playPauseExit') + src('_applyFrame'),
            '_applyFrame',
            {
                document: {
                    getElementById: (id) => (id === 'dashboard-paused' ? view : null),
                    querySelector: () => card,
                },
                _reducedMotion: () => false,
                _renderFrame: render,
                playPauseEntrance: entrance,
            },
        );
        return { apply, render, entrance, card };
    }

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('a pause the room saw begin gets its entrance; a reload into a pause does not', () => {
        const a = pauseFrames();
        a.apply({ phase: 'PAUSED', game_id: 'g', round: 2 });
        expect(a.entrance).not.toHaveBeenCalled();
        const b = pauseFrames();
        b.apply({ phase: 'PLAYING', game_id: 'g', round: 2 });
        b.apply({ phase: 'PAUSED', game_id: 'g', round: 2 });
        b.apply({ phase: 'PAUSED', game_id: 'g', round: 2, v: 2 });
        expect(b.entrance).toHaveBeenCalledTimes(1);
    });

    it('resuming: the card leaves in 200 ms, then the newest frame is drawn', () => {
        const { apply, render, card } = pauseFrames();
        apply({ phase: 'PLAYING', game_id: 'g', round: 2 });
        apply({ phase: 'PAUSED', game_id: 'g', round: 2 });
        expect(render).toHaveBeenCalledTimes(2);
        apply({ phase: 'PLAYING', game_id: 'g', round: 2, v: 1 });
        apply({ phase: 'PLAYING', game_id: 'g', round: 2, v: 2 });
        expect(render).toHaveBeenCalledTimes(2);
        vi.advanceTimersByTime(200);
        expect(render).toHaveBeenCalledTimes(3);
        expect(render.mock.calls[2][0].v).toBe(2);
        onlyCheap(card.anims);
        expect(card.anims[0].cancel).toHaveBeenCalled();
    });

    it('the entrance: emoji, reason, then state and hint, transform and opacity only', () => {
        const nodes = {};
        const play = evaluate(
            consts(['PAUSE_EXIT_MS']) + 'var MOTION_EASE = "ease";' + declarationOfEntrance() + src('playPauseEntrance'),
            'playPauseEntrance',
            {
                _reducedMotion: () => false,
                document: { querySelector: (s) => (nodes[s] = nodes[s] || makeEl(s)) },
            },
        );
        play();
        const delay = (s) => nodes[s].anims[0].opts.delay;
        expect(delay('#dashboard-pause-icon')).toBeLessThan(delay('#dashboard-pause-title'));
        expect(delay('#dashboard-pause-title')).toBeLessThan(delay('#dashboard-pause-state'));
        expect(delay('#dashboard-pause-state')).toBeLessThan(delay('#dashboard-pause-message'));
        Object.values(nodes).forEach((n) => onlyCheap(n.anims));
    });

    function declarationOfEntrance() {
        const at = DASHBOARD.indexOf('\n    var PAUSE_ENTRANCE = [');
        if (at === -1) throw new Error('dashboard.js no longer declares PAUSE_ENTRANCE');
        return DASHBOARD.slice(at, DASHBOARD.indexOf('];', at) + 2);
    }
});
