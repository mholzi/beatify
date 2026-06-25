/**
 * Beatify Admin — Seasonal playlist suggestion chip (#1539, design option 2).
 *
 * In-product counterpart to the BeatifyBot `seasonal-playlists` chat job: when
 * `now` falls inside an occasion's date window AND the matching bundled playlist
 * is present in the rendered list AND the host hasn't dismissed it this season,
 * we surface a highlighted "suggestion of the season" chip as the FIRST element
 * of the playlist list (see renderPlaylists in ./playlists.js). One tap on
 * "Add" selects the playlist via the existing checkbox/toggle path; the "×"
 * dismisses the occasion for the rest of the season (localStorage flag).
 *
 * Scope is deliberately tiny: an occasion → playlist-filename calendar plus the
 * chip render/wire. No new selection mechanism — it reuses the playlist
 * checkbox and handlePlaylistToggle so selection state stays single-sourced.
 *
 * Matching is by `filename` (e.g. "koelner-karneval.json"), the stable field
 * the server attaches to every playlist entry (game/playlist.py), NOT the
 * absolute `path` which differs per install.
 */

import { adminState } from '../state.js';
import { tr } from '../util.js';

const utils = () => window.BeatifyUtils || {};

/**
 * Occasion calendar — date window → bundled playlist filename.
 *
 * THIS TABLE IS THE ONLY EDIT POINT for seasonal suggestions (#1585): to add a
 * new occasion, append one entry here plus matching `admin.seasonalReason<Id>`
 * keys in every `www/i18n/*.json` locale — no render/wiring code changes. All
 * chrome labels (badge / add / dismiss) are localized separately and shared
 * across every occasion.
 *
 * Only occasions whose playlist actually ships are listed; if a filename isn't
 * present in the rendered list at runtime the occasion silently does nothing,
 * so this stays safe even if a playlist is later renamed/removed.
 *
 * `start`/`end` are inclusive "MM-DD" bounds. A window where start > end wraps
 * across New Year (e.g. Carnival late-Jan → mid-Feb does not wrap, but the
 * field supports it for future occasions like a Dec→Jan set).
 *
 * `season(date)` returns the season identifier used in the dismiss key so the
 * same occasion can re-suggest in a later year. For wrapping windows the season
 * is anchored to the year the window STARTS in.
 */
export const SEASONAL_OCCASIONS = [
    {
        id: 'carnival',
        filename: 'koelner-karneval.json',
        emoji: '🎭',
        // Window covers the run-up to Weiberfastnacht/Rosenmontag. Carnival's
        // date floats with Easter; this fixed window (late Jan – mid Feb) is a
        // pragmatic approximation that comfortably brackets the typical dates.
        start: '01-20',
        end: '02-20',
        // Short reason shown under the title. `reasonKey` routes through i18n
        // (#1577); `reason` is the English fallback when i18n is unavailable.
        reasonKey: 'admin.seasonalReasonCarnival',
        reason: 'Carnival season is here — Kölsche hits for Weiberfastnacht & Rosenmontag.',
    },
    {
        id: 'eurovision',
        filename: 'eurovision-winners.json',
        emoji: '🎤',
        // ESC grand final is mid-May; surface it for the weeks around it.
        start: '04-25',
        end: '05-20',
        reasonKey: 'admin.seasonalReasonEurovision',
        reason: 'Eurovision time — play the winners from 1956 to today.',
    },
    {
        id: 'worldcup',
        filename: 'world-cup-anthems.json',
        emoji: '⚽',
        // FIFA World Cup 2026 runs mid-June to mid-July.
        start: '06-11',
        end: '07-19',
        reasonKey: 'admin.seasonalReasonWorldCup',
        reason: 'World Cup fever — anthems for every match-day party.',
    },
    {
        id: 'summer',
        filename: 'summer-party-anthems.json',
        emoji: '☀️',
        start: '06-01',
        end: '08-31',
        reasonKey: 'admin.seasonalReasonSummer',
        reason: 'Summer is on — 100 anthems for the garden party.',
    },
];

/** @returns {string} "MM-DD" for the given Date (local time). */
function monthDay(date) {
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${m}-${d}`;
}

/**
 * Is `md` ("MM-DD") inside [start, end] inclusive, with wrap-around support
 * (start > end means the window crosses New Year).
 */
function inWindow(md, start, end) {
    if (start <= end) return md >= start && md <= end;
    return md >= start || md <= end; // wraps across Dec→Jan
}

/** Stable season tag for the dismiss key (anchored to the window's start year). */
function seasonTag(occasion, now) {
    const year = now.getFullYear();
    const md = monthDay(now);
    // For a wrapping window, dates in Jan belong to the PREVIOUS season's start year.
    if (occasion.start > occasion.end && md <= occasion.end) return String(year - 1);
    return String(year);
}

function dismissKey(occasion, now) {
    return `beatify_seasonal_dismissed_${occasion.id}_${seasonTag(occasion, now)}`;
}

function isDismissed(occasion, now) {
    try {
        return localStorage.getItem(dismissKey(occasion, now)) === '1';
    } catch {
        return false; // private mode / blocked storage → just show it
    }
}

function markDismissed(occasion, now) {
    try {
        localStorage.setItem(dismissKey(occasion, now), '1');
    } catch {
        /* storage unavailable — chip is removed from DOM regardless */
    }
}

/**
 * Pick the active occasion for `now` whose playlist is present (and selectable)
 * in the current list and which hasn't been dismissed this season.
 *
 * @param {Array} filteredPlaylists  the list as rendered (post tag-filter)
 * @param {Date} [now]
 * @returns {{occasion: object, playlist: object} | null}
 */
export function pickSeasonalSuggestion(filteredPlaylists, now = new Date()) {
    if (!Array.isArray(filteredPlaylists) || filteredPlaylists.length === 0) return null;
    const md = monthDay(now);
    for (const occasion of SEASONAL_OCCASIONS) {
        if (!inWindow(md, occasion.start, occasion.end)) continue;
        if (isDismissed(occasion, now)) continue;
        const playlist = filteredPlaylists.find(
            (p) => p && p.filename === occasion.filename && p.is_valid,
        );
        if (!playlist) continue;
        // Skip if the host already selected it — nothing to suggest.
        if (adminState.selectedPlaylists.some((s) => s.path === playlist.path)) continue;
        return { occasion, playlist };
    }
    return null;
}

/**
 * Build the chip HTML (returns '' when there's nothing to suggest). Rendered as
 * the first child of #playlists-list, ahead of the normal items.
 */
export function seasonalSuggestionHtml(filteredPlaylists, now = new Date()) {
    const pick = pickSeasonalSuggestion(filteredPlaylists, now);
    if (!pick) return '';
    const { occasion, playlist } = pick;
    const esc = utils().escapeHtml || ((s) => s);
    // All chrome labels route through i18n (#1585); the English literals are the
    // fallback when i18n isn't ready/missing so the chip never shows a raw key.
    const badge = tr('admin.seasonalBadge', 'Suggestion of the season');
    const dismissLabel = tr('admin.seasonalDismiss', 'Dismiss seasonal suggestion');
    const addLabel = tr('admin.seasonalAdd', 'Add');
    return `
        <div class="seasonal-suggestion" data-occasion="${esc(occasion.id)}"
             data-playlist-path="${esc(playlist.path)}">
            <div class="seasonal-suggestion__badge">${esc(occasion.emoji)} ${esc(badge)}</div>
            <button type="button" class="seasonal-suggestion__dismiss"
                    aria-label="${esc(dismissLabel)}">×</button>
            <div class="seasonal-suggestion__title">${esc(playlist.name)}</div>
            <div class="seasonal-suggestion__reason">${esc(tr(occasion.reasonKey, occasion.reason))}</div>
            <button type="button" class="seasonal-suggestion__add btn btn-primary">${esc(addLabel)}</button>
        </div>
    `;
}

/**
 * Wire the chip's Add / Dismiss buttons after the list HTML is in the DOM.
 * Idempotent and a no-op if no chip is present.
 *
 * @param {HTMLElement} container  the #playlists-list element
 * @param {Function} onToggle  handlePlaylistToggle (injected to avoid a cycle)
 * @param {Date} [now]
 */
export function wireSeasonalSuggestion(container, onToggle, now = new Date()) {
    const chip = container?.querySelector('.seasonal-suggestion');
    if (!chip) return;
    const occasionId = chip.dataset.occasion;
    const occasion = SEASONAL_OCCASIONS.find((o) => o.id === occasionId);
    const path = chip.dataset.playlistPath;

    const addBtn = chip.querySelector('.seasonal-suggestion__add');
    addBtn?.addEventListener('click', () => {
        const checkbox = container.querySelector(
            `.playlist-checkbox[data-path="${CSS.escape(path)}"]`,
        );
        if (checkbox && !checkbox.disabled) {
            checkbox.checked = true;
            onToggle(checkbox); // existing selection path — single source of truth
            // Reflect the selection on the matching row, then drop the chip.
            checkbox.closest('.playlist-item')?.classList.add('is-selected');
        }
        chip.remove();
    });

    const dismissBtn = chip.querySelector('.seasonal-suggestion__dismiss');
    dismissBtn?.addEventListener('click', () => {
        if (occasion) markDismissed(occasion, now);
        chip.remove();
    });
}

/**
 * #1570: hub-friendly variant of wireSeasonalSuggestion for the Playlist Hub
 * (playlist-hub.js), which owns its own selection model instead of the flat
 * #playlists-list checkboxes. The flat list is dead UI since rc11/#1138, so the
 * chip never surfaced on the live wizard step-3 picker — the same mount gap the
 * Mix tab hit (#1568/#1569).
 *
 * Identical to wireSeasonalSuggestion except the Add path delegates to the
 * supplied `onAdd(path)` callback (the hub adds the path to its selection and
 * re-renders) rather than toggling a checkbox. The occasion calendar, chip
 * markup and the per-season dismiss logic are shared verbatim with the flat
 * list — only the selection coupling differs.
 *
 * @param {HTMLElement} container  the element holding the rendered chip
 * @param {(path: string) => void} onAdd  hub selection hook
 * @param {Date} [now]
 */
export function wireSeasonalSuggestionHub(container, onAdd, now = new Date()) {
    const chip = container?.querySelector('.seasonal-suggestion');
    if (!chip) return;
    const occasionId = chip.dataset.occasion;
    const occasion = SEASONAL_OCCASIONS.find((o) => o.id === occasionId);
    const path = chip.dataset.playlistPath;

    const addBtn = chip.querySelector('.seasonal-suggestion__add');
    addBtn?.addEventListener('click', () => {
        if (path && typeof onAdd === 'function') onAdd(path); // hub selection API
        chip.remove();
    });

    const dismissBtn = chip.querySelector('.seasonal-suggestion__dismiss');
    dismissBtn?.addEventListener('click', () => {
        if (occasion) markDismissed(occasion, now);
        chip.remove();
    });
}

// #1570: the Playlist Hub (playlist-hub.js) is loaded as a standalone <script
// type="module"> and can't import this bundled module without duplicating
// admin/state.js. Expose the seasonal API on window — the same cross-module
// bridge the Smart Playlist Mixer uses (window.BeatifyMixPanel, #1568/#1569) —
// so the hub can render + wire the chip from its own (filtered) playlist set.
if (typeof window !== 'undefined') {
    window.BeatifySeasonal = {
        pickSeasonalSuggestion,
        seasonalSuggestionHtml,
        wireSeasonalSuggestionHub,
    };
}
