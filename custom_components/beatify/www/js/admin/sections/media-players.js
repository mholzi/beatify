/**
 * Beatify Admin — Media-Players setup-section (#1279 Schritt 4b/6).
 *
 * Extracted from admin.js: the media-player list render + radio-selection +
 * platform-capability cluster, plus the provider-option/-warning UI that gates
 * the music-service provider chips based on the selected speaker's capabilities.
 *
 * State: reads/writes the shared `adminState` object (admin/state.js) directly.
 *
 * Cross-section: imports `updateStartButtonState` from playlists.js (the shared
 * start-button validation helper). `updateProviderOptions` toggles the
 * `.chip[data-provider]` buttons that the game-settings section wires up — the
 * music-service "section" has no separate cluster of its own (the live provider
 * UI is the chips owned by game-settings + this capability gate), so it is NOT
 * a standalone module (see PR body).
 *
 * The no-compatible-players empty state renders inline `onclick="loadStatus()"`;
 * `loadStatus` lives in admin.js core and is already shimmed onto `window` there,
 * so this module needs no extra shim for it.
 */

import { adminState } from '../state.js';
import { STORAGE_LAST_PLAYER, PLATFORM_LABELS } from '../constants.js';
import { updateStartButtonState } from './playlists.js';

// BeatifyUtils is a classic global script loaded before admin.min.js (module,
// deferred), so this is safe at module init. Mirrors the admin.js pattern.
const utils = window.BeatifyUtils || {};

/**
 * Update media player summary badge
 * @param {string} playerName - Friendly name of selected player
 */
export function updateMediaPlayerSummary(playerName) {
    const summary = document.getElementById('media-player-summary');
    if (summary) {
        summary.textContent = playerName || 'Select...';
    }
}

/**
 * Render media players list grouped by platform with capability info
 * Filters out unavailable players
 * @param {Array} players
 */
export function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');
    // Remove data-i18n and skeleton state when real content renders
    container?.removeAttribute('data-i18n');
    container?.removeAttribute('aria-busy');
    container?.classList.remove('skeleton-list');
    const totalPlayers = players ? players.length : 0;

    // Reset selection state
    adminState.selectedMediaPlayer = null;

    // Filter out unavailable players
    const availablePlayers = (players || []).filter(p => p.state !== 'unavailable');

    // Hide validation message when showing empty states (avoid redundant messaging)
    const validationMsg = document.getElementById('media-player-validation-msg');

    if (totalPlayers === 0) {
        // No compatible players found - show setup message with MA link
        container.innerHTML = `
            <div class="no-players-message">
                <h3>🎵 No Compatible Players Found</h3>
                <p>Beatify works with Music Assistant, Sonos, and Alexa players.</p>
                <p><strong>Recommended:</strong> Install Music Assistant for the best experience with any speaker.</p>
                <div class="button-group">
                    <a href="https://music-assistant.io/getting-started/"
                       target="_blank" class="btn btn-secondary">
                        📖 Music Assistant Setup Guide
                    </a>
                    <button onclick="loadStatus()" class="btn btn-primary">
                        🔄 Refresh
                    </button>
                </div>
            </div>
        `;
        if (validationMsg) {
            validationMsg.classList.add('hidden');
        }
        // Disable start button when no players
        const startBtn = document.getElementById('start-game');
        if (startBtn) startBtn.disabled = true;
        return;
    }

    if (availablePlayers.length === 0) {
        // Players exist but all unavailable
        const docsLink = adminState.mediaPlayerDocsUrl
            ? `<a href="${utils.escapeHtml(adminState.mediaPlayerDocsUrl)}" target="_blank" rel="noopener">Troubleshooting</a>`
            : '';
        container.innerHTML = `
            <div class="empty-state">
                <p class="status-error">All media players are unavailable. Check your devices are powered on.</p>
                ${docsLink ? `<p style="margin-top: 12px;">${docsLink}</p>` : ''}
            </div>
        `;
        if (validationMsg) {
            validationMsg.classList.add('hidden');
        }
        return;
    }

    // Render all players with platform badges on each item
    container.innerHTML = availablePlayers.map(player => renderPlayerItem(player)).join('');
    attachPlayerSelectionHandlers();

    // Try to auto-select last used player from localStorage
    const lastPlayerId = localStorage.getItem(STORAGE_LAST_PLAYER);
    if (lastPlayerId) {
        // Match the radio input specifically — the wrapper .media-player-item div
        // also carries data-entity-id and appears first in DOM order, so a bare
        // [data-entity-id] selector grabs the div: .checked is a no-op and
        // handleMediaPlayerSelect reads undefined data-state. Mirror admin.js
        // hydrateFromStorage and target .media-player-radio (CSS.escape the id).
        const lastPlayerRadio = container.querySelector(
            `.media-player-radio[data-entity-id="${CSS.escape(lastPlayerId)}"]`
        );
        if (lastPlayerRadio) {
            lastPlayerRadio.checked = true;
            handleMediaPlayerSelect(lastPlayerRadio, true); // true = skip localStorage save
            // Collapse section since we have a valid selection
            const section = document.getElementById('media-players');
            if (section) {
                section.classList.add('collapsed');
                const toggle = document.getElementById('media-players-toggle');
                if (toggle) toggle.setAttribute('aria-expanded', 'false');
            }
        }
    }
}

/**
 * Render a single player item with platform badge and capability data attributes
 * @param {Object} player - Player object from backend
 * @returns {string} HTML string
 */
export function renderPlayerItem(player) {
    const info = PLATFORM_LABELS[player.platform] || { icon: '🔈', label: player.platform };
    const platformBadge = `<span class="platform-badge platform-badge--${utils.escapeHtml(player.platform)}">${info.icon} ${info.label}</span>`;

    return `
        <div class="media-player-item list-item is-selectable"
             data-entity-id="${utils.escapeHtml(player.entity_id)}"
             data-platform="${utils.escapeHtml(player.platform)}"
             data-supports-spotify="${player.supports_spotify}"
             data-supports-apple-music="${player.supports_apple_music}"
             data-supports-youtube-music="${player.supports_youtube_music}"
             data-supports-tidal="${player.supports_tidal}"
             data-supports-deezer="${player.supports_deezer}"
             data-supports-amazon-music="${player.supports_amazon_music}">
            <label class="radio-label">
                <input type="radio"
                       class="media-player-radio"
                       name="media-player"
                       data-entity-id="${utils.escapeHtml(player.entity_id)}"
                       data-state="${utils.escapeHtml(player.state)}"
                       data-platform="${utils.escapeHtml(player.platform)}"
                       data-supports-spotify="${player.supports_spotify}"
                       data-supports-apple-music="${player.supports_apple_music}"
                       data-supports-youtube-music="${player.supports_youtube_music}"
                       data-supports-tidal="${player.supports_tidal}"
                       data-supports-deezer="${player.supports_deezer}"
                       data-supports-amazon-music="${player.supports_amazon_music}">
                <span class="player-info">
                    <span class="player-name">${utils.escapeHtml(player.friendly_name)}</span>
                    ${platformBadge}
                </span>
            </label>
            <span class="meta">
                <span class="state-dot state-${utils.escapeHtml(player.state)}"></span>
                ${utils.escapeHtml(player.state)}
            </span>
        </div>
    `;
}

/**
 * Attach event handlers to player selection elements
 */
export function attachPlayerSelectionHandlers() {
    const container = document.getElementById('media-players-list');
    if (!container) return;

    // Attach event listeners to radio buttons
    container.querySelectorAll('.media-player-radio').forEach(radio => {
        radio.addEventListener('change', function() {
            handleMediaPlayerSelect(this);
        });
    });

    // Make entire row clickable (for hidden input UX)
    container.querySelectorAll('.media-player-item').forEach(item => {
        item.addEventListener('click', function(e) {
            // Don't double-trigger if clicking on the radio or within the label
            if (e.target.classList.contains('media-player-radio') || e.target.closest('.radio-label')) return;
            const radio = item.querySelector('.media-player-radio');
            if (radio && !radio.checked) {
                radio.checked = true;
                handleMediaPlayerSelect(radio);
            }
        });
    });
}

/**
 * Handle media player radio button selection (AC4)
 * Updates provider options based on platform capabilities.
 * @param {HTMLInputElement} radio
 * @param {boolean} skipSave - If true, don't save to localStorage (used for auto-select)
 */
export function handleMediaPlayerSelect(radio, skipSave = false) {
    const entityId = radio.dataset.entityId;
    const state = radio.dataset.state;
    const platform = radio.dataset.platform;
    const supportsSpotify = radio.dataset.supportsSpotify === 'true';
    const supportsAppleMusic = radio.dataset.supportsAppleMusic === 'true';
    const supportsYoutubeMusic = radio.dataset.supportsYoutubeMusic === 'true';
    const supportsTidal = radio.dataset.supportsTidal === 'true';
    const supportsDeezer = radio.dataset.supportsDeezer === 'true';
    const supportsAmazonMusic = radio.dataset.supportsAmazonMusic === 'true';

    // Update module state with platform capabilities
    adminState.selectedMediaPlayer = {
        entityId,
        state,
        platform,
        supportsSpotify,
        supportsAppleMusic,
        supportsYoutubeMusic,
        supportsTidal,
        supportsDeezer,
        supportsAmazonMusic,
    };

    // Update visual selection
    document.querySelectorAll('.media-player-item').forEach(item => {
        item.classList.remove('is-selected');
    });
    const playerItem = radio.closest('.media-player-item');
    playerItem.classList.add('is-selected');

    // Get player name for summary
    const playerName = playerItem.querySelector('.player-name')?.textContent?.trim() || entityId;
    updateMediaPlayerSummary(playerName);

    // Show Music Service section
    const musicServiceSection = document.getElementById('music-service');
    if (musicServiceSection) {
        musicServiceSection.classList.remove('hidden');
    }

    // Update provider options based on platform capabilities
    updateProviderOptions(adminState.selectedMediaPlayer);

    // Update warning message
    updateProviderWarning(adminState.selectedMediaPlayer);

    // Save to localStorage
    if (!skipSave) {
        try {
            localStorage.setItem(STORAGE_LAST_PLAYER, entityId);
        } catch (e) {
            console.warn('Failed to save last player:', e);
        }
    }

    updateStartButtonState();
}

/**
 * Update provider button states based on selected player capabilities
 * @param {Object} player - Selected player with capability flags
 */
export function updateProviderOptions(player) {
    const spotifyBtn = document.querySelector('.chip[data-provider="spotify"]');
    const appleBtn = document.querySelector('.chip[data-provider="apple_music"]');
    const youtubeBtn = document.querySelector('.chip[data-provider="youtube_music"]');
    const tidalBtn = document.querySelector('.chip[data-provider="tidal"]');
    const deezerBtn = document.querySelector('.chip[data-provider="deezer"]');
    const amazonBtn = document.querySelector('.chip[data-provider="amazon_music"]');

    if (spotifyBtn) {
        spotifyBtn.disabled = !player.supportsSpotify;
        spotifyBtn.classList.toggle('chip--disabled', !player.supportsSpotify);
    }

    if (appleBtn) {
        appleBtn.disabled = !player.supportsAppleMusic;
        appleBtn.classList.toggle('chip--disabled', !player.supportsAppleMusic);
    }

    if (youtubeBtn) {
        youtubeBtn.disabled = !player.supportsYoutubeMusic;
        youtubeBtn.classList.toggle('chip--disabled', !player.supportsYoutubeMusic);
    }

    if (tidalBtn) {
        tidalBtn.disabled = !player.supportsTidal;
        tidalBtn.classList.toggle('chip--disabled', !player.supportsTidal);
    }

    if (deezerBtn) {
        deezerBtn.disabled = !player.supportsDeezer;
        deezerBtn.classList.toggle('chip--disabled', !player.supportsDeezer);
    }

    if (amazonBtn) {
        amazonBtn.disabled = !player.supportsAmazonMusic;
        amazonBtn.classList.toggle('chip--disabled', !player.supportsAmazonMusic);
    }

    // If current selection is now disabled, switch to Spotify
    if (adminState.selectedProvider === 'apple_music' && !player.supportsAppleMusic) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        adminState.selectedProvider = 'spotify';
    }

    if (adminState.selectedProvider === 'youtube_music' && !player.supportsYoutubeMusic) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        adminState.selectedProvider = 'spotify';
    }

    if (adminState.selectedProvider === 'tidal' && !player.supportsTidal) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        adminState.selectedProvider = 'spotify';
    }

    if (adminState.selectedProvider === 'deezer' && !player.supportsDeezer) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        adminState.selectedProvider = 'spotify';
    }

    if (adminState.selectedProvider === 'amazon_music' && !player.supportsAmazonMusic) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        adminState.selectedProvider = 'spotify';
    }

    // Show hint for disabled providers
    const hint = document.getElementById('provider-hint');
    if (hint) {
        const maSpeakerNeeded = [];
        if (!player.supportsAppleMusic) maSpeakerNeeded.push('Apple Music');
        if (!player.supportsYoutubeMusic) maSpeakerNeeded.push('YouTube Music');
        if (!player.supportsTidal) maSpeakerNeeded.push('Tidal');
        if (!player.supportsDeezer) maSpeakerNeeded.push('Deezer');

        const hintParts = [];
        if (maSpeakerNeeded.length > 0) {
            hintParts.push(`${maSpeakerNeeded.join(' and ')} require${maSpeakerNeeded.length === 1 ? 's' : ''} a Music Assistant speaker`);
        }
        if (!player.supportsAmazonMusic) {
            hintParts.push('Amazon Music requires an Amazon Echo (alexa_media)');
        }

        if (hintParts.length > 0) {
            hint.textContent = hintParts.join(' · ');
            hint.classList.remove('hidden');
        } else {
            hint.classList.add('hidden');
        }
    }
}

/**
 * Update provider warning based on selected speaker platform
 * Shows setup requirements and caveats per platform
 * @param {Object} player - Selected player with platform info
 */
export function updateProviderWarning(player) {
    const warningEl = document.getElementById('provider-warning');
    if (!warningEl) return;

    const platformInfo = {
        music_assistant: {
            warning: 'Premium account must be configured in Music Assistant',
        },
        sonos: {
            warning: 'Spotify must be linked in Sonos app',
        },
        alexa_media: {
            warning: 'Service must be linked in Alexa app',
            caveat: 'Uses voice search - may occasionally play a different version of the song',
        },
        alexa: {
            warning: 'Service must be linked in Alexa app',
            caveat: 'Uses voice search - may occasionally play a different version of the song',
        },
    };

    const info = platformInfo[player.platform];
    if (info) {
        let html = `<p>⚠️ ${utils.escapeHtml(info.warning)}</p>`;
        if (info.caveat) {
            html += `<p class="warning-caveat">ℹ️ ${utils.escapeHtml(info.caveat)}</p>`;
        }
        warningEl.innerHTML = html;
        warningEl.classList.remove('hidden');
    } else {
        warningEl.classList.add('hidden');
    }
}
