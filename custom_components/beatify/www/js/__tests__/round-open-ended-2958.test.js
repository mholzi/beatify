/**
 * #2958: a game without a round cap says "Round 7", not "Round 7 of 266".
 *
 * `max_rounds: 0` means "play every song" (#1475). `total_rounds` is then only
 * the size of the playable pool — a number nobody chose and nobody plays
 * through. The rule is mechanical: no cap, no total. Capped games keep
 * "Round 3 of 10" and "10 rounds, …" exactly as before.
 */
import { describe, it, expect } from 'vitest';
import { locale, readSource } from './helpers/js-source.js';
import { el, translator } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const T = Object.fromEntries(LOCALES.map((l) => [l, translator(locale(l)).t]));

function lobby(overrides) {
    return Object.assign(
        {
            phase: 'LOBBY',
            total_rounds: 266,
            max_rounds: 0,
            round_duration: 45,
            difficulty: 'normal',
            title_artist_mode: false,
            sudden_death_mode: false,
            closest_wins_mode: false,
            intro_mode_enabled: false,
            rampup_order_enabled: false,
            comeback_token_enabled: false,
            sabotage_enabled: false,
            finale_double_enabled: false,
            finale_tiebreaker_enabled: false,
            difficulty_bet_scaling_enabled: false,
        },
        overrides,
    );
}

describe('isOpenEnded (#2958)', () => {
    it('is true only for an explicit max_rounds of 0', () => {
        expect(U.isOpenEnded({ max_rounds: 0 })).toBe(true);
        expect(U.isOpenEnded({ max_rounds: 10 })).toBe(false);
        // An older server that does not send the field keeps the old display.
        expect(U.isOpenEnded({ total_rounds: 266 })).toBe(false);
        expect(U.isOpenEnded(null)).toBe(false);
    });
});

describe('applyRoundTotal (#2958)', () => {
    it('marks the indicator open for an uncapped game and clears it for a capped one', () => {
        const chipA = el('a');
        const chipB = el('b');
        U.applyRoundTotal([chipA, chipB], { max_rounds: 0 });
        expect(chipA.classList.contains('round-open')).toBe(true);
        expect(chipB.classList.contains('round-open')).toBe(true);
        U.applyRoundTotal([chipA, chipB], { max_rounds: 10 });
        expect(chipA.classList.contains('round-open')).toBe(false);
        expect(chipB.classList.contains('round-open')).toBe(false);
    });

    it('accepts a single element and ignores null', () => {
        const chip = el('c');
        U.applyRoundTotal(chip, { max_rounds: 0 });
        expect(chip.classList.contains('round-open')).toBe(true);
        expect(() => U.applyRoundTotal(null, { max_rounds: 0 })).not.toThrow();
    });
});

describe('the lobby sentence without a round cap (#2958)', () => {
    it('drops the rounds part and opens with a capital (en)', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30 }), T.en);
        expect(brief.text).toBe('Every song runs just 30 seconds.');
        expect(brief.html).toContain('Every song runs just 30 seconds');
        expect(brief.text).not.toContain('266');
    });

    it('keeps a standard sentence when nothing deviates', () => {
        expect(U.buildLobbyBrief(lobby(), T.en).text).toBe('Standard rules.');
    });

    it('leaves a capped game exactly as it was', () => {
        const brief = U.buildLobbyBrief(
            lobby({ total_rounds: 10, max_rounds: 10, round_duration: 30 }),
            T.en,
        );
        expect(brief.text).toBe('10 rounds, every song runs just 30 seconds.');
    });

    const cases = {
        standard: lobby(),
        one: lobby({ round_duration: 30 }),
        two: lobby({ sudden_death_mode: true, round_duration: 20 }),
        three: lobby({ sudden_death_mode: true, title_artist_mode: true, round_duration: 20 }),
        capped: lobby({
            sudden_death_mode: true,
            round_duration: 20,
            sabotage_enabled: true,
            comeback_token_enabled: true,
            finale_double_enabled: true,
        }),
    };
    for (const lang of LOCALES) {
        for (const [name, data] of Object.entries(cases)) {
            it(`${lang} · ${name}`, () => {
                const brief = U.buildLobbyBrief(data, T[lang]);
                expect(brief).not.toBeNull();
                expect(brief.text).not.toMatch(/[{}]/);
                expect(brief.text).not.toContain('lobby.brief');
                expect(brief.text).not.toContain('266');
                expect(brief.text.trim().endsWith('.')).toBe(true);
                const first = brief.text.charAt(0);
                expect(first).toBe(first.toUpperCase());
            });
        }
    }
});

describe('the TV settings chip (#2958)', () => {
    it('has an "All songs" label in every locale', () => {
        for (const lang of LOCALES) {
            const label = T[lang]('dashboard.allSongs');
            expect(label).not.toBe('dashboard.allSongs');
            expect(label.length).toBeGreaterThan(3);
        }
    });

    it('prints "All songs" instead of the pool size for an uncapped game', () => {
        const src = readSource('dashboard.js');
        const fn = src.slice(src.indexOf('function renderGameSettings('));
        const body = fn.slice(0, fn.indexOf('\n    }\n'));
        expect(body).toContain("utils.isOpenEnded(data)");
        expect(body).toContain("'dashboard.allSongs'");
    });
});

describe('every "Round X of Y" can drop its total (#2958)', () => {
    const pages = {
        'dashboard.html': ['dashboard-total-rounds', 'reveal-total-num'],
        'player.html': ['total-rounds', 'reveal-total'],
        'admin.html': ['admin-total-rounds', 'admin-reveal-total'],
    };
    for (const [page, hooks] of Object.entries(pages)) {
        it(page, () => {
            const html = readSource(`../${page}`);
            for (const hook of hooks) {
                const tag = html.match(new RegExp(`<[^>]*${hook}[^>]*>`));
                expect(tag, `${page}: ${hook}`).not.toBeNull();
                expect(tag[0], `${page}: ${hook}`).toContain('round-total-part');
            }
        });
    }

    it('styles.css hides the marked parts under .round-open', () => {
        expect(readSource('../css/styles.css')).toMatch(
            /\.round-open \.round-total-part\s*\{\s*display:\s*none;/,
        );
    });
});
