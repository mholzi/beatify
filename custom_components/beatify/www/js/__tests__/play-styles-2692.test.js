/**
 * #2692 — six finished modes get a way in.
 *
 * Ramp-up, Finale ×2, the finale tiebreaker, the Comeback Token, difficulty bet
 * scaling and Sabotage were complete down to six-language strings, and their
 * only switches sat in `admin.html:581-656` — a panel `styles.css:10181` hides
 * with `display: none !important`. `grep -ciE "sabotage|comeback|ramp|finale"`
 * over `wizard.js` returned 0; over `game/config.py` it returned 12.
 *
 * Making them reachable is the small half. The half worth testing is what
 * happens after: a host with eight guests watching makes ONE decision, so the
 * step leads with a play style and folds the eleven switches underneath it.
 * Three things can quietly go wrong there, and each has its own describe below:
 *
 *  1. **A style that only adds.** Switching from Chaos back to Classic would
 *     leave Sabotage running — a mode nobody chose, taking turns away from
 *     guests, with no visible cause. `applyPlayStyle` turns everything it does
 *     not name OFF, and that is asserted directly.
 *
 *  2. **A stale style label.** After one hand-flipped switch the combination is
 *     no longer the style that was tapped. `detectPlayStyle` recomputes from the
 *     switches and returns null, so the UI can say "custom" instead of lying.
 *
 *  3. **A setting that never reaches the server.** The wizard writes
 *     `beatify_game_settings`; `admin/util.js` reads it back into `adminState`;
 *     `admin.js` posts it. Two of the six were missing from the middle step
 *     entirely, so they were lost on every page load even for a host who found
 *     the hidden panel.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// wizard.js is a page module: it touches browser globals at import time. Stub
// them first so the style helpers can be exercised for real rather than matched
// as source text — the difference matters, because a style that only *adds*
// still contains every substring a source match would look for.
global.window = global.window || {
    BeatifyUtils: { t: (key) => key },
    localStorage: { getItem: () => null, setItem: () => {} },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { search: '' },
};
global.localStorage = global.localStorage || global.window.localStorage;
global.document = global.document || {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} }, style: {} }),
    body: { classList: { add() {}, remove() {} } },
};

const __dirname = dirname(fileURLToPath(import.meta.url));
const BEATIFY = join(__dirname, '..', '..', '..');

const ADMIN_HTML = readFileSync(join(BEATIFY, 'www', 'admin.html'), 'utf8');
const WIZARD_SRC = readFileSync(join(BEATIFY, 'www', 'js', 'wizard.js'), 'utf8');
const UTIL_SRC = readFileSync(join(BEATIFY, 'www', 'js', 'admin', 'util.js'), 'utf8');
const ADMIN_SRC = readFileSync(join(BEATIFY, 'www', 'js', 'admin.js'), 'utf8');

const { PLAY_STYLES, applyPlayStyle, detectPlayStyle } = await import('../wizard.js');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const locale = (code) =>
    JSON.parse(readFileSync(join(BEATIFY, 'www', 'i18n', `${code}.json`), 'utf8'));

/** The six modes this issue is about, with the key each surface uses. */
const SIX = [
    { wizard: 'rampupOrder', settings: 'rampupOrder', state: 'rampupOrderEnabled', post: 'rampup_order_enabled' },
    { wizard: 'finaleDouble', settings: 'finaleDouble', state: 'finaleDoubleEnabled', post: 'finale_double_enabled' },
    { wizard: 'finaleTiebreaker', settings: 'finaleTiebreaker', state: 'finaleTiebreakerEnabled', post: 'finale_tiebreaker_enabled' },
    { wizard: 'comebackToken', settings: 'comebackToken', state: 'comebackTokenEnabled', post: 'comeback_token_enabled' },
    { wizard: 'betScaling', settings: 'difficultyBetScaling', state: 'difficultyBetScalingEnabled', post: 'difficulty_bet_scaling_enabled' },
    { wizard: 'sabotage', settings: 'sabotage', state: 'sabotageEnabled', post: 'sabotage_enabled' },
];

describe('#2692 the six modes are reachable from the wizard', () => {
    it.each(SIX)('$wizard is a wizard mode card', ({ wizard }) => {
        expect(WIZARD_SRC).toContain(`key: '${wizard}'`);
    });

    it('the step leads with the play style, not with eleven switches', () => {
        expect(ADMIN_HTML).toContain('id="wiz-play-styles"');
        // The switch list is present but folded — hidden, not removed.
        expect(ADMIN_HTML).toMatch(/id="wiz-modes"[^>]*hidden/);
        expect(ADMIN_HTML).toContain('id="wiz-modes-toggle"');
    });

    it('the fold is a real disclosure, with a state a screen reader can read', () => {
        expect(ADMIN_HTML).toMatch(/id="wiz-modes-toggle"[\s\S]*?aria-expanded="false"/);
        expect(ADMIN_HTML).toMatch(/aria-controls="wiz-modes"/);
    });
});

describe('#2692 a style is a complete statement, not an addition', () => {
    const styleModes = (key) =>
        PLAY_STYLES.find((s) => s.key === key).modes;

    beforeEach(() => {
        // Start every case from a known combination.
        applyPlayStyle('classic');
    });

    it('Chaos → Classic actually turns Sabotage back OFF', () => {
        // The regression this exists for. A style that only *adds* leaves
        // Sabotage running in a game nobody chose it for — a mode that takes
        // turns away from guests, with no visible cause.
        applyPlayStyle('chaos');
        expect(detectPlayStyle()).toBe('chaos');

        applyPlayStyle('classic');

        expect(detectPlayStyle()).toBe('classic');
    });

    it('every mode a style does not name ends up off', () => {
        applyPlayStyle('dramatic');
        const on = detectPlayStyle();
        expect(on).toBe('dramatic');
        // Dramatic does not include Sabotage or bet scaling; if either were
        // left over from a previous style, detectPlayStyle would return null.
        expect(styleModes('dramatic')).not.toContain('sabotage');
        expect(styleModes('dramatic')).not.toContain('betScaling');
    });

    it('leaves Sudden Death alone — it is a rule, not a flavour', () => {
        const fn = WIZARD_SRC.match(/export function applyPlayStyle\([\s\S]*?\n}/);
        expect(fn[0]).toContain("m.key === 'suddenDeath'");
    });

    it('an unknown style key changes nothing', () => {
        applyPlayStyle('dramatic');
        expect(applyPlayStyle('nope')).toBe(false);
        expect(detectPlayStyle()).toBe('dramatic');
    });

    it('Classic really is the quiet one', () => {
        const modes = styleModes('classic');
        expect(modes).not.toContain('sabotage');
        expect(modes).not.toContain('betScaling');
        expect(modes).not.toContain('finaleDouble');
    });

    it('Sabotage appears in exactly one style', () => {
        const withSabotage = PLAY_STYLES
            .filter((s) => s.modes.includes('sabotage'))
            .map((s) => s.key);
        // It is the only mode that actively takes something from a guest. An
        // angry guest the host cannot explain is worse than an unused feature.
        expect(withSabotage).toEqual(['chaos']);
    });

    it('Classic is the default, so no existing game changes silently', () => {
        // Every game since the wizard rewrite ran with all six OFF. Defaulting
        // to Dramatic would change the rules under every existing host without
        // them touching anything.
        expect(WIZARD_SRC).toMatch(/let chosenPlayStyle = 'classic';/);
        for (const { wizard } of SIX) {
            const decl = new RegExp(
                `let chosen${wizard[0].toUpperCase()}${wizard.slice(1)}\\s*=\\s*false`
            );
            expect(WIZARD_SRC, `${wizard} must default off`).toMatch(decl);
        }
    });
});

describe('#2692 the style label is recomputed, never remembered', () => {
    it('detectPlayStyle reads the switches rather than the last click', () => {
        const fn = WIZARD_SRC.match(/export function detectPlayStyle\([\s\S]*?\n}/);
        expect(fn).not.toBeNull();
        expect(fn[0]).toContain('GAME_MODES');
        expect(fn[0]).not.toContain('chosenPlayStyle');
    });

    it('returns null for a combination no style describes', () => {
        const fn = WIZARD_SRC.match(/export function detectPlayStyle\([\s\S]*?\n}/);
        expect(fn[0]).toContain('return match ? match.key : null');
    });

    it('a hand-flipped switch re-renders the styles', () => {
        // Otherwise the panel keeps claiming "Dramatic" for a game that is not.
        const handler = WIZARD_SRC.match(
            /card\.addEventListener\('click', \(\) => \{[\s\S]*?\n {8}\}\);/
        );
        expect(handler).not.toBeNull();
        expect(handler[0]).toContain('_renderPlayStyles()');
    });
});

describe('#2692 the settings actually reach the server', () => {
    it.each(SIX)('$settings is written by the wizard', ({ settings }) => {
        const persist = WIZARD_SRC.match(/function _persistGameSettings\([\s\S]*?\n}/);
        expect(persist).not.toBeNull();
        expect(persist[0]).toContain(`${settings}:`);
    });

    it.each(SIX)('$settings is read back into adminState', ({ settings, state }) => {
        // This is the step that was missing for two of the six. admin.js posted
        // `difficulty_bet_scaling_enabled` and `sabotage_enabled` from
        // adminState, and nothing ever put a saved value into adminState — so
        // both were lost on every page load, hidden panel or not.
        expect(UTIL_SRC).toContain(`s.${settings}`);
        expect(UTIL_SRC).toContain(`adminState.${state}`);
    });

    it.each(SIX)('$post is posted to the server', ({ post, state }) => {
        expect(ADMIN_SRC).toContain(`${post}: adminState.${state}`);
    });

    it('reopening the wizard shows what the game is set to', () => {
        // Without hydration the wizard renders all six off and writes that back
        // the moment the host taps Continue — turning a visit to the wizard
        // into a silent reset.
        for (const { settings } of SIX) {
            expect(WIZARD_SRC).toContain(`savedSettings.${settings}`);
        }
    });
});

describe('#2692 the new copy exists in every locale', () => {
    const KEYS = [
        'playStyle',
        'setIndividually',
        'switchCount',
        'styleClassic',
        'styleClassicLine',
        'styleDramatic',
        'styleDramaticLine',
        'styleChaos',
        'styleChaosLine',
    ];

    it.each(LOCALES)('%s carries every key', (code) => {
        const step4 = locale(code).wizard.step4;
        for (const k of KEYS) {
            expect(step4?.[k], `wizard.step4.${k} missing in ${code}`).toBeTruthy();
        }
    });

    it.each(LOCALES)('%s keeps the switch-count placeholder', (code) => {
        expect(locale(code).wizard.step4.switchCount).toContain('{count}');
    });

    it.each(LOCALES.filter((c) => c !== 'en'))(
        '%s translated the style lines rather than copying English',
        (code) => {
            const en = locale('en').wizard.step4;
            const other = locale(code).wizard.step4;
            expect(other.styleDramaticLine).not.toBe(en.styleDramaticLine);
            expect(other.styleChaosLine).not.toBe(en.styleChaosLine);
        }
    );

    it('the six mode cards reuse strings that already shipped', () => {
        // No new copy for the modes themselves — the admin.* keys have been in
        // all six locales since the features were built.
        const en = locale('en').admin;
        for (const k of [
            'rampupOrder',
            'finaleDouble',
            'finaleTiebreaker',
            'comebackToken',
            'difficultyBetScaling',
            'sabotage',
        ]) {
            expect(en[k], `admin.${k} missing`).toBeTruthy();
            expect(en[`${k}Hint`], `admin.${k}Hint missing`).toBeTruthy();
        }
    });
});
