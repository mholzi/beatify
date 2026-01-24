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

// Language state (Story 12.4)
let selectedLanguage = 'en';

// Timer state (Story 13.1)
let selectedDuration = 45;

// Difficulty state (Story 14.1)
let selectedDifficulty = 'normal';

// Provider state (Story 17.2)
let selectedProvider = 'spotify';
let hasMusicAssistant = false;

// Artist Challenge state (Story 20.7)
let artistChallengeEnabled = true;

// Lobby state (Story 16.8)
let previousLobbyPlayers = [];
let lobbyPollingInterval = null;

// Setup sections to hide/show as a group (Story 9.10: game-controls removed, button is standalone)
const setupSections = ['media-players', 'playlists', 'provider-section', 'language-section', 'timer-section', 'difficulty-section', 'artist-challenge-section'];

// Alias BeatifyUtils for convenience
const utils = window.BeatifyUtils || {};

document.addEventListener('DOMContentLoaded', async () => {
    // Initialize i18n based on browser language (Story 12.4)
    // Guard clause: wait for BeatifyI18n in case fallback script is loading
    const i18nAvailable = await utils.waitForI18n();
    if (!i18nAvailable) {
        console.error('[Beatify] BeatifyI18n module failed to load - UI will use fallback text');
    } else {
        await BeatifyI18n.init();
        BeatifyI18n.initPageTranslations();
        selectedLanguage = BeatifyI18n.getLanguage();
    }
    updateLanguageButtons(selectedLanguage);

    // Wire event listeners
    document.getElementById('start-game')?.addEventListener('click', startGame);
    document.getElementById('print-qr')?.addEventListener('click', printQRCode);
    document.getElementById('rejoin-game')?.addEventListener('click', rejoinGame);

    // Dashboard URL is now set in showLobbyView() for analytics layout
    document.getElementById('end-game')?.addEventListener('click', endGame);
    document.getElementById('end-game-lobby')?.addEventListener('click', endGame);

    // Admin join setup
    setupAdminJoin();

    // End game modal setup (Story 9.10)
    setupEndGameModal();

    // Language selector setup (Story 12.4)
    setupLanguageSelector();

    // Timer selector setup (Story 13.1)
    setupTimerSelector();

    // Difficulty selector setup (Story 14.1)
    setupDifficultySelector();

    // Provider selector setup (Story 17.2)
    setupProviderSelector();

    // Artist Challenge toggle setup (Story 20.7)
    setupArtistChallengeToggle();

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
        // Set Music Assistant availability from backend (not based on entity names)
        hasMusicAssistant = status.has_music_assistant === true;
        // Display version in footer
        const versionEl = document.getElementById('app-version');
        if (versionEl && status.version) {
            versionEl.textContent = 'v' + status.version;
        }
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
        const container = document.getElementById('media-players-list');
        if (container) {
            container.innerHTML = '<span class="status-error">Failed to load status</span>';
        }
    }
}

/**
 * Render media players list with radio buttons for selection
 * Filters out unavailable players
 * @param {Array} players
 */
function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');
    // Remove data-i18n to prevent initPageTranslations from overwriting rendered content
    container?.removeAttribute('data-i18n');
    const totalPlayers = players ? players.length : 0;

    // Reset selection state
    selectedMediaPlayer = null;

    // Note: hasMusicAssistant is now set from backend status API (not based on entity names)

    // Filter out unavailable players
    const availablePlayers = (players || []).filter(p => p.state !== 'unavailable');

    // Hide validation message when showing empty states (avoid redundant messaging)
    const validationMsg = document.getElementById('media-player-validation-msg');

    if (totalPlayers === 0) {
        // AC2: No players configured at all
        const docsLink = mediaPlayerDocsUrl
            ? `<a href="${utils.escapeHtml(mediaPlayerDocsUrl)}" target="_blank" rel="noopener">Setup Guide</a>`
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
            ? `<a href="${utils.escapeHtml(mediaPlayerDocsUrl)}" target="_blank" rel="noopener">Troubleshooting</a>`
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
    container.innerHTML = availablePlayers.map(player => {
        // Show Music Assistant badge for MA players (enables Apple Music)
        const massBadge = player.is_mass
            ? '<span class="mass-badge" title="Music Assistant - Apple Music enabled">Music Assistant</span>'
            : '';
        return `
        <div class="media-player-item list-item is-selectable${player.is_mass ? ' is-mass-player' : ''}">
            <label class="radio-label">
                <input type="radio"
                       class="media-player-radio"
                       name="media-player"
                       data-entity-id="${utils.escapeHtml(player.entity_id)}"
                       data-state="${utils.escapeHtml(player.state)}"
                       data-is-mass="${player.is_mass ? 'true' : 'false'}">
                <span class="player-name">${utils.escapeHtml(player.friendly_name)}${massBadge}</span>
            </label>
            <span class="meta">
                <span class="state-dot state-${utils.escapeHtml(player.state)}"></span>
                ${utils.escapeHtml(player.state)}
            </span>
        </div>
    `;
    }).join('');

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
    // Remove data-i18n to prevent initPageTranslations from overwriting rendered content
    container?.removeAttribute('data-i18n');

    // Reset selection state
    selectedPlaylists = [];
    playlistData = playlists || [];

    // Check if we have any valid playlists
    const hasValidPlaylists = playlistData.some(p => p.is_valid);

    if (!playlists || playlists.length === 0) {
        // AC2: No playlists error with documentation link
        const docsLink = playlistDocsUrl
            ? `<a href="${utils.escapeHtml(playlistDocsUrl)}" target="_blank" rel="noopener">How to create playlists</a>`
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

    container.innerHTML = playlists.map(playlist => {
        if (playlist.is_valid) {
            // AC1: Valid playlists with checkbox
            const songCount = playlist.song_count || 0;
            // Provider count - Spotify only (Story 17.6)
            const providerCount = playlist.spotify_count || songCount;

            // Build coverage indicator
            let coverageHtml = '';
            if (providerCount < songCount) {
                const coverageClass = providerCount === 0
                    ? 'playlist-coverage playlist-coverage--none'
                    : 'playlist-coverage playlist-coverage--warning';
                coverageHtml = `<span class="${coverageClass}">${providerCount}/${songCount}</span>`;
            }

            return `
                <div class="playlist-item list-item is-selectable">
                    <label class="checkbox-label">
                        <input type="checkbox"
                               class="playlist-checkbox"
                               data-path="${utils.escapeHtml(playlist.path)}"
                               data-song-count="${utils.escapeHtml(String(songCount))}">
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

    // Show start button if we have valid playlists (Story 9.10)
    if (hasValidPlaylists) {
        document.getElementById('start-game')?.classList.remove('hidden');
    } else {
        document.getElementById('start-game')?.classList.add('hidden');
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

// escapeHtml moved to BeatifyUtils

// ==========================================
// View State Machine (Story 2.3)
// ==========================================

/**
 * Show setup view (initial state)
 */
function showSetupView() {
    currentView = 'setup';
    currentGame = null;

    // Stop lobby polling (Story 16.8)
    stopLobbyPolling();
    previousLobbyPlayers = [];

    // Show setup sections
    setupSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('hidden');
    });

    // Show start button if there are valid playlists (Story 9.10)
    const hasValidPlaylists = playlistData.some(p => p.is_valid);
    if (hasValidPlaylists) {
        document.getElementById('start-game')?.classList.remove('hidden');
    }

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

    // Hide start button and validation message (Story 9.10)
    document.getElementById('start-game')?.classList.add('hidden');
    document.getElementById('playlist-validation-msg')?.classList.add('hidden');

    // Hide existing game view
    document.getElementById('existing-game-section')?.classList.add('hidden');

    // Show lobby
    document.getElementById('lobby-section')?.classList.remove('hidden');

    // Generate QR code (only if URL changed) - compact size, CSS scales for desktop
    const qrContainer = document.getElementById('qr-code');
    if (qrContainer && gameData.join_url) {
        if (cachedQRUrl !== gameData.join_url) {
            qrContainer.innerHTML = '';

            if (typeof QRCode !== 'undefined') {
                new QRCode(qrContainer, {
                    text: gameData.join_url,
                    width: 180,
                    height: 180,
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

    // Update dashboard URL (compact inline link)
    var dashboardUrl = window.location.origin + '/beatify/dashboard';
    var dashboardLink = document.getElementById('admin-dashboard-url');
    if (dashboardLink) {
        dashboardLink.href = dashboardUrl;
    }

    // Render initial player list and start polling (Story 16.8)
    renderLobbyPlayers(gameData.players || []);
    startLobbyPolling();
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

    // Hide start button and validation message (Story 9.10)
    document.getElementById('start-game')?.classList.add('hidden');
    document.getElementById('playlist-validation-msg')?.classList.add('hidden');

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
                media_player: selectedMediaPlayer?.entityId,
                language: selectedLanguage,
                round_duration: selectedDuration,  // Story 13.1
                difficulty: selectedDifficulty,  // Story 14.1
                provider: selectedProvider,  // Story 17.2
                artist_challenge_enabled: artistChallengeEnabled  // Story 20.7
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
 * Show end game confirmation modal (Story 9.10)
 */
function showEndGameModal() {
    const modal = document.getElementById('end-game-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

/**
 * Close end game confirmation modal (Story 9.10)
 */
function closeEndGameModal() {
    const modal = document.getElementById('end-game-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * End the current game - shows confirmation modal (Story 9.10)
 */
function endGame() {
    showEndGameModal();
}

/**
 * Actually end the game after confirmation
 */
async function confirmEndGame() {
    closeEndGameModal();

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
 * Setup end game modal event listeners (Story 9.10)
 */
function setupEndGameModal() {
    const confirmBtn = document.getElementById('end-game-confirm-btn');
    const cancelBtn = document.getElementById('end-game-cancel-btn');
    const backdrop = document.querySelector('#end-game-modal .modal-backdrop');

    confirmBtn?.addEventListener('click', confirmEndGame);
    cancelBtn?.addEventListener('click', closeEndGameModal);
    backdrop?.addEventListener('click', closeEndGameModal);

    // ESC key handling added to global handler below
}

/**
 * Rejoin the current game - fetches fresh status first
 */
async function rejoinGame() {
    if (!currentGame) return;

    // Fetch fresh status to get latest player list
    try {
        var response = await fetch('/beatify/api/status');
        if (response.ok) {
            var status = await response.json();
            if (status.active_game) {
                currentGame = status.active_game;
            }
        }
    } catch (err) {
        console.error('Failed to refresh game status:', err);
    }

    // Show lobby view with current (possibly refreshed) game data
    showLobbyView(currentGame);
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

    // Close modals on Escape (Story 9.10: also handles end-game-modal)
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const adminModal = document.getElementById('admin-join-modal');
            const endGameModal = document.getElementById('end-game-modal');

            if (adminModal && !adminModal.classList.contains('hidden')) {
                closeAdminJoinModal();
            }
            if (endGameModal && !endGameModal.classList.contains('hidden')) {
                closeEndGameModal();
            }
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

/**
 * Setup language selector buttons (Story 12.4)
 */
function setupLanguageSelector() {
    var langButtons = document.querySelectorAll('.lang-btn');

    langButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var lang = btn.getAttribute('data-lang');
            if (lang && lang !== selectedLanguage) {
                setLanguage(lang);
            }
        });
    });
}

/**
 * Update language button states (Story 12.4)
 * @param {string} lang - Language code ('en', 'de', or 'es')
 */
function updateLanguageButtons(lang) {
    var langButtons = document.querySelectorAll('.lang-btn');
    langButtons.forEach(function(btn) {
        var btnLang = btn.getAttribute('data-lang');
        if (btnLang === lang) {
            btn.classList.add('lang-btn--active');
        } else {
            btn.classList.remove('lang-btn--active');
        }
    });
}

/**
 * Set language and update UI (Story 12.4, 16.3)
 * @param {string} lang - Language code ('en', 'de', or 'es')
 */
async function setLanguage(lang) {
    if (lang !== 'en' && lang !== 'de' && lang !== 'es') {
        lang = 'en';
    }

    selectedLanguage = lang;
    updateLanguageButtons(lang);

    // Update i18n and re-render page
    await BeatifyI18n.setLanguage(lang);
    BeatifyI18n.initPageTranslations();
}

// ==========================================
// Timer Selector Functions (Story 13.1)
// ==========================================

/**
 * Setup timer selector buttons
 */
function setupTimerSelector() {
    var timerButtons = document.querySelectorAll('.timer-btn');

    timerButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var duration = parseInt(btn.getAttribute('data-duration'), 10);
            if (duration && duration !== selectedDuration) {
                setTimerDuration(duration);
            }
        });
    });
}

/**
 * Update timer button states
 * @param {number} duration - Duration in seconds (15, 30, or 45)
 */
function updateTimerButtons(duration) {
    var timerButtons = document.querySelectorAll('.timer-btn');
    timerButtons.forEach(function(btn) {
        var btnDuration = parseInt(btn.getAttribute('data-duration'), 10);
        if (btnDuration === duration) {
            btn.classList.add('timer-btn--active');
        } else {
            btn.classList.remove('timer-btn--active');
        }
    });
}

/**
 * Set timer duration
 * @param {number} duration - Duration in seconds (10-60 range)
 */
function setTimerDuration(duration) {
    // Validate duration is within valid range (matches backend: 10-60)
    if (typeof duration !== 'number' || duration < 10 || duration > 60) {
        duration = 30;
    }

    selectedDuration = duration;
    updateTimerButtons(duration);
}

// ==========================================
// Difficulty Selector Functions (Story 14.1)
// ==========================================

// Mapping of difficulty levels to their description i18n keys
const difficultyDescriptions = {
    easy: 'admin.difficultyEasyDesc',
    normal: 'admin.difficultyNormalDesc',
    hard: 'admin.difficultyHardDesc'
};

/**
 * Setup difficulty selector buttons
 */
function setupDifficultySelector() {
    var difficultyButtons = document.querySelectorAll('.difficulty-btn');

    difficultyButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var difficulty = btn.getAttribute('data-difficulty');
            if (difficulty && difficulty !== selectedDifficulty) {
                setDifficulty(difficulty);
            }
        });
    });
}

/**
 * Update difficulty button states
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function updateDifficultyButtons(difficulty) {
    var difficultyButtons = document.querySelectorAll('.difficulty-btn');
    difficultyButtons.forEach(function(btn) {
        var btnDifficulty = btn.getAttribute('data-difficulty');
        if (btnDifficulty === difficulty) {
            btn.classList.add('difficulty-btn--active');
        } else {
            btn.classList.remove('difficulty-btn--active');
        }
    });
}

/**
 * Set difficulty level and update UI
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function setDifficulty(difficulty) {
    // Validate difficulty
    var validDifficulties = ['easy', 'normal', 'hard'];
    if (validDifficulties.indexOf(difficulty) === -1) {
        difficulty = 'normal';
    }

    selectedDifficulty = difficulty;
    updateDifficultyButtons(difficulty);

    // Update description text
    var descriptionEl = document.getElementById('difficulty-description');
    if (descriptionEl) {
        var descKey = difficultyDescriptions[difficulty];
        descriptionEl.setAttribute('data-i18n', descKey);
        // Use i18n translation if available
        if (typeof BeatifyI18n !== 'undefined' && BeatifyI18n.t) {
            descriptionEl.textContent = BeatifyI18n.t(descKey);
        }
    }
}

// ==========================================
// Artist Challenge Toggle Functions (Story 20.7)
// ==========================================

/**
 * Setup artist challenge toggle
 */
function setupArtistChallengeToggle() {
    var toggle = document.getElementById('artist-challenge-toggle');
    if (!toggle) return;

    // Load saved preference
    var saved = localStorage.getItem('beatify_artist_challenge');
    if (saved !== null) {
        artistChallengeEnabled = saved === 'true';
        toggle.checked = artistChallengeEnabled;
    }

    toggle.addEventListener('change', function() {
        artistChallengeEnabled = toggle.checked;
        // Save preference
        localStorage.setItem('beatify_artist_challenge', artistChallengeEnabled.toString());
    });
}

// ==========================================
// Provider Selector Functions (Story 17.2)
// ==========================================

/**
 * Setup provider selector buttons
 */
function setupProviderSelector() {
    var providerButtons = document.querySelectorAll('.provider-btn');

    providerButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            // Don't allow clicking disabled buttons
            if (btn.classList.contains('provider-btn--disabled')) {
                return;
            }
            var provider = btn.getAttribute('data-provider');
            if (provider && provider !== selectedProvider) {
                setProvider(provider);
            }
        });
    });
}

/**
 * Update provider button states
 * @param {string} provider - Provider identifier ('spotify' or 'apple_music')
 */
function updateProviderButtons(provider) {
    var providerButtons = document.querySelectorAll('.provider-btn');
    providerButtons.forEach(function(btn) {
        var btnProvider = btn.getAttribute('data-provider');
        if (btnProvider === provider) {
            btn.classList.add('provider-btn--active');
        } else {
            btn.classList.remove('provider-btn--active');
        }
    });
}

/**
 * Set music provider and update UI
 * @param {string} provider - Provider identifier (only 'spotify' supported, Story 17.6)
 */
function setProvider(provider) {
    // Only Spotify is supported (Story 17.6: Apple Music removed)
    selectedProvider = 'spotify';
    updateProviderButtons('spotify');

    // Re-render playlists to show coverage for selected provider
    if (playlistData.length > 0) {
        renderPlaylists(playlistData, '');
    }
}

// ==========================================
// Lobby Player List Functions (Story 16.8)
// ==========================================

// t() moved to BeatifyUtils

/**
 * Render player list in admin lobby (analytics grid layout)
 * @param {Array} players - Array of player objects from game state
 */
function renderLobbyPlayers(players) {
    var listEl = document.getElementById('lobby-players');
    var countEl = document.getElementById('lobby-player-count');
    var emptyEl = document.getElementById('lobby-players-empty');
    var statusEl = document.getElementById('lobby-status-value');
    if (!listEl) return;

    players = players || [];

    // Update player count (stat card value - just the number)
    if (countEl) {
        countEl.textContent = players.length;
    }

    // Update status based on player count
    if (statusEl) {
        if (players.length === 0) {
            statusEl.textContent = utils.t('lobby.statusWaiting', 'Waiting');
        } else if (players.length >= 2) {
            statusEl.textContent = utils.t('lobby.statusReady', 'Ready');
        } else {
            statusEl.textContent = utils.t('lobby.statusNeedMore', 'Need 1+');
        }
    }

    // Handle empty state visibility
    if (players.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        previousLobbyPlayers = [];
        return;
    }

    // Hide empty state when we have players
    if (emptyEl) emptyEl.classList.add('hidden');

    // Sort: connected first, disconnected last
    var sortedPlayers = players.slice().sort(function(a, b) {
        if (a.connected !== b.connected) {
            return a.connected ? -1 : 1;
        }
        return 0;
    });

    // Find new players by comparing with previous list
    var previousNames = previousLobbyPlayers.map(function(p) { return p.name; });
    var newNames = sortedPlayers
        .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
        .map(function(p) { return p.name; });

    // Render player cards (grid layout)
    listEl.innerHTML = sortedPlayers.map(function(player) {
        var isNew = newNames.indexOf(player.name) !== -1;
        var isDisconnected = player.connected === false;
        var isAdmin = player.is_admin === true;
        var classes = [
            'player-card',
            isNew ? 'is-new' : '',
            isDisconnected ? 'player-card--disconnected' : ''
        ].filter(Boolean).join(' ');

        // Crown badge for admin
        var adminBadge = isAdmin ? '<span class="admin-badge">👑</span>' : '';
        // Badge for disconnected players
        var awayBadge = isDisconnected ? '<span class="away-badge">' + utils.t('lobby.away', 'away') + '</span>' : '';

        return '<div class="' + classes + '" data-player="' + utils.escapeHtml(player.name) + '">' +
            '<span class="player-name">' +
                utils.escapeHtml(player.name) +
                adminBadge +
            '</span>' +
            awayBadge +
        '</div>';
    }).join('');

    // Remove .is-new class after animation
    setTimeout(function() {
        var newCards = listEl.querySelectorAll('.is-new');
        for (var i = 0; i < newCards.length; i++) {
            newCards[i].classList.remove('is-new');
        }
    }, 2000);

    previousLobbyPlayers = players.slice();
}

/**
 * Start polling for lobby state updates
 */
function startLobbyPolling() {
    // Clear any existing interval
    stopLobbyPolling();

    // Poll every 3 seconds (balanced between responsiveness and server load)
    lobbyPollingInterval = setInterval(async function() {
        if (currentView !== 'lobby') {
            stopLobbyPolling();
            return;
        }

        try {
            var response = await fetch('/beatify/api/status');
            if (!response.ok) return;

            var status = await response.json();
            if (status.active_game && status.active_game.players) {
                renderLobbyPlayers(status.active_game.players);
            }
        } catch (err) {
            console.error('Lobby polling error:', err);
        }
    }, 3000);
}

/**
 * Stop polling for lobby state updates
 */
function stopLobbyPolling() {
    if (lobbyPollingInterval) {
        clearInterval(lobbyPollingInterval);
        lobbyPollingInterval = null;
    }
}

// ============================================
// Service Worker Registration (Story 18.5)
// ============================================

/**
 * Register service worker for asset caching
 */
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/beatify/static/sw.js', {
            scope: '/beatify/'
        }).then(function(registration) {
            console.log('[Admin] SW registered:', registration.scope);
        }).catch(function(error) {
            console.warn('[Admin] SW registration failed:', error);
        });
    });
}
