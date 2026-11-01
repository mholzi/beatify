/**
 * #3367 - motion while operating. The shipped modules run; only the DOM and
 * their imports are stubbed. Each test names a way the feature could go wrong
 * for a real person: a dropout that flashes an overlay, a round that restarts
 * its animation on every broadcast, a resume that slides in.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const flags = vi.hoisted(() => ({ reduced: false }));
const WWW = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

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
    const attrs = {};
    const node = {
        id, textContent: '', style: {}, dataset: {}, anims: [],
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
        setAttribute: (k, v) => { attrs[k] = v; },
        removeAttribute: (k) => { delete attrs[k]; },
        hasAttribute: (k) => k in attrs,
        querySelector: () => null,
        querySelectorAll: () => [],
        ...extra,
    };
    return node;
}

let els = {};
let frames = [];
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
    querySelector: () => null,
    querySelectorAll: (sel) => (sel === '.wiz-frame' ? frames : []),
    body: makeEl('body'),
};

await import('../utils.js');
const U = global.window.BeatifyUtils;

vi.mock('../player-utils.js', async (orig) => {
    const real = await orig();
    return Object.assign({}, real, { prefersReducedMotion: () => flags.reduced });
});
const game = await import('../player-game.js');
const wizard = await import('../wizard.js');
const hub = await import('../playlist-hub.js');

beforeEach(() => { flags.reduced = false; els = {}; frames = []; });

describe('#3367 wizard: direction', () => {
    const frame = (n) => makeEl(`frame${n}`, { dataset: { frame: String(n) } });

    it('next comes from the right, back from the left', () => {
        frames = [frame(1), frame(2), frame(3)];
        els['wiz-progress'] = makeEl('wiz-progress');
        wizard._showFrame(1, { instant: true });
        wizard._showFrame(2);
        expect(frames[1].anims[0].frames[0].transform).toBe('translateX(48px)');
        wizard._showFrame(3);
        wizard._showFrame(2);
        expect(frames[1].anims[1].frames[0].transform).toBe('translateX(-48px)');
    });

    it('the progress bar runs on a step change and not on opening', () => {
        frames = [frame(1), frame(2)];
        els['wiz-progress'] = makeEl('wiz-progress');
        wizard._showFrame(2, { instant: true });
        expect(els['wiz-progress'].classList.contains('wiz-progress--live')).toBe(false);
        wizard._showFrame(1);
        expect(els['wiz-progress'].classList.contains('wiz-progress--live')).toBe(true);
    });

    it('resuming shows the final picture, even coming from another step', async () => {
        frames = [frame(1), frame(2), frame(3)];
        els['wiz-progress'] = makeEl('wiz-progress');
        els['wizard-root'] = makeEl('wizard-root');
        wizard._showFrame(1, { instant: true });
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ media_players: [], playlists: [] }) })));
        await wizard.show(3);
        vi.unstubAllGlobals();
        expect(frames[2].hasAttribute('hidden')).toBe(false);
        expect(frames[2].anims).toHaveLength(0);
        expect(els['wiz-progress'].classList.contains('wiz-progress--live')).toBe(false);
    });

    it('reduced motion shows every step at once', () => {
        frames = [frame(1), frame(2)];
        els['wiz-progress'] = makeEl('wiz-progress');
        wizard._showFrame(1, { instant: true });
        flags.reduced = true;
        wizard._showFrame(2);
        expect(frames[1].anims).toHaveLength(0);
        expect(els['wiz-progress'].classList.contains('wiz-progress--live')).toBe(false);
    });

    it('the same step does not move', () => {
        expect(wizard.wizardStepDirection(2, 2, false)).toBe(null);
        expect(wizard.wizardStepDirection(2, 3, true)).toBe(null);
    });
});

describe('#3367 reconnect overlay', () => {
    let shown, hidden, signals;
    const overlay = (over = {}) => U.createReconnectOverlay({
        delay: 1000,
        show: () => { shown += 1; },
        hide: () => { hidden += 1; },
        signal: () => { signals += 1; return 440; },
        ...over,
    });

    beforeEach(() => { shown = 0; hidden = 0; signals = 0; vi.useFakeTimers(); });
    afterEach(() => vi.useRealTimers());

    it('a dropout inside the second shows nothing and signals nothing', () => {
        const o = overlay();
        o.lost();
        vi.advanceTimersByTime(999);
        o.back();
        vi.advanceTimersByTime(5000);
        expect([shown, hidden, signals]).toEqual([0, 0, 0]);
    });

    it('shows after one second, however many retries fail meanwhile', () => {
        const o = overlay();
        o.lost();
        vi.advanceTimersByTime(600);
        o.lost();
        vi.advanceTimersByTime(399);
        expect(shown).toBe(0);
        vi.advanceTimersByTime(1);
        expect(shown).toBe(1);
        o.lost();
        vi.advanceTimersByTime(5000);
        expect(shown).toBe(1);
    });

    it('only an overlay that was visible turns green, then goes', () => {
        const o = overlay();
        o.lost();
        vi.advanceTimersByTime(1000);
        o.back();
        expect(signals).toBe(1);
        expect(hidden).toBe(0);
        vi.advanceTimersByTime(440);
        expect(hidden).toBe(1);
    });

    it('losing it again during the signal keeps the overlay up without a new wait', () => {
        const unsignal = vi.fn();
        const o = overlay({ unsignal });
        o.lost();
        vi.advanceTimersByTime(1000);
        o.back();
        o.lost();
        expect(unsignal).toHaveBeenCalledTimes(1);
        vi.advanceTimersByTime(5000);
        expect(hidden).toBe(0);
        expect(o.state()).toBe('visible');
    });

    it('reduced motion clears at once, with no signal', () => {
        const o = overlay({ reduced: () => true });
        o.lost();
        vi.advanceTimersByTime(1000);
        o.back();
        expect([signals, hidden]).toEqual([0, 1]);
    });

    it('giving up cancels a pending wait', () => {
        const o = overlay();
        o.lost();
        o.stop();
        vi.advanceTimersByTime(5000);
        expect(shown).toBe(0);
    });

    it('the first retry can finish inside the wait, the ladder after it is unchanged', () => {
        const core = readFileSync(join(WWW, 'js/player-core.js'), 'utf8');
        const wait = Number(core.match(/RECONNECT_OVERLAY_DELAY_MS = (\d+)/)[1]);
        const first = Number(core.match(/FIRST_RECONNECT_DELAY_MS = (\d+)/)[1]);
        expect(wait).toBe(1000);
        expect(first).toBeLessThan(wait / 2);
        expect(U.reconnectBackoffDelay(1, { firstDelay: first })).toBe(first);
        expect(U.reconnectBackoffDelay(2, { firstDelay: first })).toBe(2000);
        expect(U.reconnectBackoffDelay(1)).toBe(1000);
    });
});

describe('#3367 round start', () => {
    const gate = (reduced = false) => U.createMotionGate({ reduced: () => reduced });

    it('fires once per round change, not on repeat frames', () => {
        const g = gate();
        g.enter('PLAYING', 3);
        g.takeRoundStart();
        g.enter('REVEAL', 3);
        g.enter('PLAYING', 4);
        expect(g.takeRoundStart()).toBe(true);
        expect(g.takeRoundStart()).toBe(false);
        g.enter('PLAYING', 4);
        g.enter('PLAYING', 4);
        expect(g.takeRoundStart()).toBe(false);
    });

    it('the first round out of the lobby counts', () => {
        const g = gate();
        g.enter('LOBBY', 0);
        g.enter('PLAYING', 1);
        expect(g.takeRoundStart()).toBe(true);
    });

    it('stays still on a reload, a reconnect and a resume from pause', () => {
        const fresh = gate();
        fresh.enter('PLAYING', 5);
        expect(fresh.takeRoundStart()).toBe(false);

        const dropped = gate();
        dropped.enter('REVEAL', 4);
        dropped.reset();
        dropped.enter('PLAYING', 5);
        expect(dropped.takeRoundStart()).toBe(false);

        const paused = gate();
        paused.enter('PLAYING', 5);
        paused.enter('PAUSED', 5);
        paused.enter('PLAYING', 5);
        expect(paused.takeRoundStart()).toBe(false);
    });

    it('reduced motion never fires', () => {
        const g = gate(true);
        g.enter('REVEAL', 4);
        g.enter('PLAYING', 5);
        expect(g.takeRoundStart()).toBe(false);
    });

    it('leaves the reveal gate alone: a new round is not `live`', () => {
        const g = gate();
        g.enter('REVEAL', 4);
        expect(g.enter('PLAYING', 5)).toBe(false);
        expect(g.isLive()).toBe(false);
        expect(g.takeRoundStart()).toBe(true);
    });

    it('the timer leads, the rest follows 60 ms apart, all under half a second', () => {
        ['timer-neon', 'year-display-arc', 'year-selector-container', 'submit-btn'].forEach((id) => { els[id] = makeEl(id); });
        game.playRoundStartMotion();
        const delays = ['year-display-arc', 'year-selector-container', 'submit-btn'].map((id) => els[id].anims[0].opts.delay);
        expect(els['timer-neon'].anims[0].opts.delay).toBeUndefined();
        expect(delays).toEqual([60, 120, 180]);
        const ends = Object.values(els).map((e) => (e.anims[0].opts.delay || 0) + e.anims[0].opts.duration);
        expect(Math.max(...ends)).toBeLessThan(500);
        Object.values(els).forEach((e) => {
            e.anims[0].frames.forEach((f) => expect(Object.keys(f).filter((k) => k !== 'offset').sort()).toEqual(['opacity', 'transform']));
        });
    });

    it('is wired behind the gate in the PLAYING path', () => {
        const core = readFileSync(join(WWW, 'js/player-core.js'), 'utf8');
        expect(core).toMatch(/motionGate\.takeRoundStart\(\)\) playRoundStartMotion\(\)/);
    });

    it('reduced motion plays nothing', () => {
        els['timer-neon'] = makeEl('timer-neon');
        flags.reduced = true;
        game.playRoundStartMotion();
        expect(els['timer-neon'].anims).toHaveLength(0);
    });
});

describe('#3367 selection', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('springs the check and glows the tile briefly', () => {
        const tile = makeEl('tile');
        const check = makeEl('check');
        U.pickFeedback(tile, check);
        expect(tile.classList.contains('motion-pick-glow')).toBe(true);
        expect(check.anims[0].opts.duration).toBeLessThan(300);
        vi.advanceTimersByTime(320);
        expect(tile.classList.contains('motion-pick-glow')).toBe(false);
    });

    it('reduced motion leaves both alone', () => {
        const tile = makeEl('tile');
        const check = makeEl('check');
        flags.reduced = true;
        U.pickFeedback(tile, check);
        expect(tile.classList.contains('motion-pick-glow')).toBe(false);
        expect(check.anims).toHaveLength(0);
    });

    it('finds the tapped card among the same playlist on several shelves', () => {
        const a = makeEl('a', { dataset: { plhCard: 'x.json' } });
        const b = makeEl('b', { dataset: { plhCard: 'y.json' } });
        const c = makeEl('c', { dataset: { plhCard: 'x.json' } });
        const root = { querySelectorAll: () => [a, b, c] };
        expect(hub._cardsFor(root, 'x.json')).toEqual([a, c]);
    });

    it('a count holds the final value at once, and reduced motion stops there', () => {
        const queued = [];
        vi.stubGlobal('requestAnimationFrame', (fn) => { queued.push(fn); return queued.length; });
        const el = makeEl('n');
        el.textContent = '100';
        U.countTo(el, 200);
        expect(el.textContent).toBe(200);
        expect(queued).toHaveLength(1);
        queued[0](0);
        queued[1](140);
        expect(Number(el.textContent)).toBeGreaterThan(100);
        expect(Number(el.textContent)).toBeLessThan(200);
        queued[2](280);
        expect(el.textContent).toBe(200);

        flags.reduced = true;
        const still = makeEl('m');
        still.textContent = '1';
        const before = queued.length;
        U.countTo(still, 9);
        expect(still.textContent).toBe(9);
        expect(queued).toHaveLength(before);
        vi.unstubAllGlobals();
    });
});

describe('#3367 sections', () => {
    function section(collapsed) {
        const content = makeEl('content', {
            scrollHeight: 240,
            getBoundingClientRect: () => ({ height: collapsed ? 0 : 240 }),
        });
        const s = makeEl('section', { querySelector: () => content });
        if (collapsed) s.classList.add('collapsed');
        return { s, content };
    }
    beforeEach(() => vi.stubGlobal('getComputedStyle', () => ({ paddingTop: '0px', paddingBottom: '16px' })));
    afterEach(() => vi.unstubAllGlobals());

    it('opens in 200 ms and the state is right from the first moment', () => {
        const { s, content } = section(true);
        expect(U.toggleCollapsibleSection(s)).toBe(false);
        expect(s.classList.contains('collapsed')).toBe(false);
        expect(s.classList.contains('is-closing')).toBe(false);
        const [a, b] = content.anims[0].frames;
        expect(content.anims[0].opts.duration).toBe(200);
        expect([a.height, b.height]).toEqual(['0px', '240px']);
    });

    it('keeps the content up while closing, and lets go when done', () => {
        const { s, content } = section(false);
        expect(U.toggleCollapsibleSection(s)).toBe(true);
        expect(s.classList.contains('collapsed')).toBe(true);
        expect(s.classList.contains('is-closing')).toBe(true);
        content.anims[0].onfinish();
        expect(s.classList.contains('is-closing')).toBe(false);
        expect(s.classList.contains('is-toggling')).toBe(false);
    });

    it('a tap in mid-flight turns round, and the old finish changes nothing', () => {
        const { s, content } = section(false);
        U.toggleCollapsibleSection(s);
        const first = content.anims[0];
        U.toggleCollapsibleSection(s);
        expect(first.cancel).toHaveBeenCalled();
        expect(s.classList.contains('is-closing')).toBe(false);
        first.onfinish();
        expect(s.classList.contains('is-toggling')).toBe(true);
    });

    it('reduced motion switches at once', () => {
        flags.reduced = true;
        const { s, content } = section(false);
        U.toggleCollapsibleSection(s);
        expect(s.classList.contains('collapsed')).toBe(true);
        expect(s.classList.contains('is-closing')).toBe(false);
        expect(s.classList.contains('is-toggling')).toBe(false);
        expect(content.anims).toHaveLength(0);
    });

    it('the chevron only turns on a tap, so a state set on load does not move', () => {
        const css = readFileSync(join(WWW, 'css/styles.css'), 'utf8');
        const rule = (sel) => css.slice(css.indexOf(`${sel} {`), css.indexOf('}', css.indexOf(`${sel} {`)));
        expect(rule('.admin-content .section-header-collapsible .section-toggle')).not.toContain('transition');
        expect(css).toMatch(/\.admin-content \.section-collapsible\.is-toggling \.section-toggle[\s\S]{0,120}transition: transform 200ms/);
    });
});

describe('#3367 button press', () => {
    const css = readFileSync(join(WWW, 'css/styles.css'), 'utf8');
    const block = css.slice(css.indexOf('Motion while operating (#3367)'));

    it('is one rule on :active, scoped away from the TV and reduced motion', () => {
        const media = block.slice(block.indexOf('@media (prefers-reduced-motion: no-preference)'));
        expect(media).toMatch(/body:not\(\.dashboard-body\) button:not\(:disabled\)[^{]*:active[\s\S]{0,300}scale: 0\.96/);
        expect(media.slice(0, media.indexOf('.motion-pick-glow'))).not.toContain('animation');
    });

    it('leaves no second scale on the press of a single button', () => {
        const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
        const hits = [...stripped.matchAll(/([^{}]*:active[^{}]*)\{([^{}]*)\}/g)]
            .filter((m) => /transform:\s*scale/.test(m[2]) && !/slider/.test(m[1]));
        expect(hits.map((m) => m[1].trim())).toEqual([]);
    });
});
