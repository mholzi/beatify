/**
 * Beatify Admin — Smart Playlist Mixer (Issue #1538).
 *
 * Lets the host pick tags (decade / style / region / special — the same
 * taxonomy that drives the playlist filter bar) plus a target song count, then
 * asks the backend (`POST /beatify/api/mix-playlists`) to assemble a
 * de-duplicated transient song set from every catalogue playlist matching the
 * tags. The result is held in `adminState.mixSongs` (never written to disk) and
 * sent inline to start-game via the `mix_songs` payload field.
 *
 * State: reads/writes the shared `adminState` object directly, mirroring the
 * other section modules. Building a mix sets `adminState.mixSongs`; clearing the
 * tag selection (or rebuilding with no matches) resets it to null.
 */

import { adminState } from '../state.js';
import { TAG_CATEGORIES } from '../constants.js';
import { updateStartButtonState, updateSelectionSummary } from './playlists.js';

const utils = window.BeatifyUtils || {};

function t(key, fallback) {
    return (window.BeatifyI18n && window.BeatifyI18n.t && window.BeatifyI18n.t(key)) || fallback;
}

const capitalize = (str) => (str ? str.charAt(0).toUpperCase() + str.slice(1) : str);

/**
 * Collect the currently selected mixer tags from the dropdowns.
 * @returns {string[]}
 */
function getSelectedMixTags() {
    const container = document.getElementById('smart-mixer-tags');
    if (!container) return [];
    return Array.from(container.querySelectorAll('.filter-dropdown'))
        .map((sel) => sel.value)
        .filter((v) => v);
}

/**
 * Render the mixer tag dropdowns from the discovered playlists' tags. Only
 * surfaces tags that actually exist in the catalogue (same approach as the
 * filter bar) so the host can't build an empty mix from a phantom tag.
 * Reveals the mixer panel when at least one tag is available.
 * @param {Array} playlists
 */
export function renderSmartMixer(playlists) {
    const panel = document.getElementById('smart-mixer');
    const tagContainer = document.getElementById('smart-mixer-tags');
    if (!panel || !tagContainer) return;

    const availableTags = new Set();
    (playlists || []).forEach((p) => (p.tags || []).forEach((tag) => availableTags.add(tag)));

    if (availableTags.size === 0) {
        panel.classList.add('hidden');
        return;
    }

    let html = '';
    Object.entries(TAG_CATEGORIES).forEach(([categoryKey, category]) => {
        const categoryTags = category.tags.filter((tag) => availableTags.has(tag));
        if (categoryTags.length === 0) return;
        html += `
            <select class="filter-dropdown" data-mix-category="${categoryKey}">
                <option value="">${utils.escapeHtml(category.label)}</option>
                ${categoryTags
                    .map((tag) => `<option value="${utils.escapeHtml(tag)}">${utils.escapeHtml(capitalize(tag))}</option>`)
                    .join('')}
            </select>
        `;
    });

    tagContainer.innerHTML = html;
    panel.classList.remove('hidden');
}

/**
 * Build the mix: POST the selected tags + count, store the returned songs in
 * adminState.mixSongs, and update the selection summary + start button.
 */
async function buildMix() {
    const btn = document.getElementById('smart-mixer-build');
    const resultEl = document.getElementById('smart-mixer-result');
    const countSel = document.getElementById('smart-mixer-count');

    const tags = getSelectedMixTags();
    const count = parseInt(countSel ? countSel.value : '50', 10) || 50;

    if (btn) btn.disabled = true;
    const originalText = btn ? btn.innerHTML : '';
    if (btn) btn.textContent = t('admin.smartMixerBuilding', 'Building…');

    try {
        const auth = window.BeatifyAuth;
        const response = await auth.fetch('/beatify/api/mix-playlists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags, count }),
        });
        const data = await response.json();

        if (!response.ok) {
            throw new Error((data && data.error) || `HTTP ${response.status}`);
        }

        const songs = data.songs || [];
        if (songs.length === 0) {
            adminState.mixSongs = null;
            if (resultEl) {
                resultEl.textContent = t('admin.smartMixerEmpty', 'No songs matched those tags. Try fewer tags.');
                resultEl.classList.remove('hidden');
            }
        } else {
            adminState.mixSongs = songs;
            // A built mix replaces any ticked playlists.
            adminState.selectedPlaylists = [];
            if (resultEl) {
                const tmpl = t('admin.smartMixerResult', '{count} songs ready (transient mix — not saved)');
                resultEl.textContent = tmpl.replace('{count}', songs.length);
                resultEl.classList.remove('hidden');
            }
        }
    } catch (err) {
        adminState.mixSongs = null;
        if (resultEl) {
            resultEl.textContent = t('admin.smartMixerError', 'Could not build mix.') + ' ' + (err.message || '');
            resultEl.classList.remove('hidden');
        }
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
        updateSelectionSummary();
        updateStartButtonState();
    }
}

/**
 * Reset any built mix. Called when the host ticks a real playlist so the two
 * selection modes can't silently fight each other.
 */
export function clearMix() {
    if (!adminState.mixSongs) return;
    adminState.mixSongs = null;
    const resultEl = document.getElementById('smart-mixer-result');
    if (resultEl) resultEl.classList.add('hidden');
    const tagContainer = document.getElementById('smart-mixer-tags');
    if (tagContainer) {
        tagContainer.querySelectorAll('.filter-dropdown').forEach((sel) => { sel.value = ''; });
    }
}

/** Wire the build button once at init. */
export function initSmartMixer() {
    const btn = document.getElementById('smart-mixer-build');
    if (btn && !btn.dataset.bound) {
        btn.dataset.bound = '1';
        btn.addEventListener('click', buildMix);
    }
}
