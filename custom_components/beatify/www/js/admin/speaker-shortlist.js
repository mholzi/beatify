/**
 * Beatify — the short speaker list in the wizard's Step 1 (#3537).
 *
 * The server marks each speaker in `/api/status` with `shortlisted`,
 * `duplicate_of` and `visibility_override` (services/speaker_shortlist.py).
 * Step 1 shows the short list on its own, the rest behind a collapsed
 * "Show N more speakers" row, and a "Choose which speakers show here" view
 * stores the admin's own choice server-side.
 *
 * Pure functions only (no DOM, no fetch), so vitest covers them directly.
 * wizard.js owns the rendering into the page and the save request.
 */

const escapeAttr = (s) => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escapeText = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * Split the speakers into the short list and the rest.
 *
 * A speaker without a `shortlisted` field (an older server) is shown. The
 * selected speaker is always on the short list, even when the server's rule
 * or the admin's choice would leave it off.
 *
 * @param {Array} speakers - status `media_players` without the browser targets
 * @param {string|null} selectedId - the chosen speaker
 * @returns {{short: Array, more: Array}}
 */
export function splitSpeakers(speakers, selectedId) {
    const short = [];
    const more = [];
    for (const p of speakers || []) {
        if (p.shortlisted !== false || (selectedId && p.entity_id === selectedId)) short.push(p);
        else more.push(p);
    }
    return { short, more };
}

/**
 * Whether the manage view starts a speaker as switched on: the admin's own
 * choice if there is one, else the automatic rule (duplicates off).
 * @param {Object} player
 * @returns {boolean}
 */
export function defaultVisible(player) {
    if (player.visibility_override === 'shown') return true;
    if (player.visibility_override === 'hidden') return false;
    return !player.duplicate_of;
}

/**
 * The override lists to store for the manage view's switches.
 *
 * Only speakers that differ from the automatic rule are stored, so a speaker
 * added later still follows the rule. A stored choice for a speaker that is
 * not in the list right now (switched off, renamed) is kept as it was.
 *
 * @param {Array} speakers - the speakers the manage view showed
 * @param {Object<string, boolean>} draft - entity_id → switched on
 * @param {{shown?: string[], hidden?: string[]}} [previous] - stored choice
 * @returns {{shown: string[], hidden: string[]}}
 */
export function buildOverrides(speakers, draft, previous = {}) {
    const listed = new Set((speakers || []).map((p) => p.entity_id));
    const shown = (previous.shown || []).filter((id) => !listed.has(id));
    const hidden = (previous.hidden || []).filter((id) => !listed.has(id));
    for (const p of speakers || []) {
        const on = Object.prototype.hasOwnProperty.call(draft, p.entity_id)
            ? !!draft[p.entity_id]
            : defaultVisible(p);
        const auto = !p.duplicate_of;
        if (on === auto) continue;
        (on ? shown : hidden).push(p.entity_id);
    }
    return { shown, hidden };
}

/**
 * The speakers grouped by integration for the manage view, Music Assistant
 * first, then by name.
 * @param {Array} speakers
 * @returns {Array<{platform: string, players: Array}>}
 */
export function groupByPlatform(speakers) {
    const groups = new Map();
    for (const p of speakers || []) {
        const key = p.platform || 'unknown';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(p);
    }
    const rank = (k) => (k === 'music_assistant' ? 0 : 1);
    return [...groups.entries()]
        .sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))
        .map(([platform, players]) => ({ platform, players }));
}

const CHEVRON = '<svg class="wiz-more-chevron" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';

/**
 * The "Show N more speakers" row (collapsed) or "Show fewer speakers"
 * (expanded). '' when nothing is hidden.
 * @param {number} count
 * @param {boolean} expanded
 * @param {(key: string, fallback: string, params?: object) => string} t
 * @returns {string}
 */
export function moreRowHtml(count, expanded, t) {
    if (!count) return '';
    const title = expanded
        ? t('wizard.step1.moreHide', 'Show fewer speakers')
        : (count === 1
            ? t('wizard.step1.moreShowOne', 'Show 1 more speaker')
            : t('wizard.step1.moreShowMany', 'Show {count} more speakers', { count }));
    const sub = t('wizard.step1.moreSub', 'Duplicates and speakers you hid');
    return `<button type="button" class="wiz-more-row${expanded ? ' is-expanded' : ''}" data-wiz-more aria-expanded="${expanded ? 'true' : 'false'}" aria-controls="wiz-speaker-more">
          <span class="wiz-row-text">
            <span class="wiz-row-name">${escapeText(title)}</span>
            <span class="wiz-row-sub">${escapeText(sub)}</span>
          </span>
          ${CHEVRON}
        </button>`;
}

/**
 * The "Choose which speakers show here" button and the note under it.
 * @param {(key: string, fallback: string) => string} t
 * @returns {string}
 */
export function manageEntryHtml(t) {
    return `<button type="button" class="btn btn-ghost wiz-manage-btn" data-wiz-manage>${escapeText(t('wizard.step1.manage', 'Choose which speakers show here'))}</button>
        <p class="wiz-group-note wiz-shortlist-note">${escapeText(t('wizard.step1.shortNote', 'Beatify suggests a short list on its own: one entry per room, Music Assistant first.'))}</p>`;
}

/**
 * The manage view: one switch per speaker, grouped by integration, duplicates
 * marked, with Save and Cancel.
 * @param {Array} speakers
 * @param {Object<string, boolean>} draft - entity_id → switched on
 * @param {{t: Function, platformLabel: (p: string) => string, error?: string, saving?: boolean}} opts
 * @returns {string}
 */
export function manageViewHtml(speakers, draft, opts) {
    const { t, platformLabel } = opts;
    const byId = new Map((speakers || []).map((p) => [p.entity_id, p]));
    const isOn = (p) => (Object.prototype.hasOwnProperty.call(draft, p.entity_id)
        ? !!draft[p.entity_id] : defaultVisible(p));
    const shownCount = (speakers || []).filter(isOn).length;
    const groups = groupByPlatform(speakers).map(({ platform, players }) => {
        const dupes = players.filter((p) => p.duplicate_of).length;
        const chip = dupes
            ? ` <span class="wiz-dup-chip">${escapeText(dupes === 1
                ? t('wizard.step1.duplicatesOne', '1 duplicate')
                : t('wizard.step1.duplicatesMany', '{count} duplicates', { count: dupes }))}</span>`
            : '';
        const rows = players.map((p) => {
            const on = isOn(p);
            const name = p.friendly_name || p.entity_id;
            const twin = p.duplicate_of ? byId.get(p.duplicate_of) : null;
            const sub = twin
                ? t('wizard.step1.duplicateOf', 'Duplicate of {name}', { name: twin.friendly_name || twin.entity_id })
                : p.entity_id;
            return `<button type="button" class="wiz-vis-row${on ? ' is-on' : ''}" role="switch" aria-checked="${on ? 'true' : 'false'}" data-vis-id="${escapeAttr(p.entity_id)}">
          <span class="wiz-row-text">
            <span class="wiz-row-name">${escapeText(name)}</span>
            <span class="wiz-row-sub">${escapeText(sub)}</span>
          </span>
          <span class="wiz-vis-switch" aria-hidden="true"></span>
        </button>`;
        }).join('');
        return `<div class="wiz-group-label wiz-vis-group">${escapeText(platformLabel(platform) || platform)}${chip}</div>${rows}`;
    }).join('');
    const error = opts.error
        ? `<p class="wiz-vis-error" role="alert">${escapeText(opts.error)}</p>`
        : '';
    const save = shownCount === 1
        ? t('wizard.step1.saveOne', 'Save · 1 speaker shown')
        : t('wizard.step1.saveMany', 'Save · {count} speakers shown', { count: shownCount });
    return `<div class="wiz-vis" id="wiz-speaker-manage">
        <div class="wiz-vis-head">
          <h3 class="wiz-vis-title">${escapeText(t('wizard.step1.manageTitle', 'Speakers in Step 1'))}</h3>
          <p class="wiz-sub">${escapeText(t('wizard.step1.manageSub', 'Speakers switched on show up first. The others stay under "Show more".'))}</p>
        </div>
        ${groups}
        ${error}
        <div class="wiz-vis-actions">
          <button type="button" class="btn btn-primary wiz-vis-save" data-vis-save${opts.saving ? ' disabled' : ''}>${escapeText(save)}</button>
          <button type="button" class="btn btn-ghost wiz-vis-cancel" data-vis-cancel>${escapeText(t('wizard.step1.cancel', 'Cancel'))}</button>
        </div>
      </div>`;
}
