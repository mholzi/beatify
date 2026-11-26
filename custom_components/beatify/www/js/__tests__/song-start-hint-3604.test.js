/**
 * #3604: from round 2 on, the room waits on the previous reveal while the
 * speaker starts the next song, and under rate limiting that took up to 27 s
 * with nothing on any screen. The server now sends `song_starting` after 3 s
 * without confirmed playback and `song_start_failed` when a song is skipped.
 * TV and phone show a small pill on the reveal (design Variant A) and drop it
 * with the next state that is not REVEAL.
 *
 * Runs the shipped TV functions (cut out of dashboard.js) and the shipped
 * phone module against the hand-rolled DOM.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { declaration, evaluate, readSource, locale, WWW_DIR } from './helpers/js-source.js';
import { el, doc } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const TV_HTML = readFileSync(join(WWW_DIR, 'dashboard.html'), 'utf8');
const PHONE_HTML = readFileSync(join(WWW_DIR, 'player.html'), 'utf8');

// ---------------------------------------------------------------- TV

function tv({ revealVisible = true } = {}) {
    const hint = el('dashboard-song-hint');
    hint.classList.add('hidden');
    const reveal = el('dashboard-reveal');
    if (!revealVisible) reveal.classList.add('hidden');
    const document = doc({ 'dashboard-song-hint': hint, 'dashboard-reveal': reveal });
    const setSongStartHint = evaluate(
        declaration(DASHBOARD, 'setSongStartHint', 'dashboard.js'),
        'setSongStartHint',
        { document },
    );
    return { hint, reveal, setSongStartHint };
}

describe('#3604 TV song-start pill', () => {
    it('shows the loading pill over a visible reveal', () => {
        const { hint, setSongStartHint } = tv();
        setSongStartHint('loading');
        expect(hint.classList.contains('hidden')).toBe(false);
        expect(hint.classList.contains('song-hint--failed')).toBe(false);
    });

    it('switches to the failed state and back to loading', () => {
        const { hint, setSongStartHint } = tv();
        setSongStartHint('failed');
        expect(hint.classList.contains('hidden')).toBe(false);
        expect(hint.classList.contains('song-hint--failed')).toBe(true);
        setSongStartHint('loading');
        expect(hint.classList.contains('song-hint--failed')).toBe(false);
    });

    it('clears on null', () => {
        const { hint, setSongStartHint } = tv();
        setSongStartHint('failed');
        setSongStartHint(null);
        expect(hint.classList.contains('hidden')).toBe(true);
        expect(hint.classList.contains('song-hint--failed')).toBe(false);
    });

    it('ignores a notice that arrives when the reveal is not on screen', () => {
        const { hint, setSongStartHint } = tv({ revealVisible: false });
        setSongStartHint('loading');
        expect(hint.classList.contains('hidden')).toBe(true);
    });

    it('routes both server messages to the pill', () => {
        const calls = [];
        const handle = evaluate(
            declaration(DASHBOARD, 'handleServerMessage', 'dashboard.js'),
            'handleServerMessage',
            { setSongStartHint: (mode) => calls.push(mode) },
        );
        handle({ type: 'song_starting' });
        handle({ type: 'song_start_failed' });
        expect(calls).toEqual(['loading', 'failed']);
    });

    function render(phase) {
        const calls = [];
        const noop = () => {};
        evaluate(declaration(DASHBOARD, '_applyStateRender', 'dashboard.js'), '_applyStateRender', {
            utils: {},
            document: { querySelectorAll: () => [] },
            showView: noop,
            stopCountdown: noop,
            stopRevealStaging: noop,
            debug: noop,
            setSongStartHint: (mode) => calls.push(mode),
            renderLobbyView: noop,
            renderPlayingView: noop,
            renderRevealView: noop,
            renderEndView: noop,
            renderPausedView: noop,
        })({ phase, game_id: 'g1' });
        return calls;
    }

    it.each(['PLAYING', 'PAUSED', 'END', 'LOBBY'])('a %s state clears the pill', (phase) => {
        expect(render(phase)).toEqual([null]);
    });

    it('a REVEAL re-broadcast keeps it', () => {
        expect(render('REVEAL')).toEqual([]);
    });

    it('the markup carries the pill with the intro-wait dot and all three strings', () => {
        const start = TV_HTML.indexOf('id="dashboard-song-hint"');
        expect(start).toBeGreaterThan(TV_HTML.indexOf('id="dashboard-reveal"'));
        expect(start).toBeLessThan(TV_HTML.indexOf('id="dashboard-end"'));
        const pill = TV_HTML.slice(start, TV_HTML.indexOf('</div>', start));
        expect(pill).toContain('class="intro-wait__dot"');
        for (const key of ['game.songLoading', 'game.songLoadingSlow', 'game.songStartFailed']) {
            expect(pill).toContain(`data-i18n="${key}"`);
        }
    });
});

// ---------------------------------------------------------------- phone

let phoneEls = {};
global.window = global.window || {};
global.window.BeatifyUtils = global.window.BeatifyUtils || { t: (k) => k };
global.document = { getElementById: (id) => phoneEls[id] || null };

vi.mock('../player-utils.js', () => ({
    state: {},
    escapeHtml: (s) => String(s),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const { setSongStartHint, stopRevealCountdown } = await import('../player-reveal.js');

describe('#3604 phone song-start pill', () => {
    let hint;
    let view;
    beforeEach(() => {
        hint = el('reveal-song-hint');
        hint.classList.add('hidden');
        view = el('reveal-view');
        phoneEls = { 'reveal-song-hint': hint, 'reveal-view': view };
    });

    it('shows the loading pill on the reveal', () => {
        setSongStartHint('loading');
        expect(hint.classList.contains('hidden')).toBe(false);
        expect(hint.classList.contains('reveal-song-hint--failed')).toBe(false);
    });

    it('shows the failed state in orange', () => {
        setSongStartHint('failed');
        expect(hint.classList.contains('hidden')).toBe(false);
        expect(hint.classList.contains('reveal-song-hint--failed')).toBe(true);
    });

    it('ignores a notice while the reveal is not on screen', () => {
        view.classList.add('hidden');
        setSongStartHint('loading');
        expect(hint.classList.contains('hidden')).toBe(true);
    });

    it('leaving REVEAL clears it (stopRevealCountdown runs on every other phase)', () => {
        setSongStartHint('failed');
        stopRevealCountdown();
        expect(hint.classList.contains('hidden')).toBe(true);
        expect(hint.classList.contains('reveal-song-hint--failed')).toBe(false);
    });

    it('player-core routes both messages to the pill, not to a toast', () => {
        const core = readSource('player-core.js');
        const at = core.indexOf("data.type === 'song_starting'");
        expect(at).toBeGreaterThan(-1);
        const branch = core.slice(at, core.indexOf('return;', at));
        expect(branch).toContain("setSongStartHint(data.type === 'song_start_failed' ? 'failed' : 'loading')");
        expect(branch).not.toContain('showToast');
    });

    it('the markup carries the pill inside the reveal view', () => {
        const start = PHONE_HTML.indexOf('id="reveal-song-hint"');
        expect(start).toBeGreaterThan(PHONE_HTML.indexOf('id="reveal-view"'));
        expect(start).toBeLessThan(PHONE_HTML.indexOf('id="paused-view"'));
        const pill = PHONE_HTML.slice(start, PHONE_HTML.indexOf('</div>', start));
        expect(pill).toContain('data-i18n="game.songLoading"');
        expect(pill).toContain('data-i18n="game.songStartFailed"');
    });
});

// ---------------------------------------------------------------- i18n

describe('#3604 strings', () => {
    it('keeps the approved English wording', () => {
        const en = locale('en').game;
        expect(en.songLoading).toBe('Next song is loading…');
        expect(en.songLoadingSlow).toBe('The music service is slow right now');
        expect(en.songStartFailed).toBe("That song didn't start. Trying another one…");
    });

    it.each(['de', 'es', 'fr', 'it', 'nl'])('%s translates all three keys', (lang) => {
        const en = locale('en').game;
        const game = locale(lang).game;
        for (const key of ['songLoading', 'songLoadingSlow', 'songStartFailed']) {
            expect(typeof game[key]).toBe('string');
            expect(game[key].length).toBeGreaterThan(0);
            expect(game[key]).not.toBe(en[key]);
        }
    });
});

describe('#3626 phone pill stays in view', () => {
    const css = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
    const rule = (selector) => {
        const at = css.indexOf(`\n${selector} {`);
        expect(at).toBeGreaterThan(-1);
        return css.slice(at, css.indexOf('}', at));
    };

    it('is pinned to the viewport, not inline in the scrolling reveal', () => {
        const base = rule('.reveal-song-hint');
        expect(base).toContain('position: fixed');
        expect(base).toMatch(/bottom: calc\(5\.5rem/);
        expect(base).toContain('pointer-events: none');
    });

    it('sits above the reaction bar and the admin bar when that is up', () => {
        const admin = rule('main:has(.admin-control-bar:not(.hidden)) .reveal-song-hint');
        expect(admin).toMatch(/bottom: calc\(5\.5rem \+ 70px/);
    });
});
