/**
 * #2647: the one sentence the lobby says out loud.
 *
 * The complaint in the issue is a surprise, not a knowledge gap — the room
 * learns in round 2, at the first skull, that Sudden Death is on, although the
 * server has sent every flag in every phase since #1867. So what these tests
 * guard is not "a string appears" but the three decisions the sentence rests
 * on:
 *
 *  1. **What counts as normal** is the server's own default, read out of the
 *     `GameOptions` dataclass in `game/config.py` rather than restated here.
 *     A new game option fails this suite until somebody decides whether the
 *     room should hear about it — which is the point.
 *  2. **The cap.** Three named deviations, then a counted tail. Past three the
 *     sentence stops being one glance, and a rank order decides which three.
 *  3. **The prose is per locale, not per word.** Each locale owns whole
 *     clauses and whole sentence shapes; this only picks which clauses appear.
 *     So every locale is rendered here and has to come out whole.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, locale, readSource, REPO_DIR } from './helpers/js-source.js';
import { el, translator } from './helpers/mini-dom.js';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const T = Object.fromEntries(LOCALES.map((l) => [l, translator(locale(l)).t]));

/** A LOBBY payload: an entirely default game, ten rounds long. */
function lobby(overrides) {
    return Object.assign(
        {
            phase: 'LOBBY',
            total_rounds: 10,
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

// ---------------------------------------------------------------------------
// 1. "Normal" is the server default, and nothing else
// ---------------------------------------------------------------------------

const CONFIG_PY = readFileSync(
    join(REPO_DIR, 'custom_components', 'beatify', 'game', 'config.py'),
    'utf8',
);
const CONST_PY = readFileSync(
    join(REPO_DIR, 'custom_components', 'beatify', 'const.py'),
    'utf8',
);

/** Read a top-level `NAME = <literal>` out of const.py. */
function pyConst(name) {
    const m = new RegExp(`^${name}\\s*(?::[^=]+)?=\\s*(.+?)\\s*(?:#.*)?$`, 'm').exec(CONST_PY);
    if (!m) throw new Error(`${name} not found in const.py`);
    return pyLiteral(m[1]);
}

function pyLiteral(raw) {
    const text = String(raw).trim();
    if (text === 'True') return true;
    if (text === 'False') return false;
    if (/^-?\d+$/.test(text)) return Number(text);
    const str = /^['"](.*)['"]$/.exec(text);
    if (str) return str[1];
    if (/^[A-Z_][A-Z0-9_]*$/.test(text)) return pyConst(text);   // one level of alias
    return undefined;   // default_factory and friends — not a scalar option
}

/** `GameOptions` field -> default value, straight out of the dataclass body. */
function gameOptionDefaults() {
    const body = /^class GameOptions:\n([\s\S]*?)\n {4}@classmethod/m.exec(CONFIG_PY);
    if (!body) throw new Error('GameOptions not found in game/config.py');
    const out = {};
    for (const line of body[1].split('\n')) {
        const m = /^ {4}([a-z_]+)\s*:\s*[^=]+=\s*(.+?)\s*$/.exec(line);
        if (m) out[m[1]] = pyLiteral(m[2]);
    }
    return out;
}

/**
 * Options the sentence deliberately never names, with the reason. Everything
 * else must be in LOBBY_BRIEF_DEFAULTS — that is what makes a newly added
 * option a decision rather than an omission.
 */
const NOT_IN_SENTENCE = {
    provider: 'where the music comes from — not a rule of the game',
    platform: 'playback routing, invisible to players',
    max_rounds: 'a cap on the pool; the sentence says the resulting round count',
    reveal_auto_advance: 'host pacing, nothing a player can act on',
    artist_challenge_enabled: 'defaults ON and is not in the state payload — see the PR',
    movie_quiz_enabled: 'defaults ON and is not in the state payload — see the PR',
};

const DEFAULTS = evaluate(
    declaration(readSource('utils.js'), 'LOBBY_BRIEF_DEFAULTS', 'utils.js'),
    'LOBBY_BRIEF_DEFAULTS',
);

describe('what counts as normal (#2647)', () => {
    it('reads the Python dataclass at all', () => {
        const opts = gameOptionDefaults();
        expect(opts.round_duration).toBe(pyConst('DEFAULT_ROUND_DURATION'));
        expect(opts.difficulty).toBe(pyConst('DIFFICULTY_DEFAULT'));
        expect(Object.keys(opts).length).toBeGreaterThan(10);
    });

    it('mirrors every default it claims to mirror', () => {
        const opts = gameOptionDefaults();
        for (const [field, value] of Object.entries(DEFAULTS)) {
            expect(field in opts, `${field} is not a GameOptions field`).toBe(true);
            expect(opts[field], `default of ${field}`).toBe(value);
        }
    });

    it('accounts for every game option — a new one has to be decided on', () => {
        for (const field of Object.keys(gameOptionDefaults())) {
            const known = field in DEFAULTS || field in NOT_IN_SENTENCE;
            expect(known, `new game option "${field}": name it in the lobby sentence or list it in NOT_IN_SENTENCE`).toBe(true);
        }
    });
});

// ---------------------------------------------------------------------------
// 2. The sentence itself
// ---------------------------------------------------------------------------

describe('the sentence (#2647)', () => {
    const surprise = lobby({
        sudden_death_mode: true,
        title_artist_mode: true,
        round_duration: 20,
    });

    it('reads, in German, the game the issue describes', () => {
        expect(U.buildLobbyBrief(surprise, T.de).text).toBe(
            '10 Runden, ihr ratet Titel und Interpret statt des Jahres, '
            + 'jeder Song läuft nur 20 Sekunden — und wer einmal danebenliegt, ist raus.',
        );
    });

    it('reads, in English, the same game', () => {
        expect(U.buildLobbyBrief(surprise, T.en).text).toBe(
            '10 rounds, you are guessing title and artist instead of the year, '
            + 'every song runs just 20 seconds — and a single wrong answer knocks you out.',
        );
    });

    it('still says something for a game with nothing unusual about it', () => {
        expect(U.buildLobbyBrief(lobby(), T.de).text).toBe('10 Runden, ganz normale Regeln.');
        expect(U.buildLobbyBrief(lobby(), T.en).text).toBe('10 rounds, standard rules.');
    });

    it('names a single deviation without a conjunction', () => {
        const one = lobby({ sudden_death_mode: true });
        expect(U.buildLobbyBrief(one, T.en).text)
            .toBe('10 rounds, a single wrong answer knocks you out.');
    });

    it('agrees with a one-round game', () => {
        expect(U.buildLobbyBrief(lobby({ total_rounds: 1 }), T.de).text)
            .toBe('1 Runde, ganz normale Regeln.');
    });

    it('says nothing at all when the round count is unknown', () => {
        // An older server, or a payload that never carried total_rounds: the
        // line hides and the lobby looks exactly as it did before #2647.
        expect(U.buildLobbyBrief(lobby({ total_rounds: undefined }), T.de)).toBeNull();
        expect(U.buildLobbyBrief(lobby({ total_rounds: 0 }), T.de)).toBeNull();
        expect(U.buildLobbyBrief(null, T.de)).toBeNull();
    });

    it('reads a float round_duration as whole seconds', () => {
        // The server stores it as a float (30.0) — #1867.
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30.0 }), T.en);
        expect(brief.text).toContain('every song runs just 30 seconds');
    });
});

// ---------------------------------------------------------------------------
// 3. The cap at three
// ---------------------------------------------------------------------------

describe('the cap at three named deviations (#2647)', () => {
    it('names three and counts the fourth', () => {
        const four = lobby({
            sudden_death_mode: true,
            round_duration: 20,
            sabotage_enabled: true,
            comeback_token_enabled: true,
        });
        const brief = U.buildLobbyBrief(four, T.en);
        expect(brief.named).toBe(3);
        expect(brief.hidden).toBe(1);
        expect(brief.text).toBe(
            '10 rounds, every song runs just 20 seconds, everyone gets one sabotage to spend, '
            + 'plus one more twist — and a single wrong answer knocks you out.',
        );
    });

    it('counts every deviation past the third, not just the fourth', () => {
        const six = lobby({
            sudden_death_mode: true,
            round_duration: 20,
            sabotage_enabled: true,
            comeback_token_enabled: true,
            finale_double_enabled: true,
            rampup_order_enabled: true,
        });
        const brief = U.buildLobbyBrief(six, T.en);
        expect(brief.named).toBe(3);
        expect(brief.hidden).toBe(3);
        expect(brief.text).toContain('plus 3 more twists');
    });

    it('drops the least interesting, never the elimination rule', () => {
        // Rank order is "changes how you play": whatever else is on, the rule
        // that can knock you out of the game is the one that survives the cap
        // and closes the sentence.
        const noisy = lobby({
            sudden_death_mode: true,
            rampup_order_enabled: true,
            comeback_token_enabled: true,
            finale_double_enabled: true,
            finale_tiebreaker_enabled: true,
        });
        const brief = U.buildLobbyBrief(noisy, T.en);
        expect(brief.text).toContain('a single wrong answer knocks you out.');
        expect(brief.text).not.toContain('easiest to hardest');
    });
});

// ---------------------------------------------------------------------------
// 4. Rules that are not running are not named
// ---------------------------------------------------------------------------

describe('Title & Artist suppression (#2647, mirrors #1180)', () => {
    it('never names a year-round rule in a Title & Artist game', () => {
        // The admin's icon row already hides these behind `yearRoundActive`
        // (admin/sections/game-settings.js). Naming "only the closest guess
        // scores" here would describe a rule that is not running.
        const ta = lobby({
            title_artist_mode: true,
            difficulty: 'hard',
            closest_wins_mode: true,
            intro_mode_enabled: true,
            difficulty_bet_scaling_enabled: true,
        });
        const brief = U.buildLobbyBrief(ta, T.en);
        expect(brief.named).toBe(1);
        expect(brief.hidden).toBe(0);
        expect(brief.text).toBe(
            '10 rounds, you are guessing title and artist instead of the year.',
        );
    });

    it('does name them in a year game', () => {
        const hard = lobby({ difficulty: 'hard', closest_wins_mode: true });
        const brief = U.buildLobbyBrief(hard, T.en);
        expect(brief.text).toContain('only the closest guess scores');
        expect(brief.text).toContain('only a near-perfect guess scores');
    });

    it('treats an unknown difficulty as normal rather than inventing a clause', () => {
        expect(U.buildLobbyBrief(lobby({ difficulty: 'brutal' }), T.en).text)
            .toBe('10 rounds, standard rules.');
    });
});

// ---------------------------------------------------------------------------
// 5. Six locales, one sentence each
// ---------------------------------------------------------------------------

describe('every locale renders a whole sentence (#2647)', () => {
    const cases = {
        standard: lobby(),
        one: lobby({ sudden_death_mode: true }),
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
                // No placeholder survives, no raw key leaks, and it ends as a
                // sentence — the three ways generated prose usually breaks.
                expect(brief.text).not.toMatch(/[{}]/);
                expect(brief.text).not.toContain('lobby.brief');
                expect(brief.text.trim().endsWith('.')).toBe(true);
                expect(brief.text.length).toBeGreaterThan(12);
            });
        }
    }

    it('has no locale silently falling back to another', () => {
        const data = cases.three;
        const rendered = LOCALES.map((l) => U.buildLobbyBrief(data, T[l]).text);
        expect(new Set(rendered).size).toBe(LOCALES.length);
    });
});

// ---------------------------------------------------------------------------
// 6. What lands on the screen
// ---------------------------------------------------------------------------

describe('the rendered line (#2647)', () => {
    it('colours the closing clause, the first middle clause, and nothing else', () => {
        const brief = U.buildLobbyBrief(
            lobby({ sudden_death_mode: true, title_artist_mode: true, round_duration: 20 }),
            T.en,
        );
        expect(brief.html).toContain(
            '<span class="lobby-brief-em lobby-brief-em--key">a single wrong answer knocks you out</span>',
        );
        expect(brief.html).toContain(
            '<span class="lobby-brief-em lobby-brief-em--alt">you are guessing title and artist instead of the year</span>',
        );
        expect(brief.html).toContain(
            '<span class="lobby-brief-em">every song runs just 20 seconds</span>',
        );
        // "10 rounds" is not news: it carries no span at all.
        expect(brief.html.startsWith('10 rounds,')).toBe(true);
    });

    it('escapes what it interpolates', () => {
        const angry = U.buildLobbyBrief(lobby(), (key, params) => {
            if (key === 'lobby.brief.rounds') return '<b>10</b> rounds';
            return translator(locale('en')).t(key, params);
        });
        expect(angry.html).not.toContain('<b>');
        expect(angry.html).toContain('&lt;b&gt;10&lt;/b&gt;');
    });

    it('shows the line, and hides it again when there is nothing to say', () => {
        const node = el('dashboard-lobby-brief');
        node.classList.add('hidden');

        U.renderLobbyBrief(node, lobby(), T.de);
        expect(node.classList.contains('hidden')).toBe(false);
        expect(node.innerHTML).toContain('Runden');

        U.renderLobbyBrief(node, lobby({ total_rounds: 0 }), T.de);
        expect(node.classList.contains('hidden')).toBe(true);
        expect(node.innerHTML).toBe('');
    });

    it('does not throw on a missing element', () => {
        expect(U.renderLobbyBrief(null, lobby(), T.de)).toBeNull();
    });
});
