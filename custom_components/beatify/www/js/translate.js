/**
 * Shared translation helper (#3582).
 *
 * One `tr(key, fallback, params)` for every ES-module caller. Before this file
 * the same lookup existed in nine places with three different signatures, and
 * every new language or fallback rule had to be applied in each copy.
 *
 * Lookup order:
 *   1. `window.BeatifyI18n.t(key, params)` when i18n is loaded. It interpolates
 *      `{placeholder}` slots itself and returns the KEY for a missing
 *      translation (never a falsy value), so a result equal to the key counts as
 *      "not found" (#1402-B8). The current language falls back to English inside
 *      BeatifyI18n.t.
 *   2. The caller's `fallback` string, with `params` interpolated locally so a
 *      host or guest who hits the fallback never reads a literal "{count}".
 *
 * `BeatifyI18n` missing but `BeatifyUtils.t` present: that is asked instead (same
 * contract), then step 2. i18n not loaded at all goes straight to step 2.
 *
 * @param {string} key
 * @param {string} [fallback] - English text used when the key has no translation
 * @param {Object} [params] - `{placeholder}` values
 * @returns {string}
 */
export function tr(key, fallback, params) {
    try {
        var i18n = typeof window !== 'undefined' ? window.BeatifyI18n : null;
        if (i18n && typeof i18n.t === 'function') {
            var v = i18n.t(key, params);
            if (typeof v === 'string' && v && v !== key) return v;
        } else {
            // No BeatifyI18n: the player/admin callers that used to go through
            // BeatifyUtils.t keep that path. When BeatifyI18n exists,
            // BeatifyUtils.t only wraps it, so the branch above already covers it.
            var utils = typeof window !== 'undefined' ? window.BeatifyUtils : null;
            if (utils && typeof utils.t === 'function') {
                var u = utils.t(key, params);
                if (typeof u === 'string' && u && u !== key) return u;
            }
        }
    } catch (e) { /* i18n not ready — use the fallback */ }
    return interpolate(fallback, params);
}

/** Fill `{name}` slots in `text` from `params`; anything else passes through. */
export function interpolate(text, params) {
    if (!params || typeof text !== 'string') return text;
    return Object.keys(params).reduce(
        function (out, name) {
            return out.replace(new RegExp('\\{' + name + '\\}', 'g'), params[name]);
        },
        text,
    );
}
