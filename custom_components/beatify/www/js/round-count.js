/**
 * Round-count helpers for the setup wizard (Issue #1475).
 *
 * A game used to play every song of every selected playlist. With a 100-song
 * playlist that is a two-hour evening nobody asked for, so the host can now cap
 * the number of rounds. This module holds the pure decisions — which chips to
 * offer, how to clamp a typed number, how long the result runs — so they can be
 * tested without a DOM and stay identical between the wizard UI and any other
 * caller.
 *
 * The wire value is `max_rounds`: a positive integer caps the game, and **0
 * means "play everything"**. 0 is the pre-#1475 behaviour, so it is both the
 * default and the fallback for anything unparseable — a broken setting must
 * never silently shorten someone's game.
 */

/**
 * Fewest rounds a capped game may have.
 *
 * Markus' call: below ten rounds the difficulty ramp-up has nothing to ramp
 * over and one lucky guess decides the winner. Mirrors `MIN_ROUNDS` in
 * `game/playlist.py`; the backend clamps too, so a hand-crafted request can't
 * undercut it either.
 */
export const MIN_ROUNDS = 10;

/** Preset chip values, in display order. */
export const ROUND_PRESETS = [10, 20, 30];

/**
 * Chips to render for a given pool of playable songs.
 *
 * Presets above the pool are dropped rather than shown disabled: offering "30"
 * for a 22-song selection is an offer the game cannot keep. "All" is always
 * present and always last before the custom entry, so the escape hatch back to
 * the old behaviour never moves around.
 *
 * @param {number} available - playable songs across the selected playlists
 * @returns {Array<{id: number|string, kind: string}>}
 */
export function roundCountOptions(available) {
    const pool = Number.isFinite(available) && available > 0 ? Math.floor(available) : 0;
    const presets = ROUND_PRESETS
        .filter((n) => pool === 0 || n < pool)
        .map((n) => ({ id: n, kind: 'preset' }));
    return [...presets, { id: 0, kind: 'all' }, { id: 'custom', kind: 'custom' }];
}

/**
 * Clamp a host-typed round count into something the game can honour.
 *
 * Returns 0 ("all songs") for anything that isn't a positive finite number, so
 * an empty or garbled input lands on the safe default instead of on MIN_ROUNDS
 * — silently starting a 10-round game because a keystroke was lost would be
 * worse than ignoring the field.
 *
 * @param {*} value - raw input (number or string)
 * @param {number} available - playable songs; 0/unknown means "don't cap"
 * @returns {number} 0, or an integer in [MIN_ROUNDS, available]
 */
export function clampRoundCount(value, available) {
    const n = typeof value === 'string' ? parseInt(value, 10) : value;
    if (typeof n !== 'number' || !Number.isFinite(n) || n <= 0) return 0;
    const pool = Number.isFinite(available) && available > 0 ? Math.floor(available) : 0;
    let out = Math.max(Math.floor(n), MIN_ROUNDS);
    if (pool > 0) {
        // A cap at or above the pool is the same game as "all songs" — report
        // it as 0 so the summary and the payload agree with what happens.
        if (out >= pool) return 0;
        out = Math.min(out, pool);
    }
    return out;
}

/**
 * Playable songs across the selected playlists.
 *
 * Uses `song_count` from the status payload, which is the raw catalog size —
 * the provider filter runs server-side at create time, so the real pool can be
 * smaller. That makes this an upper bound, which is why the UI shows it as an
 * estimate and the backend clamps again against the actual song list.
 *
 * @param {Array<string>} selectedPaths
 * @param {Array<Object>} playlists - status payload entries
 * @returns {number}
 */
export function availableSongs(selectedPaths, playlists) {
    if (!Array.isArray(selectedPaths) || !Array.isArray(playlists)) return 0;
    let total = 0;
    for (const path of selectedPaths) {
        const match = playlists.find((p) => p && (p.path || p.filename || p.name) === path);
        const count = match && match.song_count;
        if (typeof count === 'number' && Number.isFinite(count) && count > 0) {
            total += Math.floor(count);
        }
    }
    return total;
}

/**
 * Rough length of a game, in whole minutes.
 *
 * Per round: the guessing timer plus the reveal. The reveal has no fixed
 * length (the host advances, or auto-advance fires), so 20s is a deliberate
 * middle estimate — the hint says "approx." and exists to make "30 rounds" feel
 * like a duration rather than a number.
 *
 * @param {number} rounds - 0 means "all", so pass the pool size instead
 * @param {number} duration - seconds per round
 * @returns {number} minutes, minimum 1
 */
export function estimateGameMinutes(rounds, duration) {
    const r = Number.isFinite(rounds) && rounds > 0 ? Math.floor(rounds) : 0;
    const d = Number.isFinite(duration) && duration > 0 ? duration : 30;
    if (r === 0) return 0;
    return Math.max(1, Math.round((r * (d + 20)) / 60));
}
