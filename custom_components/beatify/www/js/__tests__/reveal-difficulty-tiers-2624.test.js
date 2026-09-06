/**
 * #2624 — the reveal's emotion tiers must come from the scoring table.
 *
 * `showRevealEmotion` split "close" from "wrong" at fixed distances of 2 and 5
 * years, and the duel gap coloured itself at 5. The server awards points from
 * `DIFFICULTY_SCORING` (const.py): close_range 7/3/2 and near_range 10/5/0 for
 * easy/normal/hard. The two only agreed on Normal:
 *
 *   - Easy, 6 years off:  5 points on the board, "WAY OFF!" on the screen.
 *   - Hard, 3 years off:  0 points on the board, "SO CLOSE!" on the screen.
 *
 * Both now read `classifyYearsOff`, which is the JS side of that same table, so
 * the face, the gap colour and the score cannot contradict each other. The
 * numbers themselves are guarded against const.py by
 * tests/unit/test_reveal_difficulty_parity_2624.py.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const EN = JSON.parse(readFileSync(join(__dirname, '..', '..', 'i18n', 'en.json'), 'utf8'));

function makeEl(id, extraClasses) {
    const classes = new Set(extraClasses || []);
    const el = {
        id,
        textContent: '',
        innerHTML: '',
        _attrs: {},
        _parent: null,
        get className() { return [...classes].join(' '); },
        set className(v) {
            classes.clear();
            String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c));
        },
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
        getAttribute: (k) => el._attrs[k],
        querySelector: () => null,
        closest: (sel) => (sel === '.duel-gap' ? el._parent : null),
    };
    return el;
}

// Populated per test; the real player-utils.js touches the DOM at module load.
let els = {};
global.window = {
    BeatifyUtils: {
        t: (key, params) => {
            const v = key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), EN);
            if (v === undefined) return key;
            if (typeof v === 'string' && params) {
                return Object.keys(params).reduce((s, p) => s.replace(new RegExp(`\\{${p}\\}`, 'g'), params[p]), v);
            }
            return v;
        },
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    // player-utils.js reads window.location.search at module load (state.gameId);
    // importOriginal() below evaluates the real module, so it has to be there.
    location: { search: '', protocol: 'http:', host: 'ha.local', origin: 'http://ha.local' },
};
global.WebSocket = { OPEN: 1 };
global.document = {
    getElementById: (id) => (els && els[id]) || null,
    querySelector: () => null,
};

const mockState = { playerName: 'Alice', lastDifficulty: '', lastRevealContext: null };
vi.mock('../player-utils.js', async (importOriginal) => {
    const real = await importOriginal();
    return {
        state: mockState,
        escapeHtml: (s) => String(s),
        prefersReducedMotion: () => true,
        animateValue: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
        AnimationUtils: {},
        triggerConfetti: () => {},
        stopConfetti: () => {},
        isTitleArtistMode: (data) => !!(data && data.title_artist_mode),
        createModalFocusTrap: () => ({}),
        // the classifier under test is the REAL one
        classifyYearsOff: real.classifyYearsOff,
        DIFFICULTY_SCORING: real.DIFFICULTY_SCORING,
    };
});
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const { updateRevealView, stopRevealCountdown } = await import('../player-reveal.js');
const { classifyYearsOff, DIFFICULTY_SCORING } = await import('../player-utils.js');

beforeEach(() => {
    const gap = makeEl('duel-gap-wrapper', ['duel-gap']);
    const gapCount = makeEl('duel-gap-count');
    gapCount._parent = gap;
    els = {
        'reveal-round': makeEl('reveal-round'),
        'reveal-total': makeEl('reveal-total'),
        'reveal-emotion': makeEl('reveal-emotion'),
        'duel-your-year': makeEl('duel-your-year'),
        'duel-gap-count': gapCount,
        'duel-gap-unit': makeEl('duel-gap-unit'),
        _gap: gap,
    };
    mockState.playerName = 'Alice';
    mockState.lastDifficulty = '';
});

afterEach(() => stopRevealCountdown());

function reveal(difficulty, yearsOff) {
    updateRevealView({
        round: 1,
        total_rounds: 10,
        difficulty,
        song: { title: 'Africa', artist: 'Toto', year: 1982 },
        players: [{ name: 'Alice', is_admin: false, guess: 1982 - yearsOff, years_off: yearsOff, missed_round: false }],
    });
    return {
        emotion: els['reveal-emotion'].className,
        gap: els._gap.className,
    };
}

describe('#2624 classifyYearsOff mirrors DIFFICULTY_SCORING', () => {
    it('splits at close_range and near_range per difficulty', () => {
        for (const [difficulty, cfg] of Object.entries(DIFFICULTY_SCORING)) {
            expect(classifyYearsOff(0, difficulty), `${difficulty}: exact`).toBe('exact');
            expect(classifyYearsOff(cfg.close_range, difficulty), `${difficulty}: close_range`).toBe('scored');
            if (cfg.near_range > 0) {
                expect(classifyYearsOff(cfg.close_range + 1, difficulty)).toBe('close');
                expect(classifyYearsOff(cfg.near_range, difficulty)).toBe('close');
                expect(classifyYearsOff(cfg.near_range + 1, difficulty)).toBe('missed');
            } else {
                // hard has no consolation band at all
                expect(classifyYearsOff(cfg.close_range + 1, difficulty)).toBe('missed');
            }
        }
    });

    it('treats an unknown or missing difficulty as normal', () => {
        expect(classifyYearsOff(3, 'nonsense')).toBe(classifyYearsOff(3, 'normal'));
        expect(classifyYearsOff(3, undefined)).toBe(classifyYearsOff(3, 'normal'));
        expect(classifyYearsOff(6, '')).toBe('missed');
    });

    it('has no opinion without a guess', () => {
        expect(classifyYearsOff(null, 'easy')).toBe('missed');
        expect(classifyYearsOff(undefined, 'easy')).toBe('missed');
    });
});

describe('#2624 the reveal face agrees with the scoreboard', () => {
    it('easy: 6 years off scores 5 points, so it must not show the sad face', () => {
        const { emotion, gap } = reveal('easy', 6);
        expect(emotion).toContain('reveal-emotion--close');
        expect(emotion).not.toContain('reveal-emotion--wrong');
        expect(gap).toContain('duel-gap--close');
    });

    it('easy: past near_range (11 years) it is a miss on both', () => {
        const { emotion, gap } = reveal('easy', 11);
        expect(emotion).toContain('reveal-emotion--wrong');
        expect(gap).toContain('duel-gap--wrong');
    });

    it('hard: 3 years off scores nothing, so it must not say "so close"', () => {
        const { emotion, gap } = reveal('hard', 3);
        expect(emotion).toContain('reveal-emotion--wrong');
        expect(emotion).not.toContain('reveal-emotion--close');
        expect(gap).toContain('duel-gap--wrong');
    });

    it('hard: inside close_range (2 years) it is still a win', () => {
        const { emotion, gap } = reveal('hard', 2);
        expect(emotion).toContain('reveal-emotion--close');
        expect(gap).toContain('duel-gap--close');
    });

    it('normal is unchanged: 2 close, 5 close, 6 wrong', () => {
        expect(reveal('normal', 2).emotion).toContain('reveal-emotion--close');
        expect(reveal('normal', 5).emotion).toContain('reveal-emotion--close');
        expect(reveal('normal', 6).emotion).toContain('reveal-emotion--wrong');
    });

    it('an exact year is exact on every difficulty', () => {
        for (const d of ['easy', 'normal', 'hard']) {
            const { emotion, gap } = reveal(d, 0);
            expect(emotion, d).toContain('reveal-emotion--exact');
            expect(gap, d).toContain('duel-gap--exact');
        }
    });

    it('falls back to the lobby difficulty when the payload omits it', () => {
        mockState.lastDifficulty = 'easy';
        updateRevealView({
            song: { title: 'Africa', artist: 'Toto', year: 1982 },
            players: [{ name: 'Alice', guess: 1976, years_off: 6, missed_round: false }],
        });
        expect(els['reveal-emotion'].className).toContain('reveal-emotion--close');
    });
});
