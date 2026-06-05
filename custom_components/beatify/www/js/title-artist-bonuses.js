/**
 * Title & Artist mode — bonus-flag precedence (#1180).
 *
 * Title & Artist mode replaces the year round, so the year-only bonuses
 * (artist challenge, movie quiz, intro, closest wins) have nothing to attach
 * to and must be suppressed while TA mode is on.
 *
 * This is a PURE helper: it never mutates the host's stored preferences. The
 * host's real choices stay the source of truth (in the in-memory flags, the
 * checkboxes, and localStorage); suppression is applied only when building the
 * start-game payload. That keeps the save → reload → toggle-off cycle lossless
 * (a host who had Artist Challenge on, enabled TA mode, reloaded, then turned
 * TA mode off gets their Artist Challenge preference back).
 *
 * Loaded as an ES module (exposes window.BeatifyTitleArtist for the classic
 * admin.js script) and imported directly by the vitest suite.
 */

/**
 * The year-round bonus flags suppressed by Title & Artist mode.
 * @type {ReadonlyArray<string>}
 */
export const YEAR_ROUND_BONUS_KEYS = [
    'artist_challenge_enabled',
    'closest_wins_mode',
];

/**
 * Apply Title & Artist mode precedence to a start-game payload's bonus flags.
 *
 * Returns a NEW object: when TA mode is on, every year-round bonus key is
 * forced to false; when off, the host's flags pass through unchanged. The
 * input is never mutated, so the caller's source-of-truth flags survive.
 *
 * @param {Object} flags - Bonus flags keyed by start-game payload field name
 *   (artist_challenge_enabled, movie_quiz_enabled, intro_mode_enabled,
 *   closest_wins_mode). Unknown keys are passed through untouched.
 * @param {boolean} titleArtistMode - Whether Title & Artist mode is on.
 * @returns {Object} A new flags object with year-round bonuses suppressed when
 *   TA mode is on.
 */
export function applyTitleArtistBonusPrecedence(flags, titleArtistMode) {
    const result = { ...flags };
    if (titleArtistMode) {
        for (const key of YEAR_ROUND_BONUS_KEYS) {
            result[key] = false;
        }
    }
    return result;
}

if (typeof window !== 'undefined') {
    window.BeatifyTitleArtist = {
        YEAR_ROUND_BONUS_KEYS,
        applyTitleArtistBonusPrecedence,
    };
}
