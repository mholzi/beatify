/**
 * #3152 — "Song over · keep guessing" once the song sample has run out.
 *
 * With a song length shorter than the answer time, the speaker goes silent
 * while the countdown is still running. The server says so with
 * `sample_stopped`, and the TV and the phones show the existing intro chip in
 * its stopped state with one line of text. Nothing is shown while the music
 * plays, and an intro round keeps its own two texts exactly as before.
 *
 * Both screens run their shipped code: the TV's renderPlayingView is cut out of
 * the dashboard IIFE (helpers/js-source.js), the phone's updateGameView is
 * imported from the module.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { declaration, evaluate, readSource, locale as readLocale } from './helpers/js-source.js';

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const i18n = Object.fromEntries(LOCALES.map((l) => [l, readLocale(l)]));
let lang = 'en';
const t = (key) =>
    key.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), i18n[lang]) ?? key;

/** An element stub; `withLabel` gives it the inner `[data-i18n]` span of the chip. */
function makeEl({ withLabel = false, hidden = true } = {}) {
    const classes = new Set(hidden ? ['hidden'] : []);
    const label = { textContent: 'INTRO ROUND', _attrs: { 'data-i18n': 'game.introRound' } };
    label.setAttribute = (k, v) => { label._attrs[k] = v; };
    const el = {
        textContent: '', className: '', disabled: false, _attrs: {}, style: {}, label,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => {
                const want = on === undefined ? !classes.has(c) : on;
                if (want) classes.add(c); else classes.delete(c);
                return classes.has(c);
            },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        querySelector: (sel) => (withLabel && sel === '[data-i18n]' ? label : null),
        querySelectorAll: () => [],
        appendChild: (c) => c,
        addEventListener: () => {},
    };
    return el;
}

/** What a guest reads off the chip. */
function read(chip) {
    return {
        shown: !chip.classList.contains('hidden'),
        stopped: chip.classList.contains('intro-badge--stopped'),
        text: chip.label.textContent,
        key: chip.label._attrs['data-i18n'],
    };
}

const EXPECTED = {
    en: 'Song over · keep guessing',
    de: 'Song vorbei · weiter raten',
    es: 'Canción terminada · sigue adivinando',
    fr: 'Chanson terminée · continuez à deviner',
    it: 'Canzone finita · continua a indovinare',
    nl: 'Nummer voorbij · blijf gokken',
};

// ---- phone: the real module, with the DOM and player-utils stubbed ----------
global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.window = {
    BeatifyUtils: { t },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
let phoneEls;
global.document = { getElementById: (id) => phoneEls[id] || null, createElement: () => makeEl() };

vi.mock('../player-utils.js', () => {
    const state = { ws: null, playerName: 'Ada' };
    return {
        state,
        escapeHtml: (s) => String(s),
        showConfirmModal: async () => true,
        prefersReducedMotion: () => true,
        animateValue: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
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
        isTitleArtistMode: () => false,
        createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
    };
});

const { updateGameView, resetSubmissionState } = await import('../player-game.js');

// ---- TV: renderPlayingView cut out of the dashboard IIFE --------------------
const DASHBOARD = readSource('dashboard.js');
const TV_SNIPPETS = [
    'var lastCountdownDeadline = null;',
    'var countdownInterval = null;',
    ...['renderPlayingView', 'renderRoundStats', 'startCountdown', 'stopCountdown', 'showRestingTimer'].map(
        (name) => declaration(DASHBOARD, name, 'dashboard.js'),
    ),
];
let tvEls;
function tvRender() {
    const noop = () => {};
    return evaluate(TV_SNIPPETS, 'renderPlayingView', {
        document: { getElementById: (id) => tvEls[id] || null },
        utils: { t },
        debug: noop,
        lastRenderedRound: null,
        songStoppedRound: null,
        setSongStoppedChip: noop,
        renderJoinCorner: noop,
        renderLeaderboard: noop,
        renderGhostLeague: noop,
        renderSuddenDeathFinalBanner: noop,
        renderFinaleDoubleBanner: noop,
        renderFinalePlayoffBanner: noop,
    });
}

function frame(extra) {
    return Object.assign({
        phase: 'PLAYING',
        round: 4,
        total_rounds: 10,
        deadline: Date.now() + 20_000,
        round_duration: 30,
        sample_duration: 15,
        sample_stopped: false,
        is_intro_round: false,
        intro_stopped: false,
        players: [{ name: 'Ada' }, { name: 'Bob' }],
        leaderboard: [],
    }, extra);
}

const SCREENS = [
    {
        name: 'TV',
        show: (data) => { tvRender()(data); return tvEls['dashboard-intro-badge']; },
    },
    {
        name: 'phone',
        show: (data) => { updateGameView(data); return phoneEls['intro-badge']; },
    },
];

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000);
    lang = 'en';
    tvEls = { 'dashboard-intro-badge': makeEl({ withLabel: true }) };
    phoneEls = { 'intro-badge': makeEl({ withLabel: true }), 'intro-splash': makeEl() };
    resetSubmissionState();
});
afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

describe.each(SCREENS)('#3152 the song-over chip on the $name', ({ show }) => {
    it('shows nothing while the music plays', () => {
        const chip = show(frame({ sample_stopped: false }));
        expect(read(chip).shown).toBe(false);
        expect(read(chip).stopped).toBe(false);
    });

    it('shows nothing in a game without a song length', () => {
        const chip = show(frame({ sample_duration: 0 }));
        expect(read(chip).shown).toBe(false);
    });

    it('shows the stopped chip with the song-over line once the music has stopped', () => {
        const chip = show(frame({ sample_stopped: true }));
        expect(read(chip)).toEqual({
            shown: true,
            stopped: true,
            text: 'Song over · keep guessing',
            key: 'game.sampleStopped',
        });
    });

    it.each(LOCALES)('says it in %s', (code) => {
        lang = code;
        const chip = show(frame({ sample_stopped: true }));
        expect(read(chip).text).toBe(EXPECTED[code]);
    });

    it('goes from hidden to the stopped chip without the gold intro state in between', () => {
        const before = read(show(frame({ sample_stopped: false })));
        expect(before.shown).toBe(false);
        const after = read(show(frame({ sample_stopped: true })));
        expect(after.shown).toBe(true);
        expect(after.stopped).toBe(true);
        expect(after.text).not.toBe('INTRO ROUND');
    });

    it('hides the chip again on the next round', () => {
        show(frame({ sample_stopped: true }));
        const chip = show(frame({ round: 5, sample_stopped: false }));
        expect(read(chip)).toMatchObject({ shown: false, stopped: false });
    });

    it('leaves an intro round as it was: INTRO ROUND while the intro runs', () => {
        // The sample (10s) ended before the intro's own 15s.
        const chip = show(frame({ is_intro_round: true, intro_stopped: false, sample_stopped: true }));
        expect(read(chip)).toEqual({ shown: true, stopped: false, text: 'INTRO ROUND', key: 'game.introRound' });
    });

    it('leaves an intro round as it was: "Intro complete!" afterwards', () => {
        const chip = show(frame({ is_intro_round: true, intro_stopped: true, sample_stopped: true }));
        expect(read(chip)).toEqual({ shown: true, stopped: true, text: 'Intro complete!', key: 'game.introStopped' });
    });
});

describe('#3152 the song-over line exists in every locale', () => {
    it.each(LOCALES)('%s', (code) => {
        expect(i18n[code].game.sampleStopped).toBe(EXPECTED[code]);
    });
});
