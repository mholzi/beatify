/**
 * Beatify — the handful of values the browser has to agree with the server on.
 *
 * Every constant in here mirrors `custom_components/beatify/const.py`, and
 * `__tests__/game-constants-mirror.test.js` parses that file and fails when the
 * two drift apart. The rule for the rest of `www/js/`: nobody restates these
 * numbers. admin.js, wizard.js, player-utils.js and the admin setup sections
 * import them from here, and the two chip groups and the two join forms are
 * rendered *from* them rather than typed out next to them.
 *
 * The three bugs this module exists for:
 *
 *  - #2627 the name cap sat in five places (const.py, player-utils.js, two
 *    `name.length > 20` literals in admin.js, two `maxlength="20"` attributes).
 *    Raising it server-side would have left a Join button disabled for names
 *    the server accepts.
 *  - #2626 the auto-advance delays sat in three (game_views.py, wizard.js,
 *    admin.html). A chip the UI showed as selected silently ran the game with
 *    auto-advance off.
 *  - #2625 the difficulty scoring table was written out again as prose in the
 *    wizard and — already drifted — in the admin panel. The hints are now
 *    *composed* from the table, so a tuned band cannot leave a false promise
 *    on screen.
 *
 * Pure data and pure functions: no DOM, no state, no imports. Safe to import at
 * module init from anywhere, including the `node` vitest environment.
 */

/** Mirror of `MAX_NAME_LENGTH` in const.py (enforced by game/player_registry.py). */
export const MAX_NAME_LENGTH = 20;

/**
 * Mirror of `REVEAL_AUTO_ADVANCE_OPTIONS` in const.py: the delays a host can
 * pick at the reveal, in seconds. `0` is "off" — advance manually or when the
 * song ends. Order is display order; index 0 is the default.
 */
export const REVEAL_AUTO_ADVANCE_OPTIONS = [0, 30, 60, 90];

/** Mirror of `POINTS_EXACT` / `POINTS_WRONG` in const.py. */
export const POINTS_EXACT = 10;
export const POINTS_WRONG = 0;

/** Mirror of `DIFFICULTY_DEFAULT` in const.py. */
export const DIFFICULTY_DEFAULT = 'normal';

/**
 * Mirror of `DIFFICULTY_SCORING` in const.py. Snake_case keys on purpose — they
 * are the Python dict's keys, and keeping the spelling identical is what lets
 * the mirror test compare the two structures instead of a hand-written mapping.
 */
export const DIFFICULTY_SCORING = {
    easy: { close_range: 7, close_points: 5, near_range: 10, near_points: 1 },
    normal: { close_range: 3, close_points: 5, near_range: 5, near_points: 1 },
    hard: { close_range: 2, close_points: 3, near_range: 0, near_points: 0 },
};

/**
 * Coerce a stored or user-supplied auto-advance value to one the server accepts.
 *
 * Returns 0 ("off") for anything not in the list — the same fallback
 * `server/game_views.py` applies, so the client can never send a value that
 * arrives as a different setting than the one on screen (#2626).
 *
 * @param {unknown} value - candidate delay in seconds
 * @returns {number} one of REVEAL_AUTO_ADVANCE_OPTIONS
 */
export function normalizeRevealAutoAdvance(value) {
    const n = parseInt(value, 10);
    return REVEAL_AUTO_ADVANCE_OPTIONS.indexOf(n) === -1 ? 0 : n;
}

/**
 * i18n key holding the visible label for one auto-advance chip.
 *
 * Only "off" needs translating; the rest are a number plus the SI symbol for
 * seconds and read the same in every locale the app ships. Written as a literal
 * key (not `'admin.' + x`) so `tests/unit/test_i18n_keys_exist_2507.py` can see
 * it without a DYNAMIC_PREFIXES entry.
 *
 * @param {number} seconds - one of REVEAL_AUTO_ADVANCE_OPTIONS
 * @returns {{ key: string|null, fallback: string }} `key` null ⇒ use fallback verbatim
 */
export function autoAdvanceChipLabel(seconds) {
    return seconds > 0
        ? { key: null, fallback: `${seconds}s` }
        : { key: 'admin.revealAdvanceOff', fallback: 'Off' };
}

/**
 * i18n key + English fallback for the three difficulty names, so the host's
 * status line can name the chosen level in their own language (#2620). Literal
 * keys, for the same reason as above.
 */
export const DIFFICULTY_LABELS = {
    easy: { key: 'admin.easy', fallback: 'Easy' },
    normal: { key: 'admin.normal', fallback: 'Normal' },
    hard: { key: 'admin.hard', fallback: 'Hard' },
};

/**
 * The per-level wrapper around the band clause — the flavour word and the
 * punctuation, which is all a translator should have to touch. `{bands}` is
 * filled in by `difficultyHint` below; no number ever appears in these strings.
 */
export const DIFFICULTY_HINT_SHELLS = {
    easy: { key: 'wizard.step4.difficultyHintEasy', fallback: 'Forgiving: {bands}.' },
    normal: { key: 'wizard.step4.difficultyHintNormal', fallback: 'Balanced: {bands}.' },
    hard: { key: 'wizard.step4.difficultyHintHard', fallback: 'Sharp: {bands}.' },
};

/**
 * The scoring sentence for one difficulty, assembled from DIFFICULTY_SCORING.
 *
 * Two layers, because a difficulty either has a "near" band or it does not, and
 * that is a property of the table rather than of the sentence: `hard` currently
 * has `near_range: 0`, so its band clause ends "…, otherwise 0". Giving `hard` a
 * near band in const.py therefore changes the text by itself — which is exactly
 * what did NOT happen before #2625, when the admin panel kept promising "only
 * close guesses score" long after the wizard had learned to say "3 pts within
 * ±2 years".
 *
 * @param {string} level - 'easy' | 'normal' | 'hard'; anything else reads as the default
 * @param {(key: string, fallback: string, params?: Object) => string} t
 *   a `_t`-style lookup: key, English fallback, `{placeholder}` params.
 * @returns {string} the finished sentence in the active locale
 */
export function difficultyHint(level, t) {
    const key = DIFFICULTY_SCORING[level] ? level : DIFFICULTY_DEFAULT;
    const scoring = DIFFICULTY_SCORING[key];
    const params = {
        exact: POINTS_EXACT,
        close: scoring.close_points,
        closeRange: scoring.close_range,
        near: scoring.near_points,
        nearRange: scoring.near_range,
    };
    const bands = (scoring.near_range > 0 && scoring.near_points > 0)
        ? t(
            'wizard.step4.difficultyBands',
            '{exact} pts for an exact year, {close} pts within ±{closeRange} years, {near} pt within ±{nearRange} years',
            params,
        )
        : t(
            'wizard.step4.difficultyBandsNoNear',
            '{exact} pts for an exact year, {close} pts within ±{closeRange} years, otherwise 0',
            params,
        );
    const shell = DIFFICULTY_HINT_SHELLS[key];
    return t(shell.key, shell.fallback, { bands });
}
