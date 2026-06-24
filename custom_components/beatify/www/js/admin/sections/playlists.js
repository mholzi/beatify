/**
 * Beatify Admin — Playlists setup-section (#1279 Schritt 4b/6).
 *
 * Extracted from admin.js: the playlist list render + selection + tag-filter
 * cluster, plus the selection-summary / start-button-validation helpers that
 * the playlists and media-players sections share with the start-game core.
 *
 * State: reads/writes the shared `adminState` object (admin/state.js) directly —
 * no DI closures needed (that's the whole point of step 5 centralizing state).
 *
 * Cross-section: this module has NO outgoing calls into media-players.js or
 * game-settings.js, so it sits at the bottom of the import graph. The media-
 * players section imports `updateStartButtonState` from here; game-settings
 * imports `renderPlaylists` from here; admin.js imports the loadStatus-driven
 * renderers + the validation helpers.
 *
 * `clearPlaylistFilters` is referenced from inline `onclick="..."` in the
 * HTML this module generates, so admin.js re-exports it on `window` (the shim
 * lives there alongside the other admin window globals).
 */

import { adminState } from '../state.js';
import { STORAGE_GAME_SETTINGS, TAG_CATEGORIES } from '../constants.js';
import { renderSeasonalSuggestion } from './seasonal-suggestions.js';

// BeatifyUtils is a classic global script loaded before admin.min.js (module,
// deferred), so this is safe at module init. Mirrors the admin.js pattern.
const utils = window.BeatifyUtils || {};

/**
 * Render playlists list with checkboxes for valid playlists
 * @param {Array} playlists
 * @param {string} playlistDir
 * @param {boolean} preserveSelection - If true, preserve valid selections (used when provider changes)
 */
export function renderPlaylists(playlists, playlistDir, preserveSelection = false) {
    const container = document.getElementById('playlists-list');
    // Remove data-i18n and skeleton state when real content renders
    container?.removeAttribute('data-i18n');
    container?.removeAttribute('aria-busy');
    container?.classList.remove('skeleton-list');

    // Store previous selections before reset (for preserveSelection mode)
    const previousSelections = preserveSelection ? [...adminState.selectedPlaylists] : [];

    // Reset selection state
    adminState.selectedPlaylists = [];
    adminState.playlistData = playlists || [];

    // Render filter bar (Issue #70)
    renderPlaylistFilterBar(adminState.playlistData);

    // Filter playlists based on active filters (Issue #70 - Option B)
    // Uses AND logic: playlist must match ALL selected category filters
    let filteredPlaylists = adminState.playlistData;
    if (!adminState.activeFilterTags.includes('all') && adminState.activeFilterTags.length > 0) {
        filteredPlaylists = adminState.playlistData.filter(p => {
            const playlistTags = p.tags || [];
            // Playlist must contain ALL active filter tags (AND logic)
            return adminState.activeFilterTags.every(tag => playlistTags.includes(tag));
        });
    }

    // Check if we have any valid playlists
    const hasValidPlaylists = adminState.playlistData.some(p => p.is_valid);

    if (!adminState.playlistData || adminState.playlistData.length === 0) {
        // AC2: No playlists error with documentation link
        const docsLink = adminState.playlistDocsUrl
            ? `<a href="${utils.escapeHtml(adminState.playlistDocsUrl)}" target="_blank" rel="noopener">How to create playlists</a>`
            : '';
        container.innerHTML = `
            <div class="empty-state">
                <p class="status-error">No playlists found. Add playlist JSON files to:</p>
                <p style="font-size: 14px;"><code>${utils.escapeHtml(playlistDir)}</code></p>
                ${docsLink ? `<p style="margin-top: 12px;">${docsLink}</p>` : ''}
            </div>
        `;
        // Hide start button when no playlists (Story 9.10)
        document.getElementById('start-game')?.classList.add('hidden');
        return;
    }

    // Show message if filter results in no playlists (Issue #70)
    if (filteredPlaylists.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <p>No playlists match the selected filter.</p>
                <button type="button" class="btn btn-secondary" onclick="clearPlaylistFilters()">Clear Filters</button>
            </div>
        `;
        return;
    }

    container.innerHTML = filteredPlaylists.map(playlist => {
        if (playlist.is_valid) {
            // AC1: Valid playlists with checkbox
            const songCount = playlist.song_count || 0;
            const spotifyCount = playlist.spotify_count || 0;
            const appleMusicCount = playlist.apple_music_count || 0;
            const youtubeMusicCount = playlist.youtube_music_count || 0;
            const tidalCount = playlist.tidal_count || 0;
            const deezerCount = playlist.deezer_count || 0;
            // Amazon Music uses Alexa text search — all songs are playable.
            const amazonMusicCount = playlist.amazon_music_count || songCount;

            // Get provider count based on selected provider
            let providerCount = songCount;
            if (adminState.selectedProvider === 'spotify') {
                providerCount = spotifyCount || songCount; // fallback for legacy playlists
            } else if (adminState.selectedProvider === 'apple_music') {
                providerCount = appleMusicCount;
            } else if (adminState.selectedProvider === 'youtube_music') {
                providerCount = youtubeMusicCount;
            } else if (adminState.selectedProvider === 'tidal') {
                providerCount = tidalCount;
            } else if (adminState.selectedProvider === 'deezer') {
                providerCount = deezerCount;
            } else if (adminState.selectedProvider === 'amazon_music') {
                providerCount = amazonMusicCount;
            }

            // Disable playlist if no songs for selected provider
            const isDisabled = providerCount === 0;
            const disabledClass = isDisabled ? 'is-disabled' : '';
            const disabledAttr = isDisabled ? 'disabled' : '';

            // Build coverage indicator
            let coverageHtml = '';
            if (providerCount < songCount) {
                const coverageClass = providerCount === 0
                    ? 'playlist-coverage playlist-coverage--none'
                    : 'playlist-coverage playlist-coverage--warning';
                coverageHtml = `<span class="${coverageClass}">${providerCount}/${songCount}</span>`;
            }

            return `
                <div class="playlist-item list-item ${isDisabled ? '' : 'is-selectable'} ${disabledClass}"
                     data-provider-count="${providerCount}"
                     data-tags="${utils.escapeHtml((playlist.tags || []).join(','))}">
                    <label class="checkbox-label">
                        <input type="checkbox"
                               class="playlist-checkbox"
                               data-path="${utils.escapeHtml(playlist.path)}"
                               data-song-count="${utils.escapeHtml(String(songCount))}"
                               data-provider-count="${providerCount}"
                               ${disabledAttr}>
                        <span class="playlist-name">${utils.escapeHtml(playlist.name)}</span>
                    </label>
                    <span class="meta">${coverageHtml || utils.escapeHtml(String(songCount))} songs</span>
                </div>
            `;
        } else {
            // Invalid playlists: no checkbox, greyed out
            const errorMsg = (playlist.errors && playlist.errors[0]) || 'Unknown error';
            return `
                <div class="list-item is-invalid">
                    <span class="name">${utils.escapeHtml(playlist.name)}</span>
                    <span class="meta">Invalid: ${utils.escapeHtml(errorMsg)}</span>
                </div>
            `;
        }
    }).join('');

    // Attach event listeners to checkboxes (instead of inline handlers)
    container.querySelectorAll('.playlist-checkbox').forEach(checkbox => {
        checkbox.addEventListener('change', function() {
            handlePlaylistToggle(this);
        });
    });

    // Make entire row clickable (for hidden input UX)
    container.querySelectorAll('.playlist-item.is-selectable').forEach(item => {
        item.addEventListener('click', function(e) {
            // Don't double-trigger if clicking on the checkbox or label
            if (e.target.classList.contains('playlist-checkbox') || e.target.closest('.checkbox-label')) return;
            const checkbox = item.querySelector('.playlist-checkbox');
            if (checkbox) {
                checkbox.checked = !checkbox.checked;
                handlePlaylistToggle(checkbox);
            }
        });
    });

    // Restore valid selections when preserving (provider change)
    if (preserveSelection && previousSelections.length > 0) {
        previousSelections.forEach(prev => {
            const checkbox = container.querySelector(`.playlist-checkbox[data-path="${CSS.escape(prev.path)}"]`);
            if (checkbox && !checkbox.disabled) {
                checkbox.checked = true;
                const providerCount = parseInt(checkbox.dataset.providerCount, 10) || 0;
                const item = checkbox.closest('.playlist-item');
                if (providerCount > 0) {
                    adminState.selectedPlaylists.push({ path: prev.path, songCount: providerCount });
                    item?.classList.add('is-selected');
                }
            }
        });
    }

    // Show start button if we have valid playlists (Story 9.10)
    if (hasValidPlaylists) {
        document.getElementById('start-game')?.classList.remove('hidden');
    } else {
        document.getElementById('start-game')?.classList.add('hidden');
    }

    // Restore previously saved playlist selections from localStorage (mirrors the
    // last-player auto-restore in renderMediaPlayers). Without this, the wizard's
    // selections get wiped every time loadStatus() re-renders the playlist list.
    if (adminState.selectedPlaylists.length === 0) {
        try {
            const raw = localStorage.getItem(STORAGE_GAME_SETTINGS);
            const saved = raw ? JSON.parse(raw) : null;
            const savedPaths = Array.isArray(saved?.selectedPlaylists)
                ? saved.selectedPlaylists.map((p) => (typeof p === 'string' ? p : p.path)).filter(Boolean)
                : [];
            savedPaths.forEach((path) => {
                const checkbox = container.querySelector(`.playlist-checkbox[data-path="${CSS.escape(path)}"]`);
                if (checkbox && !checkbox.disabled) {
                    checkbox.checked = true;
                    const providerCount = parseInt(checkbox.dataset.providerCount, 10) || 0;
                    if (providerCount > 0 && !adminState.selectedPlaylists.some((p) => p.path === path)) {
                        adminState.selectedPlaylists.push({ path, songCount: providerCount });
                        checkbox.closest('.playlist-item')?.classList.add('is-selected');
                    }
                }
            });
        } catch (e) { console.warn('[Beatify] restore saved playlists failed:', e); }
    }

    // Initialize summary as hidden
    updateSelectionSummary();
    updateStartButtonState();

    // #1539: surface a seasonal playlist suggestion once the checkboxes exist in
    // the DOM (the banner's "Add" action targets the matching checkbox).
    renderSeasonalSuggestion();
}

/**
 * Handle playlist checkbox toggle
 * @param {HTMLInputElement} checkbox
 */
export function handlePlaylistToggle(checkbox) {
    const path = checkbox.dataset.path;
    // Use provider-specific count for selection tracking
    const providerCount = parseInt(checkbox.dataset.providerCount, 10) || 0;
    const item = checkbox.closest('.playlist-item');

    if (checkbox.checked) {
        // Prevent duplicate selections
        if (!adminState.selectedPlaylists.some(p => p.path === path)) {
            adminState.selectedPlaylists.push({ path, songCount: providerCount });
        }
        item.classList.add('is-selected');
    } else {
        adminState.selectedPlaylists = adminState.selectedPlaylists.filter(p => p.path !== path);
        item.classList.remove('is-selected');
    }

    updateSelectionSummary();
    updateStartButtonState();
}

/**
 * Render the playlist filter bar with tag dropdowns (Issue #70).
 * Active filter state per category lives in adminState.activeFilters (step 5).
 * @param {Array} playlists
 */
export function renderPlaylistFilterBar(playlists) {
    const filterBar = document.getElementById('playlist-filter-bar');
    if (!filterBar) return;

    // Extract unique tags from all playlists
    const availableTags = new Set();
    playlists.forEach(p => {
        (p.tags || []).forEach(tag => availableTags.add(tag));
    });

    // If no tags found, hide filter bar
    if (availableTags.size === 0) {
        filterBar.classList.add('hidden');
        return;
    }

    // Capitalize first letter helper
    const capitalize = (str) => str.charAt(0).toUpperCase() + str.slice(1);

    // Build dropdown HTML for each category
    let html = '<div class="filter-dropdowns">';

    Object.entries(TAG_CATEGORIES).forEach(([categoryKey, category]) => {
        // Filter to only tags that exist in playlists
        const categoryTags = category.tags.filter(tag => availableTags.has(tag));

        if (categoryTags.length === 0) return;

        const currentValue = adminState.activeFilters[categoryKey] || '';

        html += `
            <select class="filter-dropdown" data-category="${categoryKey}">
                <option value="">${category.label}</option>
                ${categoryTags.map(tag => {
                    const selected = currentValue === tag ? 'selected' : '';
                    return `<option value="${utils.escapeHtml(tag)}" ${selected}>${capitalize(tag)}</option>`;
                }).join('')}
            </select>
        `;
    });

    html += '</div>';

    // Show active filters summary
    const activeFiltersList = Object.entries(adminState.activeFilters)
        .filter(([_, value]) => value)
        .map(([_, value]) => capitalize(value));

    if (activeFiltersList.length > 0) {
        html += `
            <div class="filter-summary">
                <span class="filter-summary-text">Showing: ${activeFiltersList.join(' • ')}</span>
                <button type="button" class="filter-clear" onclick="clearPlaylistFilters()">Clear</button>
            </div>
        `;
    }

    filterBar.innerHTML = html;
    filterBar.classList.remove('hidden');

    // Attach event listeners to dropdowns
    filterBar.querySelectorAll('.filter-dropdown').forEach(select => {
        select.addEventListener('change', function() {
            handleFilterDropdownChange(this.dataset.category, this.value);
        });
    });
}

/**
 * Handle filter dropdown change (Issue #70 - Option B)
 * @param {string} category - The filter category (decade, style, region, special)
 * @param {string} value - The selected tag value
 */
export function handleFilterDropdownChange(category, value) {
    adminState.activeFilters[category] = value;

    // Update adminState.activeFilterTags for compatibility with existing filter logic
    updateActiveFilterTags();

    // Re-render playlists with new filter
    renderPlaylists(adminState.playlistData, '', true);
}

/**
 * Update adminState.activeFilterTags array from adminState.activeFilters object
 */
export function updateActiveFilterTags() {
    const selectedTags = Object.values(adminState.activeFilters).filter(v => v);
    adminState.activeFilterTags = selectedTags.length > 0 ? selectedTags : ['all'];
}

/**
 * Clear all playlist filters (Issue #70)
 */
export function clearPlaylistFilters() {
    adminState.activeFilters = {
        decade: '',
        style: '',
        region: '',
        special: ''
    };
    adminState.activeFilterTags = ['all'];
    renderPlaylists(adminState.playlistData, '', true);
}

/**
 * Calculate total songs from selected playlists
 * @returns {number}
 */
export function calculateTotalSongs() {
    return adminState.selectedPlaylists.reduce((sum, p) => sum + p.songCount, 0);
}

/**
 * Update the selection summary display
 */
export function updateSelectionSummary() {
    const summary = document.getElementById('playlist-summary');
    const selectedCount = document.getElementById('selected-count');
    const totalSongs = document.getElementById('total-songs');

    // Null check for DOM elements
    if (!summary || !selectedCount || !totalSongs) {
        return;
    }

    if (adminState.selectedPlaylists.length === 0) {
        summary.classList.add('hidden');
    } else {
        summary.classList.remove('hidden');
        selectedCount.textContent = adminState.selectedPlaylists.length;
        totalSongs.textContent = calculateTotalSongs();
    }
}

/**
 * Update start button enabled/disabled state and validation messages.
 * Checks for both playlist AND media player selection. Shared with the
 * media-players section and the start-game core (admin.js).
 */
export function updateStartButtonState() {
    const btn = document.getElementById('start-game');
    const playlistMsg = document.getElementById('playlist-validation-msg');
    const mediaPlayerMsg = document.getElementById('media-player-validation-msg');

    if (!btn) {
        return;
    }

    const noPlaylist = adminState.selectedPlaylists.length === 0;
    const noMediaPlayer = adminState.selectedMediaPlayer === null;

    // Disable button if either selection is missing
    btn.disabled = noPlaylist || noMediaPlayer;

    // Show/hide playlist validation message
    if (playlistMsg) {
        playlistMsg.classList.toggle('hidden', !noPlaylist);
    }

    // Show/hide media player validation message
    if (mediaPlayerMsg) {
        mediaPlayerMsg.classList.toggle('hidden', !noMediaPlayer);
    }
}
