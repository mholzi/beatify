/**
 * Beatify Admin — the GitHub star hint under "Start New Game".
 *
 * One quiet line on the host end screen (#admin-end-section only, never the TV
 * or a guest phone): shown from the third finished game on this device, and
 * never again once its ✕ is tapped.
 *
 * Each game counts once. The tally is stored together with the last counted
 * game_id, so re-rendering the same END state (a reload, a reconnect, a repeat
 * broadcast) does not count it again. Any storage failure keeps the hint
 * hidden: a browser that cannot remember the dismissal must not nag.
 */

export const STAR_HINT_GAMES_KEY = 'beatify_finished_games';
export const STAR_HINT_DISMISSED_KEY = 'beatify_star_hint_dismissed';
export const STAR_HINT_MIN_GAMES = 3;

function _defaultStorage() {
    // Reading `localStorage` itself can throw (blocked site data).
    return globalThis.localStorage;
}

/**
 * Count the finished game `gameId` (once) and return whether the hint shows.
 * `storage` defaults to localStorage; tests pass their own.
 */
export function noteFinishedGame(gameId, storage) {
    try {
        const store = storage || _defaultStorage();
        if (!store) return false;
        if (store.getItem(STAR_HINT_DISMISSED_KEY) === '1') return false;
        let saved = null;
        try {
            saved = JSON.parse(store.getItem(STAR_HINT_GAMES_KEY) || 'null');
        } catch {
            saved = null; // corrupt value — start over
        }
        let count = saved && typeof saved.count === 'number' ? saved.count : 0;
        const last = saved && typeof saved.last === 'string' ? saved.last : null;
        if (gameId && gameId !== last) {
            count += 1;
            store.setItem(STAR_HINT_GAMES_KEY, JSON.stringify({ count, last: gameId }));
        }
        return count >= STAR_HINT_MIN_GAMES;
    } catch {
        return false; // storage unavailable — no hint
    }
}

/** Remember the dismissal on this device. Safe when storage throws. */
export function dismissStarHint(storage) {
    try {
        const store = storage || _defaultStorage();
        if (store) store.setItem(STAR_HINT_DISMISSED_KEY, '1');
    } catch {
        /* storage unavailable — hidden for this view only */
    }
}

/** Show or hide #admin-star-hint for the END state `data`. */
export function updateStarHint(data) {
    const hint = typeof document !== 'undefined' ? document.getElementById('admin-star-hint') : null;
    if (!hint) return;
    hint.hidden = !noteFinishedGame(data && data.game_id);
}

/** Wire the ✕ button once at startup. */
export function setupStarHint() {
    const btn = typeof document !== 'undefined' ? document.getElementById('admin-star-hint-dismiss') : null;
    if (!btn) return;
    btn.addEventListener('click', () => {
        const hint = document.getElementById('admin-star-hint');
        if (hint) hint.hidden = true;
        dismissStarHint();
    });
}
