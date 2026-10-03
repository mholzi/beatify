/**
 * #3095 — the TV said "Now Playing" while an intro round waited for the host.
 *
 * The phones show the "Intro Round! Waiting for host..." dialog for as long as
 * the server holds `intro_splash_pending`. The TV rested its timer (#3027) and
 * showed nothing else, so the shared screen gave the room no reason for the
 * silence. It now carries a card over the playing content, driven by the same
 * flag and gone the moment the flag or the view is.
 *
 * Same harness as the #3027 suite next door: the shipped dispatcher,
 * showView and renderPlayingView run for real (helpers/js-source.js); only the
 * DOM and the unrelated renderers are stubbed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource, locale, WWW_DIR } from './helpers/js-source.js';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const DASHBOARD = readSource('dashboard.js');
const SNIPPETS = [
    'var lastCountdownDeadline = null;',
    'var countdownInterval = null;',
    ...[
        '_applyStateRender',
        'showView',
        'hideIntroWaitCard',
        'renderPlayingView',
        'renderRoundStats',
        'startCountdown',
        'stopCountdown',
        'showRestingTimer',
    ].map((name) => declaration(DASHBOARD, name, 'dashboard.js')),
];

function makeEl(text = '') {
    const classes = new Set();
    const attrs = {};
    return {
        textContent: text,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, force) => {
                const on = force === undefined ? !classes.has(c) : !!force;
                if (on) classes.add(c);
                else classes.delete(c);
                return on;
            },
        },
        setAttribute: (k, v) => {
            attrs[k] = String(v);
        },
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
    };
}

let els;
let shown;
let apply;

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    els = {
        'dashboard-timer': makeEl('30'),
        'dashboard-time-remaining': makeEl('--'),
        'dashboard-submissions': makeEl(''),
        'dashboard-intro-wait': makeEl(),
    };
    // As shipped in dashboard.html: off, and hidden from assistive tech.
    els['dashboard-intro-wait'].setAttribute('aria-hidden', 'true');
    shown = [];
    const noop = () => {};
    apply = evaluate(SNIPPETS, '_applyStateRender', {
        document: { getElementById: (id) => els[id] || null, querySelectorAll: () => [] },
        utils: {
            t: () => '',
            showView: (_views, id) => shown.push(id),
            hydrateLeaderboard: (lb) => lb,
        },
        allViews: [],
        debug: noop,
        lastRenderedRound: null,
        songStoppedRound: null,
        setSongStoppedChip: noop,
        hideJoinCorner: noop,
        stopRevealStaging: noop,
        renderJoinCorner: noop,
        renderLeaderboard: noop,
        renderGhostLeague: noop,
        renderSuddenDeathFinalBanner: noop,
        renderFinaleDoubleBanner: noop,
        renderFinalePlayoffBanner: noop,
        renderLobbyView: noop,
        renderRevealView: noop,
        renderEndView: noop,
        renderPausedView: noop,
    });
});

afterEach(() => {
    vi.useRealTimers();
});

const card = () => els['dashboard-intro-wait'];
const visible = () => card().classList.contains('is-visible');

function frame(extra) {
    return {
        phase: 'PLAYING',
        game_id: 'g1',
        round: 1,
        total_rounds: 10,
        round_duration: 30,
        players: [],
        deadline: 1_030_000,
        seconds_remaining: 30,
        ...extra,
    };
}

describe('#3095 TV card while the intro round waits for the host', () => {
    it('shows the card on a playing frame with the splash pending', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        expect(shown.at(-1)).toBe('dashboard-playing');
        expect(visible()).toBe(true);
        expect(card().getAttribute('aria-hidden')).toBe('false');
    });

    it('hides it on the frame that clears the flag', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        apply(frame({ is_intro_round: true, intro_splash_pending: false, deadline: 1_042_000 }));
        expect(visible()).toBe(false);
        expect(card().getAttribute('aria-hidden')).toBe('true');
    });

    it('stays up across later pending frames', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        apply(frame({ is_intro_round: true, intro_splash_pending: true, seconds_remaining: 12 }));
        expect(visible()).toBe(true);
    });

    it.each([
        ['REVEAL', 'dashboard-reveal'],
        ['PAUSED', 'dashboard-paused'],
        ['END', 'dashboard-end'],
        ['LOBBY', 'dashboard-lobby'],
    ])('hides it when a pending round moves to %s', (phase, view) => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        expect(visible()).toBe(true);

        apply(frame({ phase }));
        expect(shown.at(-1)).toBe(view);
        expect(visible()).toBe(false);
        expect(card().getAttribute('aria-hidden')).toBe('true');
    });

    it('hides it when the game is gone', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        apply({ phase: null });
        expect(shown.at(-1)).toBe('dashboard-no-game');
        expect(visible()).toBe(false);
    });

    it('never shows it on a normal playing frame', () => {
        apply(frame({}));
        expect(visible()).toBe(false);
        apply(frame({ is_intro_round: true, seconds_remaining: 20 }));
        expect(visible()).toBe(false);
        expect(card().getAttribute('aria-hidden')).toBe('true');
    });

    it('shows it again on the next intro round', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        apply(frame({ phase: 'REVEAL' }));
        apply(frame({ round: 2, is_intro_round: true, intro_splash_pending: true }));
        expect(visible()).toBe(true);
    });

    it('leaves the #3027 resting timer as it was while the card is up', () => {
        apply(frame({ is_intro_round: true, intro_splash_pending: true }));
        vi.advanceTimersByTime(40_000);
        expect(els['dashboard-timer'].textContent).toBe(30);
        expect(els['dashboard-timer'].classList.contains('timer--critical')).toBe(false);
    });
});

describe('#3095 the card reuses the phones\' three strings', () => {
    const html = readFileSync(join(WWW_DIR, 'dashboard.html'), 'utf8');
    const start = html.indexOf('id="dashboard-intro-wait"');
    const markup = html.slice(start, html.indexOf('</div>\n            </div>\n        </div>', start));
    const keys = [...markup.matchAll(/data-i18n="([^"]+)"/g)].map((m) => m[1]);

    it('is a status region that starts hidden', () => {
        expect(start).toBeGreaterThan(-1);
        const tag = html.slice(html.lastIndexOf('<', start), html.indexOf('>', start) + 1);
        expect(tag).toContain('role="status"');
        expect(tag).toContain('aria-live="polite"');
        expect(tag).toContain('aria-hidden="true"');
        expect(tag).not.toContain('is-visible');
    });

    it('binds exactly the three existing keys', () => {
        expect(keys).toEqual(['game.introSplashTitle', 'game.introSplashDesc', 'game.introSplashWaiting']);
    });

    it.each(['en', 'de', 'es', 'fr', 'it', 'nl'])('has all three in %s', (lang) => {
        const game = locale(lang).game;
        for (const key of keys) {
            const value = game[key.split('.')[1]];
            expect(typeof value).toBe('string');
            expect(value.length).toBeGreaterThan(0);
        }
    });
});
