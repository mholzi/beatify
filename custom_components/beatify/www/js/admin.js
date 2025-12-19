/**
 * Beatify Admin Page
 * Vanilla JS - no frameworks
 */

// Module-level state
let selectedPlaylists = [];
let playlistData = [];
let playlistDocsUrl = '';
let selectedMediaPlayer = null;  // { entityId: string, state: string } or null
let mediaPlayerDocsUrl = '';

// View state management (Story 2.3)
let currentView = 'setup';
let currentGame = null;
let cachedQRUrl = null;

// Setup sections to hide/show as a group
const setupSections = ['ma-status', 'media-players', 'playlists', 'game-controls'];
const allViews = ['setup', 'lobby', 'existing-game'];

document.addEventListener('DOMContentLoaded', async () => {
    // Wire event listeners
    document.getElementById('start-game')?.addEventListener('click', startGame);
    document.getElementById('print-qr')?.addEventListener('click', printQRCode);
    document.getElementById('rejoin-game')?.addEventListener('click', rejoinGame);
    document.getElementById('end-game')?.addEventListener('click', endGame);
    document.getElementById('end-game-lobby')?.addEventListener('click', endGame);

    // Admin join setup
    setupAdminJoin();

    await loadStatus();
});

/**
 * Fetch and render current status from the API
 */
async function loadStatus() {
    try {
        const response = await fetch('/beatify/api/status');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const status = await response.json();

        playlistDocsUrl = status.playlist_docs_url || '';
        mediaPlayerDocsUrl = status.media_player_docs_url || '';
        renderMAStatus(status.ma_configured, status.ma_setup_url);
        renderMediaPlayers(status.media_players);
        renderPlaylists(status.playlists, status.playlist_dir);
        updateStartButtonState();

        // Check for active game and show appropriate view
        if (status.active_game) {
            showExistingGameView(status.active_game);
        } else {
            showSetupView();
        }
    } catch (error) {
        console.error('Failed to load status:', error);
        document.getElementById('ma-status-content').innerHTML =
            '<span class="status-error">Failed to load status</span>';
    }
}

/**
 * Render Music Assistant status
 * @param {boolean} isConfigured
 * @param {string} setupUrl
 */
function renderMAStatus(isConfigured, setupUrl) {
    const container = document.getElementById('ma-status-content');

    if (isConfigured) {
        container.innerHTML = '<span class="status-connected">✓ Connected</span>';
    } else {
        container.innerHTML = `
            <span class="status-error">✗ Not configured</span>
            <p style="margin-top: 8px;">Music Assistant is required for Beatify to play songs.</p>
            <a href="${escapeHtml(setupUrl)}" target="_blank" rel="noopener" class="btn btn-secondary" style="margin-top: 12px;">
                Setup Guide
            </a>
        `;
    }
}

/**
 * Render media players list with radio buttons for selection
 * Filters out unavailable players (AC1, AC2, AC3)
 * @param {Array} players
 */
function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');
    const totalPlayers = players ? players.length : 0;

    // Reset selection state
    selectedMediaPlayer = null;

    // Filter out unavailable players
    const availablePlayers = (players || []).filter(p => p.state !== 'unavailable');

    // Hide validation message when showing empty states (avoid redundant messaging)
    const validationMsg = document.getElementById('media-player-validation-msg');

    if (totalPlayers === 0) {
        // AC2: No players configured at all
        const docsLink = mediaPlayerDocsUrl
            ? `<a href="${escapeHtml(mediaPlayerDocsUrl)}" target="_blank" rel="noopener">Setup Guide</a>`
            : '';
        container.innerHTML = `
            <div class="empty-state">
                <p class="status-error">No media players found. Configure a media player in Home Assistant.</p>
                ${docsLink ? `<p style="margin-top: 12px;">${docsLink}</p>` : ''}
            </div>
        `;
        if (validationMsg) {
            validationMsg.classList.add('hidden');
        }
        return;
    }

    if (availablePlayers.length === 0) {
        // AC3: Players exist but all unavailable
        const docsLink = mediaPlayerDocsUrl
            ? `<a href="${escapeHtml(mediaPlayerDocsUrl)}" target="_blank" rel="noopener">Troubleshooting</a>`
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

    // AC1: Render only available players with radio buttons
    container.innerHTML = availablePlayers.map(player => `
        <div class="media-player-item list-item is-selectable">
            <label class="radio-label">
                <input type="radio"
                       class="media-player-radio"
                       name="media-player"
                       data-entity-id="${escapeHtml(player.entity_id)}"
                       data-state="${escapeHtml(player.state)}">
                <span class="player-name">${escapeHtml(player.friendly_name)}</span>
            </label>
            <span class="meta">
                <span class="state-dot state-${escapeHtml(player.state)}"></span>
                ${escapeHtml(player.state)}
            </span>
        </div>
    `).join('');

    // Attach event listeners to radio buttons
    container.querySelectorAll('.media-player-radio').forEach(radio => {
        radio.addEventListener('change', function() {
            handleMediaPlayerSelect(this);
        });
    });
}

/**
 * Handle media player radio button selection (AC4)
 * @param {HTMLInputElement} radio
 */
function handleMediaPlayerSelect(radio) {
    const entityId = radio.dataset.entityId;
    const state = radio.dataset.state;

    // Update module state
    selectedMediaPlayer = { entityId, state };

    // Update visual selection
    document.querySelectorAll('.media-player-item').forEach(item => {
        item.classList.remove('is-selected');
    });
    radio.closest('.media-player-item').classList.add('is-selected');

    updateStartButtonState();
}

/**
 * Render playlists list with checkboxes for valid playlists
 * @param {Array} playlists
 * @param {string} playlistDir
 */
function renderPlaylists(playlists, playlistDir) {
    const container = document.getElementById('playlists-list');

    // Reset selection state
    selectedPlaylists = [];
    playlistData = playlists || [];

    // Check if we have any valid playlists
    const hasValidPlaylists = playlistData.some(p => p.is_valid);

    if (!playlists || playlists.length === 0) {
        // AC2: No playlists error with documentation link
        const docsLink = playlistDocsUrl
            ? `<a href="${escapeHtml(playlistDocsUrl)}" target="_blank" rel="noopener">How to create playlists</a>`
            : '';
        container.innerHTML = `
            <div class="empty-state">
                <p class="status-error">No playlists found. Add playlist JSON files to:</p>
                <p style="font-size: 14px;"><code>${escapeHtml(playlistDir)}</code></p>
                ${docsLink ? `<p style="margin-top: 12px;">${docsLink}</p>` : ''}
            </div>
        `;
        // Hide game controls when no playlists
        document.getElementById('game-controls').classList.add('hidden');
        return;
    }

    container.innerHTML = playlists.map(playlist => {
        if (playlist.is_valid) {
            // AC1: Valid playlists with checkbox
            const songCount = escapeHtml(String(playlist.song_count));
            return `
                <div class="playlist-item list-item is-selectable">
                    <label class="checkbox-label">
                        <input type="checkbox"
                               class="playlist-checkbox"
                               data-path="${escapeHtml(playlist.path)}"
                               data-song-count="${songCount}">
                        <span class="playlist-name">${escapeHtml(playlist.name)}</span>
                    </label>
                    <span class="meta">${songCount} songs</span>
                </div>
            `;
        } else {
            // Invalid playlists: no checkbox, greyed out
            const errorMsg = (playlist.errors && playlist.errors[0]) || 'Unknown error';
            return `
                <div class="list-item is-invalid">
                    <span class="name">${escapeHtml(playlist.name)}</span>
                    <span class="meta">Invalid: ${escapeHtml(errorMsg)}</span>
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

    // Show game controls if we have valid playlists
    if (hasValidPlaylists) {
        document.getElementById('game-controls').classList.remove('hidden');
    } else {
        document.getElementById('game-controls').classList.add('hidden');
    }

    // Initialize summary as hidden
    updateSelectionSummary();
}

/**
 * Handle playlist checkbox toggle
 * @param {HTMLInputElement} checkbox
 */
function handlePlaylistToggle(checkbox) {
    const path = checkbox.dataset.path;
    const songCount = parseInt(checkbox.dataset.songCount, 10) || 0;
    const item = checkbox.closest('.playlist-item');

    if (checkbox.checked) {
        // Prevent duplicate selections
        if (!selectedPlaylists.some(p => p.path === path)) {
            selectedPlaylists.push({ path, songCount });
        }
        item.classList.add('is-selected');
    } else {
        selectedPlaylists = selectedPlaylists.filter(p => p.path !== path);
        item.classList.remove('is-selected');
    }

    updateSelectionSummary();
    updateStartButtonState();
}

/**
 * Calculate total songs from selected playlists
 * @returns {number}
 */
function calculateTotalSongs() {
    return selectedPlaylists.reduce((sum, p) => sum + p.songCount, 0);
}

/**
 * Update the selection summary display
 */
function updateSelectionSummary() {
    const summary = document.getElementById('playlist-summary');
    const selectedCount = document.getElementById('selected-count');
    const totalSongs = document.getElementById('total-songs');

    // Null check for DOM elements
    if (!summary || !selectedCount || !totalSongs) {
        return;
    }

    if (selectedPlaylists.length === 0) {
        summary.classList.add('hidden');
    } else {
        summary.classList.remove('hidden');
        selectedCount.textContent = selectedPlaylists.length;
        totalSongs.textContent = calculateTotalSongs();
    }
}

/**
 * Update start button enabled/disabled state and validation messages
 * Checks for both playlist AND media player selection
 */
function updateStartButtonState() {
    const btn = document.getElementById('start-game');
    const playlistMsg = document.getElementById('playlist-validation-msg');
    const mediaPlayerMsg = document.getElementById('media-player-validation-msg');

    if (!btn) {
        return;
    }

    const noPlaylist = selectedPlaylists.length === 0;
    const noMediaPlayer = selectedMediaPlayer === null;

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

/**
 * Escape HTML to prevent XSS
 * @param {string} text
 * @returns {string}
 */
function escapeHtml(text) {
    if (text === null || text === undefined) {
        return '';
    }
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

// ==========================================
// View State Machine (Story 2.3)
// ==========================================

/**
 * Show setup view (initial state)
 */
function showSetupView() {
    currentView = 'setup';
    currentGame = null;

    // Show setup sections
    setupSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('hidden');
    });

    // Hide other views
    document.getElementById('lobby-section')?.classList.add('hidden');
    document.getElementById('existing-game-section')?.classList.add('hidden');
}

/**
 * Show lobby view with QR code
 * @param {Object} gameData - Game data from API
 */
function showLobbyView(gameData) {
    currentView = 'lobby';
    currentGame = gameData;

    // Hide setup sections
    setupSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Hide existing game view
    document.getElementById('existing-game-section')?.classList.add('hidden');

    // Show lobby
    document.getElementById('lobby-section')?.classList.remove('hidden');

    // Generate QR code (only if URL changed)
    const qrContainer = document.getElementById('qr-code');
    if (qrContainer && gameData.join_url) {
        if (cachedQRUrl !== gameData.join_url) {
            qrContainer.innerHTML = '';

            if (typeof QRCode !== 'undefined') {
                new QRCode(qrContainer, {
                    text: gameData.join_url,
                    width: 300,
                    height: 300,
                    colorDark: '#000000',
                    colorLight: '#ffffff',
                    correctLevel: QRCode.CorrectLevel.M
                });
            } else {
                qrContainer.innerHTML = '<p class="status-error">QR code library not loaded</p>';
            }

            cachedQRUrl = gameData.join_url;
        }
    }

    // Display join URL
    const urlEl = document.getElementById('join-url');
    if (urlEl && gameData.join_url) {
        urlEl.textContent = gameData.join_url;
    }
}

/**
 * Show existing game view (for rejoin/end)
 * @param {Object} gameData - Game data from status API
 */
function showExistingGameView(gameData) {
    currentView = 'existing-game';
    currentGame = gameData;

    // Hide setup sections
    setupSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Hide lobby
    document.getElementById('lobby-section')?.classList.add('hidden');

    // Show existing game section
    document.getElementById('existing-game-section')?.classList.remove('hidden');

    // Update game info
    const idEl = document.getElementById('existing-game-id');
    const phaseEl = document.getElementById('existing-game-phase');
    const playersEl = document.getElementById('existing-game-players');

    if (idEl) idEl.textContent = gameData.game_id || 'Unknown';
    if (phaseEl) phaseEl.textContent = gameData.phase || 'Unknown';
    if (playersEl) playersEl.textContent = gameData.player_count ?? 0;
}

// ==========================================
// Game Control Functions (Story 2.3)
// ==========================================

/**
 * Start a new game
 */
async function startGame() {
    const btn = document.getElementById('start-game');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = 'Starting...';

    try {
        const response = await fetch('/beatify/api/start-game', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                playlists: selectedPlaylists.map(p => p.path),
                media_player: selectedMediaPlayer?.entityId
            })
        });

        const data = await response.json();

        if (!response.ok) {
            showError(data.message || 'Failed to start game');
            return;
        }

        if (data.warnings && data.warnings.length > 0) {
            console.warn('Game started with warnings:', data.warnings);
        }

        showLobbyView(data);

    } catch (err) {
        showError('Network error. Please try again.');
        console.error('Start game error:', err);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
        updateStartButtonState();
    }
}

/**
 * End the current game
 */
async function endGame() {
    if (!confirm('End the current game? All players will be disconnected.')) {
        return;
    }

    try {
        const response = await fetch('/beatify/api/end-game', { method: 'POST' });
        if (response.ok) {
            cachedQRUrl = null;  // Clear QR cache
            showSetupView();
        } else {
            const data = await response.json();
            showError(data.message || 'Failed to end game');
        }
    } catch (err) {
        console.error('End game error:', err);
        showError('Network error. Please try again.');
    }
}

/**
 * Rejoin the current game
 */
function rejoinGame() {
    if (!currentGame) return;

    if (currentGame.phase === 'LOBBY') {
        showLobbyView(currentGame);
    } else {
        // For other phases, show lobby view for now (future: show game view)
        showLobbyView(currentGame);
    }
}

/**
 * Print QR code
 */
function printQRCode() {
    window.print();
}

/**
 * Show error message to user
 * @param {string} message
 */
function showError(message) {
    // Simple alert for now - can be enhanced with toast notifications
    alert(message);
}

// ==========================================
// Admin Join Functions (Story 3.5)
// ==========================================

/**
 * Open admin join modal
 */
function openAdminJoinModal() {
    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.remove('hidden');
        document.getElementById('admin-name-input')?.focus();
    }
}

/**
 * Close admin join modal
 */
function closeAdminJoinModal() {
    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
    // Reset form
    const nameInput = document.getElementById('admin-name-input');
    const joinBtn = document.getElementById('admin-join-btn');
    const errorMsg = document.getElementById('admin-name-error');
    if (nameInput) nameInput.value = '';
    if (joinBtn) {
        joinBtn.disabled = true;
        joinBtn.textContent = 'Join';
    }
    if (errorMsg) errorMsg.classList.add('hidden');
}

/**
 * Setup admin join modal and button handlers
 */
function setupAdminJoin() {
    const participateBtn = document.getElementById('participate-btn');
    const cancelBtn = document.getElementById('admin-cancel-btn');
    const joinBtn = document.getElementById('admin-join-btn');
    const nameInput = document.getElementById('admin-name-input');
    const backdrop = document.querySelector('#admin-join-modal .modal-backdrop');

    participateBtn?.addEventListener('click', openAdminJoinModal);
    cancelBtn?.addEventListener('click', closeAdminJoinModal);
    backdrop?.addEventListener('click', closeAdminJoinModal);

    nameInput?.addEventListener('input', function() {
        const name = this.value.trim();
        joinBtn.disabled = !name || name.length > 20;
    });

    nameInput?.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !joinBtn.disabled) {
            handleAdminJoin();
        }
    });

    joinBtn?.addEventListener('click', handleAdminJoin);

    // Close on Escape
    document.addEventListener('keydown', function(e) {
        const modal = document.getElementById('admin-join-modal');
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeAdminJoinModal();
        }
    });
}

/**
 * Handle admin join button click
 */
function handleAdminJoin() {
    const nameInput = document.getElementById('admin-name-input');
    const joinBtn = document.getElementById('admin-join-btn');
    const name = nameInput?.value.trim();

    if (!name) return;

    joinBtn.disabled = true;
    joinBtn.textContent = 'Joining...';

    try {
        // Store admin name for player page
        sessionStorage.setItem('beatify_admin_name', name);
        sessionStorage.setItem('beatify_is_admin', 'true');

        // Redirect to player page with game ID
        const gameId = currentGame?.game_id;
        if (gameId) {
            window.location.href = '/beatify/play?game=' + encodeURIComponent(gameId);
        } else {
            showError('No active game found');
            joinBtn.disabled = false;
            joinBtn.textContent = 'Join';
        }
    } catch (err) {
        console.error('Admin join failed:', err);
        joinBtn.disabled = false;
        joinBtn.textContent = 'Join';
    }
}
