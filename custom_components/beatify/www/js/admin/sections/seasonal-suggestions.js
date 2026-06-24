/**
 * Beatify Admin — Seasonal playlist suggestions (#1539).
 *
 * In-product counterpart to the BeatifyBot `seasonal-playlists` occasion-detection
 * job. Beatify has strongly seasonal content (Carnival, Summer, Eurovision, World
 * Cup, December …) but nothing surfaces the right playlist at the right time. This
 * module renders a small, dismissible suggestion banner on the admin setup screen:
 * when `now` falls in an occasion window AND the matching playlist file exists in
 * the user's library, it offers a one-tap "add to selection" action.
 *
 * Self-contained + unobtrusive:
 *  - Pure presentation. Reuses the existing playlist selection path: tapping the
 *    suggestion just checks the matching checkbox + fires its change handler, so
 *    selection/summary/start-button logic stays in playlists.js (single source).
 *  - Each occasion is suggested at most once per season via a localStorage flag
 *    (keyed by occasion id + season year), and dismissals are remembered too.
 *  - If no occasion is active, or the playlist isn't installed, the banner stays
 *    hidden — no empty chrome.
 *
 * Wiring: playlists.js calls `renderSeasonalSuggestion()` at the end of
 * `renderPlaylists()` (after the checkboxes exist in the DOM).
 */

import { adminState } from '../state.js';

const utils = window.BeatifyUtils || {};

const STORAGE_PREFIX = 'beatify_seasonal_';

/**
 * Occasion calendar: date window → playlist filename(s).
 *
 * Windows are inclusive [start, end] as {m, d} (1-based month). Windows that wrap
 * the year boundary (start month > end month, e.g. Carnival Jan→Mar handled via
 * Feb peak, December→January) are supported via `wraps: true`.
 *
 * `files` is an ordered preference list — the FIRST filename that actually exists
 * in the user's library wins. Filenames must match real playlist JSONs shipped
 * under custom_components/beatify/playlists/ (root or community/). Occasions whose
 * file isn't installed simply never render.
 */
const OCCASIONS = [
    {
        id: 'carnival',
        emoji: '🎭',
        // Karneval season peaks ~Weiberfastnacht→Rosenmontag (mid-Feb), but the
        // "session" runs from 11.11. We surface it through Jan–Feb (the active run-up).
        window: { start: { m: 1, d: 6 }, end: { m: 2, d: 28 } },
        label: 'Carnival is coming',
        sub: 'Get the party started with Cologne Carnival hits.',
        files: ['koelner-karneval.json'],
    },
    {
        id: 'eurovision',
        emoji: '🎤',
        // ESC final is mid-May; surface from late April.
        window: { start: { m: 4, d: 20 }, end: { m: 5, d: 31 } },
        label: 'Eurovision season',
        sub: 'Spin up decades of Eurovision winners.',
        files: ['eurovision-winners.json'],
    },
    {
        id: 'summer',
        emoji: '☀️',
        window: { start: { m: 6, d: 1 }, end: { m: 8, d: 31 } },
        label: 'Summer is here',
        sub: 'Sunshine anthems for the garden party.',
        files: ['sommerklassiker.json', 'summer-party-anthems.json'],
    },
    {
        id: 'worldcup',
        emoji: '⚽',
        // Tournaments cluster in (northern) summer; reuse the broad summer window.
        window: { start: { m: 6, d: 1 }, end: { m: 7, d: 31 } },
        label: 'Tournament fever',
        sub: 'Stadium anthems for match night.',
        files: ['world-cup-anthems.json'],
    },
    {
        id: 'december',
        emoji: '🎄',
        // December festive window, wrapping into early January.
        window: { start: { m: 12, d: 1 }, end: { m: 1, d: 6 }, wraps: true },
        label: 'Festive season',
        sub: 'Bring out the holiday playlist.',
        // No Christmas playlist ships today — listed so it lights up automatically
        // once a festive set is added. Until then this occasion never renders.
        files: ['christmas-classics.json', 'weihnachtshits.json', 'holiday-hits.json'],
    },
];

/** Is {m,d} inside an occasion window (inclusive, wrap-aware)? */
function inWindow(now, win) {
    const md = (m, d) => m * 100 + d;
    const cur = md(now.getMonth() + 1, now.getDate());
    const start = md(win.start.m, win.start.d);
    const end = md(win.end.m, win.end.d);
    if (win.wraps) {
        // e.g. Dec 1 → Jan 6: inside if >= start OR <= end.
        return cur >= start || cur <= end;
    }
    return cur >= start && cur <= end;
}

/**
 * Season key for the once-per-season flag. Uses the window's START year so a
 * wrap-around occasion (Dec→Jan) counts the Dec→following-Jan run as one season.
 */
function seasonKey(occasion, now) {
    let year = now.getFullYear();
    if (occasion.window.wraps && now.getMonth() + 1 <= occasion.window.end.m) {
        // We're in the January tail → the season started the previous December.
        year -= 1;
    }
    return `${STORAGE_PREFIX}${occasion.id}_${year}`;
}

function isSeasonDone(occasion, now) {
    try {
        return localStorage.getItem(seasonKey(occasion, now)) !== null;
    } catch {
        return false;
    }
}

function markSeasonDone(occasion, now, how) {
    try {
        localStorage.setItem(seasonKey(occasion, now), how || 'shown');
    } catch {
        /* localStorage unavailable (private mode) — degrade gracefully */
    }
}

/** Find the playlist object whose path ends with one of the occasion's filenames. */
function findInstalledPlaylist(occasion) {
    const playlists = adminState.playlistData || [];
    for (const filename of occasion.files) {
        const match = playlists.find(
            (p) => p && p.is_valid && typeof p.path === 'string' && p.path.endsWith('/' + filename),
        );
        if (match) return match;
    }
    return null;
}

/** Pick the first active occasion that has an installed playlist and isn't done. */
function pickSuggestion(now) {
    for (const occasion of OCCASIONS) {
        if (!inWindow(now, occasion.window)) continue;
        if (isSeasonDone(occasion, now)) continue;
        const playlist = findInstalledPlaylist(occasion);
        if (playlist) return { occasion, playlist };
    }
    return null;
}

/**
 * Render (or hide) the seasonal suggestion banner. Idempotent — safe to call on
 * every renderPlaylists(). Injected after the playlist checkboxes exist so the
 * "add" action can target the right checkbox.
 *
 * @param {Date} [nowOverride] - injectable clock for tests.
 */
export function renderSeasonalSuggestion(nowOverride) {
    const host = document.getElementById('seasonal-suggestion');
    if (!host) return;

    const now = nowOverride instanceof Date ? nowOverride : new Date();
    const picked = pickSuggestion(now);

    if (!picked) {
        host.classList.add('hidden');
        host.innerHTML = '';
        return;
    }

    const { occasion, playlist } = picked;
    const esc = utils.escapeHtml || ((s) => String(s));

    host.innerHTML = `
        <div class="seasonal-banner" role="status">
            <span class="seasonal-banner__emoji" aria-hidden="true">${occasion.emoji}</span>
            <div class="seasonal-banner__text">
                <strong class="seasonal-banner__title">${esc(occasion.label)}</strong>
                <span class="seasonal-banner__sub">${esc(occasion.sub)} ${esc(playlist.name)}</span>
            </div>
            <div class="seasonal-banner__actions">
                <button type="button" class="btn btn-primary seasonal-banner__add">Add playlist</button>
                <button type="button" class="seasonal-banner__dismiss" aria-label="Dismiss suggestion">&times;</button>
            </div>
        </div>
    `;
    host.classList.remove('hidden');

    const addBtn = host.querySelector('.seasonal-banner__add');
    const dismissBtn = host.querySelector('.seasonal-banner__dismiss');

    addBtn?.addEventListener('click', () => {
        const checkbox = document.querySelector(
            `.playlist-checkbox[data-path="${CSS.escape(playlist.path)}"]`,
        );
        if (checkbox && !checkbox.disabled && !checkbox.checked) {
            checkbox.checked = true;
            // Reuse the canonical toggle path so selection/summary/start-button
            // all update exactly as if the host had tapped the checkbox.
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
            // Bring it into view so the host sees what got added.
            checkbox.closest('.playlist-item')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        markSeasonDone(occasion, now, 'added');
        host.classList.add('hidden');
        host.innerHTML = '';
    });

    dismissBtn?.addEventListener('click', () => {
        markSeasonDone(occasion, now, 'dismissed');
        host.classList.add('hidden');
        host.innerHTML = '';
    });
}

// Exposed for tests.
export const __testables = { OCCASIONS, inWindow, seasonKey, pickSuggestion, findInstalledPlaylist };
