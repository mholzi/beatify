/**
 * Beatify Admin Page
 * Vanilla JS - no frameworks
 */

// Issue #386: Admin token auth for REST endpoints
// Issue #477: Persist token in localStorage (survives tab close)
function _getAdminToken() {
    try {
        var gameId = currentGame?.game_id;
        if (gameId) {
            var token = localStorage.getItem('beatify_admin_token_' + gameId);
            if (token) return token;
        }
        return localStorage.getItem('beatify_admin_token');
    } catch(e) { return null; }
}

function _setAdminToken(token, gameId) {
    try {
        if (gameId) localStorage.setItem('beatify_admin_token_' + gameId, token);
        localStorage.setItem('beatify_admin_token', token);
        // Migrate: also clear old sessionStorage key
        sessionStorage.removeItem('beatify_admin_token');
    } catch(e) {}
}

function _adminHeaders() {
    var token = _getAdminToken();
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return headers;
}

// Screen Wake Lock (#622)
// Prevents screen from dimming/locking while the admin is running a game.
var _wakeLock = null;

async function _requestWakeLock() {
    if (!('wakeLock' in navigator)) return;
    try {
        _wakeLock = await navigator.wakeLock.request('screen');
        _wakeLock.addEventListener('release', function() {
            _wakeLock = null;
        });
    } catch (err) {
        // Silently fail — browser may deny if page is not visible
    }
}

function _releaseWakeLock() {
    if (_wakeLock) {
        _wakeLock.release();
        _wakeLock = null;
    }
}

// #647: Re-acquire wake lock when admin tab becomes visible during an active game
// #648: Reconnect admin WS on tab return (e.g. after screen sleep)
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible' && currentGame && currentGame.phase !== 'END') {
        _requestWakeLock();
        // Reconnect WS if it died while tab was hidden
        if (!adminWs || adminWs.readyState !== WebSocket.OPEN) {
            adminReconnectAttempts = 0; // reset backoff on user-initiated return
            connectAdminWebSocket();
        }
    }
});

// Module-level state
let selectedPlaylists = [];
let playlistData = [];
let playlistDocsUrl = '';
let activeFilterTags = ['all'];  // Tag filter state (Issue #70)
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

// Intro Mode state (Issue #23)
let introModeEnabled = false;

// Closest Wins mode state (Issue #442)
let closestWinsModeEnabled = false;

// Lobby state (Story 16.8)
let previousLobbyPlayers = [];
let lobbyPollingInterval = null;

// Issue #477: Admin WebSocket state
let adminWs = null;
let adminPlayerName = null;   // Set when admin joins as player
let isPlaying = false;        // Whether admin is participating as a player
let adminReconnectAttempts = 0;
const MAX_ADMIN_RECONNECT = 10;
let countdownInterval = null;

// LocalStorage keys
const STORAGE_LAST_PLAYER = 'beatify_last_player';
const STORAGE_GAME_SETTINGS = 'beatify_game_settings';

// Setup sections to hide/show as a group
const setupSections = ['media-players', 'music-service', 'playlists', 'game-settings', 'admin-actions', 'my-requests', 'import-playlist', 'party-lights', 'tts-settings', 'ha-entities'];

// Platform display labels for speaker grouping
const PLATFORM_LABELS = {
    music_assistant: { icon: '🎵', label: 'Music Assistant', recommended: true },
    sonos: { icon: '🔊', label: 'Sonos' },
    alexa_media: { icon: '📢', label: 'Alexa' },
    alexa: { icon: '📢', label: 'Alexa' },
};

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
    // Set initial language chip active state
    document.querySelectorAll('.chip[data-lang]').forEach(c => {
        c.classList.toggle('chip--active', c.dataset.lang === selectedLanguage);
    });

    // Wire event listeners
    document.getElementById('start-game')?.addEventListener('click', startGame);
    document.getElementById('start-gameplay-btn')?.addEventListener('click', startGameplay);
    document.getElementById('print-qr')?.addEventListener('click', printQRCode);
    document.getElementById('rejoin-game')?.addEventListener('click', rejoinGame);

    // Dashboard URL is now set in showLobbyView() for analytics layout
    document.getElementById('end-game')?.addEventListener('click', endGame);
    document.getElementById('end-game-lobby')?.addEventListener('click', endGame);
    document.getElementById('end-game-existing')?.addEventListener('click', endGame);

    // Admin join setup
    setupAdminJoin();

    // Issue #477: Wire game phase control buttons
    document.getElementById('admin-stop-song')?.addEventListener('click', adminStopSong);
    document.getElementById('admin-seek-forward')?.addEventListener('click', adminSeekForward);
    document.getElementById('admin-vol-down')?.addEventListener('click', adminVolumeDown);
    document.getElementById('admin-vol-up')?.addEventListener('click', adminVolumeUp);
    document.getElementById('admin-end-game-playing')?.addEventListener('click', endGame);
    document.getElementById('admin-stop-lights')?.addEventListener('click', function() {
        if (adminWs && adminWs.readyState === WebSocket.OPEN) {
            adminWs.send(JSON.stringify({ type: 'admin', action: 'stop_lights' }));
        }
    });
    document.getElementById('admin-next-round')?.addEventListener('click', adminNextRound);
    document.getElementById('admin-skip-round')?.addEventListener('click', adminNextRound);
    document.getElementById('admin-confirm-intro')?.addEventListener('click', function() {
        sendAdminCommand({ type: 'admin', action: 'confirm_intro_splash' });
    });
    document.getElementById('admin-rematch')?.addEventListener('click', showRematchModal);
    document.getElementById('admin-new-game')?.addEventListener('click', adminDismissGame);

    // End game modal setup (Story 9.10)
    setupEndGameModal();

    // Issue #108: Rematch modal setup
    setupRematchModal();

    // Collapsible sections setup
    setupCollapsibleSections();

    // Spotify playlist import setup (#165)
    setupSpotifyImport();

    // Game settings setup (language, timer, difficulty, artist challenge)
    setupGameSettings();

    // Playlist requests setup (Story 44.2, 44.3)
    setupPlaylistRequests();

    // Load saved game settings from localStorage
    await loadSavedSettings();

    await loadStatus();

    // Initialize playlist requests display (Story 44.3, 44.4)
    initPlaylistRequests();
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
        // Display version in footer and expose globally (Story 44.5)
        const versionEl = document.getElementById('app-version');
        if (versionEl && status.version) {
            versionEl.textContent = 'v' + status.version;
            window.BEATIFY_VERSION = status.version;
        }
        renderMediaPlayers(status.media_players);
        renderPlaylists(status.playlists, status.playlist_dir);
        updateStartButtonState();

        // Check for active game and show appropriate view
        if (status.active_game && status.active_game.phase === 'LOBBY') {
            currentGame = status.active_game;
            _requestWakeLock(); // #647: keep screen on when reconnecting to active game
            showLobbyView(status.active_game);
            // Issue #477: Reconnect admin WS if we have a token
            if (!adminWs || adminWs.readyState !== WebSocket.OPEN) {
                connectAdminWebSocket();
            }
        } else if (status.active_game && status.active_game.phase !== 'END') {
            currentGame = status.active_game;
            // Issue #477: Connect WS and render phase directly instead of stub
            if (!adminWs || adminWs.readyState !== WebSocket.OPEN) {
                connectAdminWebSocket();
            }
            // Show correct phase view — WS state update will refine it
            handleAdminStateUpdate(status.active_game);
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
 * Setup collapsible section toggles
 */
function setupCollapsibleSections() {
    // Generic collapsible section toggles — handles all .section-header-collapsible
    // buttons including media-players, game-settings, my-requests, Party Lights, etc.
    // Issue #550: Removed duplicate per-ID listeners that caused double-toggle (no-op).
    document.querySelectorAll('.section-header-collapsible').forEach(function(header) {
        header.addEventListener('click', function() {
            const section = header.closest('.section-collapsible');
            if (section) {
                section.classList.toggle('collapsed');
                header.setAttribute('aria-expanded', !section.classList.contains('collapsed'));
            }
        });
    });
}

/**
 * Setup Spotify playlist import (#165)
 */
async function setupSpotifyImport() {
    // Check if credentials are configured
    try {
        var resp = await fetch('/beatify/api/spotify-credentials');
        var data = await resp.json();
        if (data.configured) {
            var importForm = document.getElementById('spotify-import-form');
            if (importForm) importForm.classList.remove('hidden');
        } else {
            var setupBtn = document.getElementById('spotify-setup-btn');
            if (setupBtn) setupBtn.classList.remove('hidden');
        }
    } catch (e) {
        var setupBtn = document.getElementById('spotify-setup-btn');
        if (setupBtn) setupBtn.classList.remove('hidden');
    }

    // Setup credentials button
    document.getElementById('spotify-setup-btn')?.addEventListener('click', function() {
        this.classList.add('hidden');
        var credsForm = document.getElementById('spotify-creds-form');
        if (credsForm) credsForm.classList.remove('hidden');
    });

    // Save credentials
    document.getElementById('spotify-save-creds')?.addEventListener('click', async function() {
        var clientId = document.getElementById('spotify-client-id')?.value?.trim();
        var clientSecret = document.getElementById('spotify-client-secret')?.value?.trim();
        if (!clientId || !clientSecret) { alert('Both fields required'); return; }

        this.disabled = true;
        this.textContent = '⏳';
        try {
            var resp = await fetch('/beatify/api/spotify-credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
            });
            var data = await resp.json();
            if (data.success) {
                document.getElementById('spotify-creds-form')?.classList.add('hidden');
                document.getElementById('spotify-import-form')?.classList.remove('hidden');
            } else {
                alert(data.error || 'Failed to save credentials');
            }
        } catch (e) {
            alert('Network error');
        }
        this.disabled = false;
        this.textContent = 'Save Credentials';
    });

    // Change credentials button
    document.getElementById('spotify-change-creds')?.addEventListener('click', function() {
        document.getElementById('spotify-import-form')?.classList.add('hidden');
        var credsForm = document.getElementById('spotify-creds-form');
        if (credsForm) credsForm.classList.remove('hidden');
    });

    // Import playlist
    document.getElementById('spotify-import-btn')?.addEventListener('click', async function() {
        var url = document.getElementById('spotify-playlist-url')?.value?.trim();
        if (!url) { alert('Paste a Spotify playlist URL'); return; }

        if (!url.includes('spotify.com/playlist/') && !url.startsWith('spotify:playlist:')) {
            alert('Please paste a valid Spotify playlist URL');
            return;
        }

        var statusEl = document.getElementById('spotify-import-status');
        var msgEl = document.getElementById('spotify-import-message');
        var reloadBtn = document.getElementById('spotify-reload-btn');
        if (statusEl) statusEl.classList.remove('hidden');
        if (reloadBtn) reloadBtn.classList.add('hidden');
        if (msgEl) msgEl.textContent = '⏳ Fetching songs from Spotify...';

        this.disabled = true;
        this.textContent = '⏳ Importing...';

        try {
            if (msgEl) msgEl.textContent = '⏳ Fetching songs and enriching URIs for all providers. This may take up to a minute for large playlists...';

            var resp = await fetch('/beatify/api/import-playlist', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spotify_url: url })
            });
            var data = await resp.json();
            if (data.error) {
                if (msgEl) msgEl.textContent = '❌ ' + data.error;
            } else {
                var enriched = data.enriched_count || 0;
                var total = data.song_count || 0;
                if (msgEl) msgEl.textContent = '✅ "' + data.name + '" imported — ' + total + ' songs, ' + enriched + ' with cross-platform URIs.';
                document.getElementById('spotify-playlist-url').value = '';
                if (reloadBtn) reloadBtn.classList.remove('hidden');
                // PR #549: Open editor for the newly imported playlist
                if (data.file_path) {
                    var fname = data.file_path.split('/').pop();
                    openPlaylistEditor(fname);
                }
            }
        } catch (e) {
            if (msgEl) msgEl.textContent = '❌ Network error: ' + e.message;
        }

        this.disabled = false;
        this.textContent = '📥 Import Playlist';
    });
}

/**
 * Setup game settings controls (chips for language, timer, difficulty, toggle for artist challenge)
 */
function setupGameSettings() {
    // Language chips
    document.querySelectorAll('.chip[data-lang]').forEach(chip => {
        chip.addEventListener('click', async function() {
            const lang = this.dataset.lang;
            document.querySelectorAll('.chip[data-lang]').forEach(c => c.classList.remove('chip--active'));
            this.classList.add('chip--active');
            selectedLanguage = lang;
            if (window.BeatifyI18n) {
                await BeatifyI18n.setLanguage(lang);
                BeatifyI18n.initPageTranslations();
            }
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Timer chips
    document.querySelectorAll('.chip[data-duration]').forEach(chip => {
        chip.addEventListener('click', function() {
            const duration = parseInt(this.dataset.duration, 10);
            document.querySelectorAll('.chip[data-duration]').forEach(c => c.classList.remove('chip--active'));
            this.classList.add('chip--active');
            selectedDuration = duration;
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Difficulty chips
    document.querySelectorAll('.chip[data-difficulty]').forEach(chip => {
        chip.addEventListener('click', function() {
            const difficulty = this.dataset.difficulty;
            document.querySelectorAll('.chip[data-difficulty]').forEach(c => c.classList.remove('chip--active'));
            this.classList.add('chip--active');
            selectedDifficulty = difficulty;
            updateGameSettingsSummary();
            saveGameSettings();
        });
    });

    // Artist Challenge toggle
    document.getElementById('artist-challenge-toggle')?.addEventListener('change', function() {
        artistChallengeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Intro Mode toggle (Issue #23)
    document.getElementById('intro-mode-toggle')?.addEventListener('change', function() {
        introModeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Closest Wins toggle (Issue #442)
    document.getElementById('closest-wins-toggle')?.addEventListener('change', function() {
        closestWinsModeEnabled = this.checked;
        updateGameSettingsSummary();
        saveGameSettings();
    });

    // Provider chips (Music Service)
    document.querySelectorAll('.chip[data-provider]').forEach(chip => {
        chip.addEventListener('click', function() {
            // Don't allow clicking disabled chips
            if (this.disabled || this.classList.contains('chip--disabled')) {
                return;
            }
            const provider = this.dataset.provider;
            document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
            this.classList.add('chip--active');
            selectedProvider = provider;
            updateGameSettingsSummary();
            saveGameSettings();
            // Re-render playlists to show coverage for selected provider (preserve valid selections)
            if (playlistData.length > 0) {
                renderPlaylists(playlistData, '', true);
            }
        });
    });
}

/**
 * Load saved settings from localStorage
 */
async function loadSavedSettings() {
    try {
        const saved = localStorage.getItem(STORAGE_GAME_SETTINGS);
        if (saved) {
            const settings = JSON.parse(saved);

            // Apply language
            if (settings.language) {
                selectedLanguage = settings.language;
                document.querySelectorAll('.chip[data-lang]').forEach(c => {
                    c.classList.toggle('chip--active', c.dataset.lang === settings.language);
                });
                if (window.BeatifyI18n) {
                    await BeatifyI18n.setLanguage(settings.language);
                    BeatifyI18n.initPageTranslations();
                }
            }

            // Apply timer
            if (settings.duration) {
                selectedDuration = settings.duration;
                document.querySelectorAll('.chip[data-duration]').forEach(c => {
                    c.classList.toggle('chip--active', parseInt(c.dataset.duration, 10) === settings.duration);
                });
            }

            // Apply difficulty
            if (settings.difficulty) {
                selectedDifficulty = settings.difficulty;
                document.querySelectorAll('.chip[data-difficulty]').forEach(c => {
                    c.classList.toggle('chip--active', c.dataset.difficulty === settings.difficulty);
                });
            }

            // Apply artist challenge
            if (typeof settings.artistChallenge === 'boolean') {
                artistChallengeEnabled = settings.artistChallenge;
                const toggle = document.getElementById('artist-challenge-toggle');
                if (toggle) toggle.checked = settings.artistChallenge;
            }

            // Apply intro mode (Issue #23)
            if (typeof settings.introMode === 'boolean') {
                introModeEnabled = settings.introMode;
                const introToggle = document.getElementById('intro-mode-toggle');
                if (introToggle) introToggle.checked = settings.introMode;
            }

            // Apply closest wins mode (Issue #442)
            if (typeof settings.closestWinsMode === 'boolean') {
                closestWinsModeEnabled = settings.closestWinsMode;
                const closestToggle = document.getElementById('closest-wins-toggle');
                if (closestToggle) closestToggle.checked = settings.closestWinsMode;
            }

            // Apply provider
            if (settings.provider) {
                selectedProvider = settings.provider;
                document.querySelectorAll('.chip[data-provider]').forEach(c => {
                    c.classList.toggle('chip--active', c.dataset.provider === settings.provider);
                });
            }
        }
    } catch (e) {
        console.warn('Failed to load saved settings:', e);
    }
    // Always update summary (uses current state values)
    updateGameSettingsSummary();
}

/**
 * Save game settings to localStorage
 */
function saveGameSettings() {
    try {
        const settings = {
            language: selectedLanguage,
            duration: selectedDuration,
            difficulty: selectedDifficulty,
            artistChallenge: artistChallengeEnabled,
            introMode: introModeEnabled,  // Issue #23
            closestWinsMode: closestWinsModeEnabled,  // Issue #442
            provider: selectedProvider
        };
        localStorage.setItem(STORAGE_GAME_SETTINGS, JSON.stringify(settings));
    } catch (e) {
        console.warn('Failed to save settings:', e);
    }
}

/**
 * Update the game settings summary badge
 */
function updateGameSettingsSummary() {
    const summary = document.getElementById('game-settings-summary');
    if (!summary) return;

    const difficultyLabels = { easy: 'Easy', normal: 'Normal', hard: 'Hard' };
    const langLabels = { en: 'EN', de: 'DE', es: 'ES' };
    const artistIcon = artistChallengeEnabled ? ' • 🎤' : '';
    const introIcon = introModeEnabled ? ' • ⚡' : '';  // Issue #23
    const closestIcon = closestWinsModeEnabled ? ' • 🎯' : '';  // Issue #442

    summary.textContent = `${difficultyLabels[selectedDifficulty] || 'Normal'} • ${selectedDuration}s • ${langLabels[selectedLanguage] || 'EN'}${artistIcon}${introIcon}${closestIcon}`;
}

/**
 * Update media player summary badge
 * @param {string} playerName - Friendly name of selected player
 */
function updateMediaPlayerSummary(playerName) {
    const summary = document.getElementById('media-player-summary');
    if (summary) {
        summary.textContent = playerName || 'Select...';
    }
}

/**
 * Group players by platform for organized display
 * @param {Array} players
 * @returns {Object} Grouped players by platform
 */
function groupPlayersByPlatform(players) {
    const groups = {};
    players.forEach(player => {
        const platform = player.platform || 'unknown';
        if (!groups[platform]) {
            groups[platform] = [];
        }
        groups[platform].push(player);
    });
    return groups;
}

/**
 * Render media players list grouped by platform with capability info
 * Filters out unavailable players
 * @param {Array} players
 */
function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');
    // Remove data-i18n and skeleton state when real content renders
    container?.removeAttribute('data-i18n');
    container?.removeAttribute('aria-busy');
    container?.classList.remove('skeleton-list');
    const totalPlayers = players ? players.length : 0;

    // Reset selection state
    selectedMediaPlayer = null;

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

    // Render all players with platform badges on each item
    container.innerHTML = availablePlayers.map(player => renderPlayerItem(player)).join('');
    attachPlayerSelectionHandlers();

    // Try to auto-select last used player from localStorage
    const lastPlayerId = localStorage.getItem(STORAGE_LAST_PLAYER);
    if (lastPlayerId) {
        const lastPlayerRadio = container.querySelector(`[data-entity-id="${lastPlayerId}"]`);
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
function renderPlayerItem(player) {
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
             data-supports-deezer="${player.supports_deezer}">
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
                       data-supports-deezer="${player.supports_deezer}">
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
function attachPlayerSelectionHandlers() {
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
function handleMediaPlayerSelect(radio, skipSave = false) {
    const entityId = radio.dataset.entityId;
    const state = radio.dataset.state;
    const platform = radio.dataset.platform;
    const supportsSpotify = radio.dataset.supportsSpotify === 'true';
    const supportsAppleMusic = radio.dataset.supportsAppleMusic === 'true';
    const supportsYoutubeMusic = radio.dataset.supportsYoutubeMusic === 'true';
    const supportsTidal = radio.dataset.supportsTidal === 'true';
    const supportsDeezer = radio.dataset.supportsDeezer === 'true';

    // Update module state with platform capabilities
    selectedMediaPlayer = {
        entityId,
        state,
        platform,
        supportsSpotify,
        supportsAppleMusic,
        supportsYoutubeMusic,
        supportsTidal,
        supportsDeezer,
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
    updateProviderOptions(selectedMediaPlayer);

    // Update warning message
    updateProviderWarning(selectedMediaPlayer);

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
function updateProviderOptions(player) {
    const spotifyBtn = document.querySelector('.chip[data-provider="spotify"]');
    const appleBtn = document.querySelector('.chip[data-provider="apple_music"]');
    const youtubeBtn = document.querySelector('.chip[data-provider="youtube_music"]');
    const tidalBtn = document.querySelector('.chip[data-provider="tidal"]');
    const deezerBtn = document.querySelector('.chip[data-provider="deezer"]');

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

    // If current selection is now disabled, switch to Spotify
    if (selectedProvider === 'apple_music' && !player.supportsAppleMusic) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        selectedProvider = 'spotify';
    }

    if (selectedProvider === 'youtube_music' && !player.supportsYoutubeMusic) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        selectedProvider = 'spotify';
    }

    if (selectedProvider === 'tidal' && !player.supportsTidal) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        selectedProvider = 'spotify';
    }

    if (selectedProvider === 'deezer' && !player.supportsDeezer) {
        // Update UI
        document.querySelectorAll('.chip[data-provider]').forEach(c => c.classList.remove('chip--active'));
        if (spotifyBtn) spotifyBtn.classList.add('chip--active');
        selectedProvider = 'spotify';
    }

    // Show hint for disabled providers
    const hint = document.getElementById('provider-hint');
    if (hint) {
        const disabledProviders = [];
        if (!player.supportsAppleMusic) disabledProviders.push('Apple Music');
        if (!player.supportsYoutubeMusic) disabledProviders.push('YouTube Music');
        if (!player.supportsTidal) disabledProviders.push('Tidal');
        if (!player.supportsDeezer) disabledProviders.push('Deezer');

        if (disabledProviders.length > 0) {
            hint.textContent = `${disabledProviders.join(' and ')} require${disabledProviders.length === 1 ? 's' : ''} Music Assistant speaker`;
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
function updateProviderWarning(player) {
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

/**
 * Render playlists list with checkboxes for valid playlists
 * @param {Array} playlists
 * @param {string} playlistDir
 * @param {boolean} preserveSelection - If true, preserve valid selections (used when provider changes)
 */
function renderPlaylists(playlists, playlistDir, preserveSelection = false) {
    const container = document.getElementById('playlists-list');
    // Remove data-i18n and skeleton state when real content renders
    container?.removeAttribute('data-i18n');
    container?.removeAttribute('aria-busy');
    container?.classList.remove('skeleton-list');

    // Store previous selections before reset (for preserveSelection mode)
    const previousSelections = preserveSelection ? [...selectedPlaylists] : [];

    // Reset selection state
    selectedPlaylists = [];
    playlistData = playlists || [];

    // Render filter bar (Issue #70)
    renderPlaylistFilterBar(playlistData);

    // Filter playlists based on active filters (Issue #70 - Option B)
    // Uses AND logic: playlist must match ALL selected category filters
    let filteredPlaylists = playlistData;
    if (!activeFilterTags.includes('all') && activeFilterTags.length > 0) {
        filteredPlaylists = playlistData.filter(p => {
            const playlistTags = p.tags || [];
            // Playlist must contain ALL active filter tags (AND logic)
            return activeFilterTags.every(tag => playlistTags.includes(tag));
        });
    }

    // Check if we have any valid playlists
    const hasValidPlaylists = playlistData.some(p => p.is_valid);

    if (!playlistData || playlistData.length === 0) {
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

            // Get provider count based on selected provider
            let providerCount = songCount;
            if (selectedProvider === 'spotify') {
                providerCount = spotifyCount || songCount; // fallback for legacy playlists
            } else if (selectedProvider === 'apple_music') {
                providerCount = appleMusicCount;
            } else if (selectedProvider === 'youtube_music') {
                providerCount = youtubeMusicCount;
            } else if (selectedProvider === 'tidal') {
                providerCount = tidalCount;
            } else if (selectedProvider === 'deezer') {
                providerCount = deezerCount;
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
                    <button type="button" class="playlist-edit-btn" data-path="${utils.escapeHtml(playlist.path)}"
                            style="flex-shrink: 0; background: none; border: none; cursor: pointer; font-size: 0.75rem; padding: 2px 6px; opacity: 0.6;"
                            title="Edit playlist">\u270E</button>
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

    // PR #549: Attach edit button listeners
    container.querySelectorAll('.playlist-edit-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            var path = this.dataset.path || '';
            var filename = path.split('/').pop();
            if (filename) openPlaylistEditor(filename);
        });
    });

    // Make entire row clickable (for hidden input UX)
    container.querySelectorAll('.playlist-item.is-selectable').forEach(item => {
        item.addEventListener('click', function(e) {
            // Don't double-trigger if clicking on the checkbox, label, or edit button
            if (e.target.classList.contains('playlist-checkbox') || e.target.closest('.checkbox-label') || e.target.classList.contains('playlist-edit-btn')) return;
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
                    selectedPlaylists.push({ path: prev.path, songCount: providerCount });
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

    // Initialize summary as hidden
    updateSelectionSummary();
    updateStartButtonState();
}

/**
 * Handle playlist checkbox toggle
 * @param {HTMLInputElement} checkbox
 */
function handlePlaylistToggle(checkbox) {
    const path = checkbox.dataset.path;
    // Use provider-specific count for selection tracking
    const providerCount = parseInt(checkbox.dataset.providerCount, 10) || 0;
    const item = checkbox.closest('.playlist-item');

    if (checkbox.checked) {
        // Prevent duplicate selections
        if (!selectedPlaylists.some(p => p.path === path)) {
            selectedPlaylists.push({ path, songCount: providerCount });
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
 * Render the playlist filter bar with tag buttons (Issue #70)
 * @param {Array} playlists
 */
// Tag category definitions for dropdown filters
const TAG_CATEGORIES = {
    decade: {
        label: 'Decade',
        tags: ['1960s', '1970s', '1980s', '1990s', '2000s']
    },
    style: {
        label: 'Style',
        tags: ['rock', 'pop', 'ballads', 'electronic', 'eurodance', 'yacht-rock', 'soft-rock', 'pop-punk', 'schlager', 'party', 'britpop', 'british-invasion', 'classic-rock', 'dance', 'disco', 'funk', 'hip-hop', 'latin', 'merengue', 'motown', 'r&b', 'salsa', 'soul']
    },
    region: {
        label: 'Region',
        tags: ['international', 'german', 'dutch', 'spanish']
    },
    special: {
        label: 'Special',
        tags: ['movies', 'soundtrack', 'eurovision', 'carnival', 'classics', 'contest', 'mixed', 'one-hit', 'top-hits']
    }
};

// Active filter state per category
let activeFilters = {
    decade: '',
    style: '',
    region: '',
    special: ''
};

function renderPlaylistFilterBar(playlists) {
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
        
        const currentValue = activeFilters[categoryKey] || '';
        
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
    const activeFiltersList = Object.entries(activeFilters)
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
function handleFilterDropdownChange(category, value) {
    activeFilters[category] = value;
    
    // Update activeFilterTags for compatibility with existing filter logic
    updateActiveFilterTags();
    
    // Re-render playlists with new filter
    renderPlaylists(playlistData, '', true);
}

/**
 * Update activeFilterTags array from activeFilters object
 */
function updateActiveFilterTags() {
    const selectedTags = Object.values(activeFilters).filter(v => v);
    activeFilterTags = selectedTags.length > 0 ? selectedTags : ['all'];
}

/**
 * Clear all playlist filters (Issue #70)
 */
function clearPlaylistFilters() {
    activeFilters = {
        decade: '',
        style: '',
        region: '',
        special: ''
    };
    activeFilterTags = ['all'];
    renderPlaylists(playlistData, '', true);
}

// Expose clearPlaylistFilters globally for onclick handler
window.clearPlaylistFilters = clearPlaylistFilters;

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
    _releaseWakeLock(); // #622: allow screen to sleep again

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
    // Issue #477: Hide game phase views
    document.getElementById('admin-playing-section')?.classList.add('hidden');
    document.getElementById('admin-reveal-section')?.classList.add('hidden');
    document.getElementById('admin-end-section')?.classList.add('hidden');

    // Issue #477: Close admin WS if switching to setup
    if (adminWs) {
        adminWs.close();
        adminWs = null;
    }
    isPlaying = false;
    adminPlayerName = null;
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

    // Hide existing game and end views
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

    // Render initial player list (Story 16.8)
    renderLobbyPlayers(gameData.players || []);
    // Issue #477: Use WS push when connected, REST polling as fallback
    if (!adminWs || adminWs.readyState !== WebSocket.OPEN) {
        startLobbyPolling();
    }

    // Update difficulty badge (use gameData.difficulty if available, else selectedDifficulty)
    updateLobbyDifficultyBadge(gameData.difficulty || selectedDifficulty);

    // Fix #228: Hide participate button if admin is already registered as a player.
    var participateBtn = document.getElementById('participate-btn');
    if (participateBtn) {
        var adminInPlayers = (gameData.players || []).some(function(p) { return p.is_admin; });
        var adminNameStored = null;
        try { adminNameStored = sessionStorage.getItem('beatify_admin_name'); } catch(e) {}
        if (adminInPlayers || adminNameStored || isPlaying) {
            participateBtn.classList.add('hidden');
        } else {
            participateBtn.classList.remove('hidden');
        }
    }

    // Setup QR tap-to-enlarge
    setupQRModal();
}

// ==========================================
// QR Modal Functions (tap to enlarge)
// ==========================================

/**
 * Open QR modal with enlarged code
 */
function openQRModal() {
    if (!cachedQRUrl) return;

    var modal = document.getElementById('qr-modal');
    var modalCode = document.getElementById('qr-modal-code');
    if (!modal || !modalCode) return;

    // Clear and render larger QR
    modalCode.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(modalCode, {
            text: cachedQRUrl,
            width: 280,
            height: 280,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    }

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    // Focus close button for accessibility
    var closeBtn = document.getElementById('qr-modal-close');
    if (closeBtn) closeBtn.focus();
}

/**
 * Close QR modal
 */
function closeQRModal() {
    var modal = document.getElementById('qr-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

/**
 * Setup QR modal event handlers
 */
function setupQRModal() {
    var qrContainer = document.getElementById('admin-qr-container');
    var modal = document.getElementById('qr-modal');
    var backdrop = modal ? modal.querySelector('.qr-modal-backdrop') : null;
    var closeBtn = document.getElementById('qr-modal-close');

    // QR container tap to enlarge
    if (qrContainer) {
        qrContainer.addEventListener('click', openQRModal);
        qrContainer.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openQRModal();
            }
        });
    }

    if (backdrop) {
        backdrop.addEventListener('click', closeQRModal);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', closeQRModal);
    }

    // Escape key to close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeQRModal();
        }
    });
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

    // Hide lobby and end views
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
    btn.textContent = BeatifyI18n.t('game.starting');

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
                artist_challenge_enabled: artistChallengeEnabled,  // Story 20.7
                intro_mode_enabled: introModeEnabled,  // Issue #23
                closest_wins_mode: closestWinsModeEnabled,  // Issue #442
                party_lights: window._partyLightsConfig ? window._partyLightsConfig() : null,  // Issue #331
                tts: window._ttsConfig ? window._ttsConfig() : null  // Issue #447
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

        // Issue #386 + #477: Store admin token in localStorage for persistence
        if (data.admin_token) {
            _setAdminToken(data.admin_token, data.game_id);
        }

        showLobbyView(data);
        _requestWakeLock(); // #622: keep screen on during game

        // Issue #477: Connect admin WebSocket for real-time updates
        connectAdminWebSocket();

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
 * Start gameplay from lobby — transitions LOBBY → PLAYING (Issue #228).
 * Called from the "Spiel starten" button in the lobby view.
 * Preserves admin session: admin can start the game without having to
 * re-join as a player after a rematch.
 */
async function startGameplay() {
    const btn = document.getElementById('start-gameplay-btn');
    if (!btn || btn.disabled) return;

    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="btn-icon" aria-hidden="true">⏳</span> ' + BeatifyI18n.t('game.starting');

    // Issue #477: Prefer WS for game commands
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        adminWs.send(JSON.stringify({ type: 'admin', action: 'start_game' }));
        // State update will arrive via WS broadcast — no need for loadStatus()
        return;
    }

    // Fallback to REST
    try {
        const response = await fetch('/beatify/api/start-gameplay', { method: 'POST', headers: _adminHeaders() });
        const data = await response.json();

        if (!response.ok) {
            showError(data.message || 'Failed to start gameplay');
            return;
        }

        await loadStatus();

    } catch (err) {
        showError('Network error. Please try again.');
        console.error('Start gameplay error:', err);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
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

    // Issue #477: Prefer WS for admin commands
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        adminWs.send(JSON.stringify({ type: 'admin', action: 'end_game' }));
        return;
    }

    // Issue #569: Check for valid admin token before REST fallback
    if (!_getAdminToken()) {
        showError('Admin session expired. Please reload the page.');
        return;
    }

    try {
        const response = await fetch('/beatify/api/end-game', { method: 'POST', headers: _adminHeaders() });
        if (response.ok) {
            cachedQRUrl = null;
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

// ==========================================
// Rematch Functions (Issue #108)
// ==========================================

var rematchInProgress = false;  // Debounce flag

/**
 * Show rematch confirmation modal
 */
function showRematchModal() {
    var modal = document.getElementById('rematch-modal');
    if (modal) {
        modal.classList.remove('hidden');
    }
}

/**
 * Close rematch confirmation modal
 */
function closeRematchModal() {
    var modal = document.getElementById('rematch-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

/**
 * Confirm rematch - calls API and transitions to setup
 */
async function confirmRematch() {
    if (rematchInProgress) return;  // Debounce
    rematchInProgress = true;

    // F8 fix: Show loading state on rematch button
    var rematchBtn = document.getElementById('rematch-game');
    var originalText = rematchBtn ? rematchBtn.textContent : '';
    if (rematchBtn) {
        rematchBtn.disabled = true;
        rematchBtn.textContent = '⏳';
    }

    closeRematchModal();

    // Issue #477: Prefer WS for rematch
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        adminWs.send(JSON.stringify({ type: 'admin', action: 'rematch_game' }));
        // WS broadcast will trigger lobby view transition
        rematchInProgress = false;
        return;
    }

    try {
        var response = await fetch('/beatify/api/rematch-game', { method: 'POST', headers: _adminHeaders() });
        if (response.ok) {
            var data = await response.json();
            await loadStatus();
        } else {
            var errData = await response.json();
            alert(errData.message || 'Failed to start rematch');
        }
    } catch (error) {
        console.error('Rematch failed:', error);
        alert('Failed to start rematch');
    } finally {
        rematchInProgress = false;
        // Restore button state (in case of error)
        if (rematchBtn) {
            rematchBtn.disabled = false;
            rematchBtn.textContent = originalText;
        }
    }
}

/**
 * Setup rematch modal event listeners (Issue #108)
 */
function setupRematchModal() {
    var confirmBtn = document.getElementById('rematch-confirm-btn');
    var cancelBtn = document.getElementById('rematch-cancel-btn');
    var backdrop = document.querySelector('#rematch-modal .modal-backdrop');

    confirmBtn?.addEventListener('click', confirmRematch);
    cancelBtn?.addEventListener('click', closeRematchModal);
    backdrop?.addEventListener('click', closeRematchModal);

    // Also handle Escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var rematchModal = document.getElementById('rematch-modal');
            if (rematchModal && !rematchModal.classList.contains('hidden')) {
                closeRematchModal();
            }
        }
    });
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
    // Issue #477: If already joined inline, just show a toast
    if (isPlaying && adminPlayerName) {
        showError(BeatifyI18n.t('admin.alreadyJoined') || 'Already joined as ' + adminPlayerName);
        return;
    }

    // Fix #228: If admin was already a player (sessionStorage has their name)
    // and no WS available, redirect to player page as fallback.
    if (!adminWs || adminWs.readyState !== WebSocket.OPEN) {
        var adminName = null;
        try { adminName = sessionStorage.getItem('beatify_admin_name'); } catch(e) {}
        if (adminName && currentGame && currentGame.game_id) {
            window.location.href = '/beatify/play?game=' + encodeURIComponent(currentGame.game_id);
            return;
        }
    }

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
        joinBtn.textContent = BeatifyI18n.t('admin.join');
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
    joinBtn.textContent = BeatifyI18n.t('game.joining');

    // #653: Always redirect to player page for full game experience.
    // The player page has all 18 player features + admin control bar
    // (shown automatically when isAdmin === true).
    try {
        sessionStorage.setItem('beatify_admin_name', name);
        sessionStorage.setItem('beatify_is_admin', 'true');

        const gameId = currentGame?.game_id;
        if (gameId) {
            window.location.href = '/beatify/play?game=' + encodeURIComponent(gameId);
        } else {
            showError('No active game found');
            joinBtn.disabled = false;
            joinBtn.textContent = BeatifyI18n.t('admin.join');
        }
    } catch (err) {
        console.error('Admin join failed:', err);
        joinBtn.disabled = false;
        joinBtn.textContent = BeatifyI18n.t('admin.join');
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

/**
 * Update difficulty badge in lobby view
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
function updateLobbyDifficultyBadge(difficulty) {
    var badge = document.getElementById('lobby-difficulty-badge');
    if (!badge) return;

    var labelKey = {
        easy: 'game.difficultyEasy',
        normal: 'game.difficultyNormal',
        hard: 'game.difficultyHard'
    }[difficulty] || 'game.difficultyNormal';

    var label = utils.t(labelKey);
    badge.textContent = label;
    badge.className = 'difficulty-badge difficulty-badge--' + (difficulty || 'normal');
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
    var summaryEl = document.getElementById('admin-players-summary');
    var emptyEl = document.getElementById('lobby-players-empty');
    if (!listEl) return;

    players = players || [];

    // Update player count (stat card value - just the number)
    if (countEl) {
        countEl.textContent = players.length;
    }

    // Update players section summary badge
    if (summaryEl) {
        summaryEl.textContent = players.length;
    }

    // Handle empty state visibility
    if (players.length === 0) {
        listEl.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        var startBtn = document.getElementById("start-gameplay-btn");
        if (startBtn) startBtn.classList.add("hidden");
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

    // Show Start button when there are players. The admin page IS the admin
    // control surface — the host should always be able to start the game,
    // whether they joined as a player or not.
    var startBtn = document.getElementById("start-gameplay-btn");
    if (startBtn) {
        startBtn.classList.remove("hidden");
    }

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
// Playlist Requests (Story 44)
// ============================================

/**
 * Setup event handlers for playlist request modal
 */
function setupPlaylistRequests() {
    const requestModal = document.getElementById('request-modal');
    const successModal = document.getElementById('request-success-modal');
    const urlInput = document.getElementById('spotify-url-input');
    const urlError = document.getElementById('spotify-url-error');
    const submitBtn = document.getElementById('request-submit-btn');

    // Open request modal from button
    document.getElementById('request-playlist-btn')?.addEventListener('click', () => {
        if (requestModal) {
            requestModal.classList.remove('hidden');
            urlInput?.focus();
        }
    });

    // Close request modal
    document.getElementById('request-cancel-btn')?.addEventListener('click', () => {
        closeRequestModal();
    });

    // Close on backdrop click
    requestModal?.querySelector('.modal-backdrop')?.addEventListener('click', () => {
        closeRequestModal();
    });

    // URL input validation
    urlInput?.addEventListener('input', () => {
        const url = urlInput.value.trim();
        const isValid = window.PlaylistRequests?.isValidSpotifyUrl(url);

        if (url && !isValid) {
            urlInput.classList.add('input-error');
            urlError?.classList.remove('hidden');
        } else {
            urlInput.classList.remove('input-error');
            urlError?.classList.add('hidden');
        }

        if (submitBtn) {
            submitBtn.disabled = !isValid;
        }
    });

    // Submit request
    submitBtn?.addEventListener('click', async () => {
        const url = urlInput?.value.trim();
        if (!url || !window.PlaylistRequests?.isValidSpotifyUrl(url)) return;

        // Show loading state
        submitBtn.classList.add('btn--loading');
        submitBtn.disabled = true;

        try {
            const result = await window.PlaylistRequests.submitRequest(url);

            // Close request modal
            closeRequestModal();

            // Show success modal
            const successName = document.getElementById('request-success-name');
            if (successName) {
                successName.textContent = result.playlist_name;
            }
            successModal?.classList.remove('hidden');

            // Refresh the requests list
            await renderRequestsList();

        } catch (error) {
            console.error('Failed to submit request:', error);
            urlInput?.classList.add('input-error');
            if (urlError) {
                urlError.textContent = error.message || 'Failed to submit request';
                urlError.classList.remove('hidden');
            }
        } finally {
            submitBtn.classList.remove('btn--loading');
            // Re-enable based on input validity
            const isValid = window.PlaylistRequests?.isValidSpotifyUrl(urlInput?.value.trim() || '');
            submitBtn.disabled = !isValid;
        }
    });

    // Close success modal
    document.getElementById('request-success-close-btn')?.addEventListener('click', () => {
        successModal?.classList.add('hidden');
    });

    successModal?.querySelector('.modal-backdrop')?.addEventListener('click', () => {
        successModal?.classList.add('hidden');
    });

    function closeRequestModal() {
        requestModal?.classList.add('hidden');
        if (urlInput) {
            urlInput.value = '';
            urlInput.classList.remove('input-error');
        }
        urlError?.classList.add('hidden');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.classList.remove('btn--loading');
        }
    }
}

/**
 * Initialize playlist requests display and polling
 */
async function initPlaylistRequests() {
    // Render existing requests (loads from backend)
    await renderRequestsList();

    // Poll for status updates (Story 44.4)
    if (window.PlaylistRequests) {
        try {
            const changed = await window.PlaylistRequests.pollStatuses();
            if (changed) {
                await renderRequestsList();
            }
        } catch (e) {
            console.error('Failed to poll request statuses:', e);
        }
    }
}

/**
 * Render the list of playlist requests
 */
async function renderRequestsList() {
    const section = document.getElementById('my-requests');
    const listContainer = document.getElementById('my-requests-list');
    const emptyState = document.getElementById('my-requests-empty');
    const summary = document.getElementById('my-requests-summary');

    if (!window.PlaylistRequests) {
        section?.classList.add('hidden');
        return;
    }

    // Only show section in setup view (not during active/existing game)
    if (currentView === 'setup') {
        section?.classList.remove('hidden');
    }

    // Load requests from backend (async)
    const requests = await window.PlaylistRequests.getRequestsForDisplayAsync();

    // Update summary badge
    if (summary) {
        summary.textContent = requests.length.toString();
    }

    // Render list or empty state
    if (requests.length === 0) {
        listContainer.innerHTML = '';
        emptyState?.classList.remove('hidden');
    } else {
        emptyState?.classList.add('hidden');
        listContainer.innerHTML = requests.map(request => {
            const statusClass = `request-status--${request.status}`;
            const statusLabels = {
                pending: '⏳ Pending',
                ready: '✅ Ready',
                installed: '✓ Installed',
                declined: '❌ Declined'
            };
            const statusLabel = statusLabels[request.status] || request.status;

            const thumbnail = request.thumbnail_url
                ? `<img class="request-item-thumbnail" src="${request.thumbnail_url}" alt="">`
                : `<div class="request-item-thumbnail-placeholder">🎵</div>`;

            let actionButton = '';
            if (request.status === 'ready' && request.update_available) {
                actionButton = `<a href="https://github.com/mholzi/beatify/releases" target="_blank"
                    class="btn btn-primary request-update-btn">Update to v${request.release_version}</a>`;
            }

            return `
                <div class="request-item">
                    ${thumbnail}
                    <div class="request-item-info">
                        <div class="request-item-name">${escapeHtml(request.playlist_name)}</div>
                        <div class="request-item-meta">${request.relative_time}</div>
                    </div>
                    <span class="request-status ${statusClass}">${statusLabel}</span>
                    ${actionButton}
                </div>
            `;
        }).join('');
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// PWA Install Button (#226)
// ============================================

/**
 * Explicit PWA install prompt — shows 📲 button in admin header.
 * Android: captures beforeinstallprompt → native install dialog.
 * iOS Safari: shows manual "Add to Home Screen" hint.
 * Hidden when already installed (standalone mode).
 */
(function initPwaInstall() {
    const btn = document.getElementById('pwa-install-btn');
    const iosHint = document.getElementById('pwa-ios-hint');
    const iosClose = document.getElementById('pwa-ios-hint-close');
    if (!btn) return;

    // Already installed — stay hidden
    if (window.matchMedia('(display-mode: standalone)').matches ||
        window.navigator.standalone === true) {
        return;
    }

    let deferredPrompt = null;

    // Android / Chrome: capture the install prompt
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        btn.classList.remove('hidden');
    });

    // Hide after successful install
    window.addEventListener('appinstalled', () => {
        btn.classList.add('hidden');
        deferredPrompt = null;
        if (iosHint) iosHint.classList.add('hidden');
    });

    // iOS Safari detection — show button for manual instructions
    const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
    const isSafari = /safari/i.test(navigator.userAgent) && !/chrome|crios|fxios/i.test(navigator.userAgent);
    if (isIos && isSafari) {
        btn.classList.remove('hidden');
    }

    btn.addEventListener('click', async () => {
        if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            console.log('[PWA] Install outcome:', outcome);
            deferredPrompt = null;
            if (outcome === 'accepted') {
                btn.classList.add('hidden');
            }
        } else if (isIos && iosHint) {
            iosHint.classList.remove('hidden');
        }
    });

    // Close iOS hint
    if (iosClose && iosHint) {
        iosClose.addEventListener('click', () => {
            iosHint.classList.add('hidden');
        });
    }
})();

// ============================================
// Issue #477: Admin WebSocket + Game Phase Views
// ============================================

/**
 * Connect admin WebSocket for real-time game state updates.
 * Authenticates via admin_connect with the stored admin token.
 */
function connectAdminWebSocket() {
    var token = _getAdminToken();
    if (!token) return;

    // Close existing connection if any
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        return; // Already connected
    }

    var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + window.location.host + '/beatify/ws';

    try {
        adminWs = new WebSocket(wsUrl);
    } catch (err) {
        console.error('[Admin WS] Failed to create WebSocket:', err);
        return;
    }

    adminWs.onopen = function() {
        console.log('[Admin WS] Connected, sending admin_connect');
        adminReconnectAttempts = 0;
        adminWs.send(JSON.stringify({
            type: 'admin_connect',
            admin_token: token
        }));
    };

    adminWs.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            handleAdminWsMessage(data);
        } catch (err) {
            console.error('[Admin WS] Message parse error:', err);
        }
    };

    adminWs.onclose = function() {
        console.log('[Admin WS] Disconnected');
        adminWs = null;
        // Issue #550: Re-enable lobby polling while WS is down so
        // spectator admin still sees player join/leave updates
        if (currentView === 'lobby') {
            startLobbyPolling();
        }
        // Auto-reconnect with backoff
        if (adminReconnectAttempts < MAX_ADMIN_RECONNECT && currentGame) {
            adminReconnectAttempts++;
            var delay = Math.min(1000 * Math.pow(2, adminReconnectAttempts - 1), 30000);
            setTimeout(connectAdminWebSocket, delay);
        }
    };

    adminWs.onerror = function(err) {
        console.error('[Admin WS] Error:', err);
    };
}

/**
 * Route incoming WebSocket messages.
 */
function handleAdminWsMessage(data) {
    switch (data.type) {
        case 'admin_connect_ack':
            console.log('[Admin WS] Authenticated, game_id:', data.game_id);
            // Stop REST polling — WS pushes are active
            stopLobbyPolling();
            break;

        case 'state':
            handleAdminStateUpdate(data);
            break;

        case 'join_ack':
            // Admin successfully joined as player
            isPlaying = true;
            if (data.session_id) {
                document.cookie = 'beatify_session=' + data.session_id +
                    ';path=/;max-age=86400;SameSite=Strict';
            }
            // Hide "Join as Player" button since admin is now a player
            document.getElementById('participate-btn')?.classList.add('hidden');
            console.log('[Admin WS] Joined as player:', adminPlayerName);
            break;

        case 'metadata_update':
            // Update album art when metadata arrives after round start
            if (data.song) {
                var artEl = document.getElementById('admin-album-art');
                if (artEl && data.song.album_art) artEl.src = data.song.album_art;
            }
            break;

        case 'admin_token_update':
            // Issue #535: Update admin token after rematch (new game_id + token)
            _setAdminToken(data.admin_token, data.game_id);
            console.log('[Admin WS] Admin token updated for game:', data.game_id);
            break;

        case 'error':
            console.error('[Admin WS] Error:', data.code, data.message);
            if (data.code === 'UNAUTHORIZED') {
                adminWs?.close();
            } else if (data.code === 'NAME_TAKEN' || data.code === 'NAME_INVALID') {
                showError(data.message);
                isPlaying = false;
                adminPlayerName = null;
                var joinBtn = document.getElementById('admin-join-btn');
                if (joinBtn) {
                    joinBtn.disabled = false;
                    joinBtn.textContent = BeatifyI18n.t('admin.join');
                }
            }
            break;

        default:
            // Ignore other message types (player_reaction, song_stopped, etc.)
            break;
    }
}

/**
 * Handle game state update from WebSocket — route to correct phase view.
 */
function handleAdminStateUpdate(data) {
    currentGame = data;

    // Restore isPlaying state from player list (survives page reload)
    if (data.players && !isPlaying) {
        var adminInList = data.players.find(function(p) { return p.is_admin; });
        if (adminInList) {
            isPlaying = true;
            adminPlayerName = adminPlayerName || adminInList.name;
            try { sessionStorage.setItem('beatify_admin_name', adminInList.name); } catch(e) {}
        }
    }

    // #647: Wake lock for all active game phases
    if (['LOBBY', 'PLAYING', 'REVEAL', 'PAUSED'].includes(data.phase)) {
        _requestWakeLock();
    } else {
        _releaseWakeLock();
    }

    // Hide all phase sections first
    var sections = ['setup-container', 'lobby-section', 'existing-game-section',
                    'admin-playing-section', 'admin-reveal-section', 'admin-end-section'];
    sections.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // Also hide setup sections
    setupSections.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.classList.add('hidden');
    });

    // #651: Hide start button and validation messages (outside setupSections)
    document.getElementById('start-game')?.classList.add('hidden');
    document.getElementById('playlist-validation-msg')?.classList.add('hidden');
    document.getElementById('media-player-validation-msg')?.classList.add('hidden');

    switch (data.phase) {
        case 'LOBBY':
            showLobbyView(data);
            break;
        case 'PLAYING':
            showAdminPlayingView(data);
            break;
        case 'REVEAL':
            showAdminRevealView(data);
            break;
        case 'END':
            showAdminEndView(data);
            break;
        case 'PAUSED':
            showAdminPausedView(data);
            break;
        default:
            showSetupView();
    }
}

// ---- PLAYING phase view (#653: mirrors player layout) ----

function showAdminPlayingView(data) {
    var section = document.getElementById('admin-playing-section');
    if (!section) return;
    section.classList.remove('hidden');

    // Round info (player-style separate spans)
    var roundEl = document.getElementById('admin-current-round');
    var totalEl = document.getElementById('admin-total-rounds');
    if (roundEl) roundEl.textContent = data.round || '?';
    if (totalEl) totalEl.textContent = data.total_rounds || '?';

    // Difficulty badge
    var diffBadge = document.getElementById('admin-game-difficulty-badge');
    if (diffBadge && data.difficulty) {
        diffBadge.textContent = data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1);
    }

    // Album cover (large centered)
    var artEl = document.getElementById('admin-album-art');
    if (artEl && data.song && data.song.album_art) artEl.src = data.song.album_art;

    // Admin-only song details (year, fun fact)
    if (data.admin_song) {
        var yearEl = document.getElementById('admin-song-year');
        var factEl = document.getElementById('admin-song-funfact');
        if (yearEl) {
            if (data.admin_song.year) {
                yearEl.textContent = '📅 ' + data.admin_song.year;
                yearEl.classList.remove('hidden');
            } else { yearEl.classList.add('hidden'); }
        }
        if (factEl) {
            var lang = BeatifyI18n.getLanguage();
            var fact = (lang !== 'en' && data.admin_song['fun_fact_' + lang])
                ? data.admin_song['fun_fact_' + lang] : data.admin_song.fun_fact;
            if (fact) {
                factEl.textContent = '💡 ' + fact;
                factEl.classList.remove('hidden');
            } else { factEl.classList.add('hidden'); }
        }
    }

    // Countdown timer (big centered, player style)
    startAdminCountdown(data.deadline);

    // Submission tracker (player dot format)
    renderAdminSubmissionDots(data.players);

    // Banners
    var lastBanner = document.getElementById('admin-last-round');
    if (lastBanner) lastBanner.classList.toggle('hidden', !data.last_round);
    var introBadge = document.getElementById('admin-intro-badge');
    if (introBadge) introBadge.classList.toggle('hidden', !data.is_intro_round);
    var closestBadge = document.getElementById('admin-closest-wins-badge');
    if (closestBadge) closestBadge.classList.toggle('hidden', !data.closest_wins_mode);

    // Intro splash overlay with confirm button
    var introSplash = document.getElementById('admin-intro-splash');
    if (introSplash) introSplash.classList.toggle('hidden', !data.intro_splash_pending);

    // Artist challenge (read-only options)
    var artistSection = document.getElementById('admin-artist-challenge');
    if (artistSection) {
        if (data.artist_challenge) {
            artistSection.classList.remove('hidden');
            renderAdminChallengeOptions('admin-artist-options', data.artist_challenge.options);
        } else { artistSection.classList.add('hidden'); }
    }

    // Movie challenge (read-only options)
    var movieSection = document.getElementById('admin-movie-challenge');
    if (movieSection) {
        if (data.movie_challenge) {
            movieSection.classList.remove('hidden');
            renderAdminChallengeOptions('admin-movie-options', data.movie_challenge.options);
        } else { movieSection.classList.add('hidden'); }
    }

    // Leaderboard (player-style entries)
    renderAdminLeaderboard(data.leaderboard);
}

/**
 * Render player-style submission dots (matches player-game.js renderSubmissionTracker).
 */
function renderAdminSubmissionDots(players) {
    var container = document.getElementById('admin-submitted-players');
    if (!container || !players) return;

    container.innerHTML = players.map(function(p) {
        var initials = (p.name || '?').split(/\s+/).map(function(w) { return w[0]; }).join('').substring(0, 2).toUpperCase();
        var classes = [
            'player-indicator',
            p.submitted ? 'is-submitted' : '',
            p.connected === false ? 'player-indicator--disconnected' : ''
        ].filter(Boolean).join(' ');
        var badges = '';
        if (p.steal_used) badges += '<span class="player-badge player-badge--steal">🥷</span>';
        if (p.bet) badges += '<span class="player-badge player-badge--bet">🎲</span>';
        return '<div class="' + classes + '">' + badges +
            '<div class="player-avatar"><span class="player-initials">' + utils.escapeHtml(initials) + '</span></div>' +
            '<span class="player-name">' + utils.escapeHtml(p.name) + '</span></div>';
    }).join('');
}

function startAdminCountdown(deadline) {
    if (countdownInterval) clearInterval(countdownInterval);

    var timerEl = document.getElementById('admin-timer');
    if (!timerEl || !deadline) return;

    function tick() {
        var now = Date.now();
        var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));
        timerEl.textContent = remaining;
        // Use player CSS classes for timer states
        timerEl.classList.toggle('timer--warning', remaining <= 10);
        timerEl.classList.toggle('timer--critical', remaining <= 5);
        if (remaining <= 0) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
    }

    tick();
    countdownInterval = setInterval(tick, 1000);
}

// ---- REVEAL phase view (#653: mirrors player layout) ----

function showAdminRevealView(data) {
    var section = document.getElementById('admin-reveal-section');
    if (!section) return;
    section.classList.remove('hidden');

    // Round info
    var roundEl = document.getElementById('admin-reveal-round');
    var totalEl = document.getElementById('admin-reveal-total');
    if (roundEl) roundEl.textContent = data.round || '?';
    if (totalEl) totalEl.textContent = data.total_rounds || '?';

    // Song hero
    if (data.song) {
        var titleEl = document.getElementById('admin-reveal-song-title');
        var artistEl = document.getElementById('admin-reveal-song-artist');
        var yearEl = document.getElementById('admin-reveal-correct-year');
        var artEl = document.getElementById('admin-reveal-album-art');
        if (titleEl) titleEl.textContent = data.song.title || '';
        if (artistEl) artistEl.textContent = data.song.artist || '';
        if (yearEl) yearEl.textContent = data.song.year || '';
        if (artEl && data.song.album_art) artEl.src = data.song.album_art;
    }

    // Difficulty badge
    var diffBadge = document.getElementById('admin-reveal-difficulty-badge');
    if (diffBadge && data.difficulty) {
        diffBadge.textContent = data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1);
    }

    // Fun fact
    var funFactContainer = document.getElementById('admin-fun-fact-container');
    var funFactText = document.getElementById('admin-fun-fact-text');
    if (funFactContainer && data.song) {
        var lang = BeatifyI18n.getLanguage();
        var fact = (lang !== 'en' && data.song['fun_fact_' + lang])
            ? data.song['fun_fact_' + lang] : data.song.fun_fact;
        if (fact) {
            funFactText.textContent = fact;
            funFactContainer.classList.remove('hidden');
        } else {
            funFactContainer.classList.add('hidden');
        }
    }

    // Artist challenge reveal
    var artistReveal = document.getElementById('admin-artist-reveal-section');
    if (artistReveal) {
        if (data.artist_challenge && data.artist_challenge.correct_answer) {
            document.getElementById('admin-artist-reveal-name').textContent = data.artist_challenge.correct_answer;
            artistReveal.classList.remove('hidden');
        } else {
            artistReveal.classList.add('hidden');
        }
    }

    // Movie challenge reveal
    var movieReveal = document.getElementById('admin-movie-reveal-section');
    if (movieReveal) {
        if (data.movie_challenge && data.movie_challenge.correct_answer) {
            document.getElementById('admin-movie-reveal-name').textContent = data.movie_challenge.correct_answer;
            movieReveal.classList.remove('hidden');
        } else {
            movieReveal.classList.add('hidden');
        }
    }

    // All guesses grid (player-style result cards)
    renderAdminResultCards(data.players, data.closest_wins_mode, data.song ? data.song.year : null);

    // Leaderboard (player-style entries)
    renderAdminLeaderboard(data.leaderboard);
}

/**
 * Render player-style leaderboard entries (matches player-utils.js renderLeaderboardEntry).
 */
function renderAdminLeaderboard(leaderboard, containerId) {
    var targets = containerId ? [containerId] : ['admin-playing-leaderboard-list', 'admin-reveal-leaderboard'];
    if (!leaderboard) return;

    var html = '';
    leaderboard.forEach(function(entry) {
        var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
        var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
        var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';
        var streakIndicator = '';
        if (entry.streak >= 2) {
            var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
            streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
        }
        var changeIndicator = '';
        if (entry.rank_change > 0) changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
        else if (entry.rank_change < 0) changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';

        html += '<div class="leaderboard-entry ' + rankClass + ' ' + disconnectedClass + '">' +
            '<span class="entry-rank">#' + entry.rank + '</span>' +
            '<span class="entry-name">' + utils.escapeHtml(entry.name) + awayBadge + '</span>' +
            '<span class="entry-meta">' + streakIndicator + changeIndicator + '</span>' +
            '<span class="entry-score">' + entry.score + '</span>' +
        '</div>';
    });

    targets.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = html;
    });

    // Update summary badges
    if (leaderboard.length > 0) {
        ['admin-playing-leaderboard-summary', 'admin-reveal-leaderboard-summary'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.textContent = leaderboard[0].name + ' — ' + leaderboard[0].score;
        });
    }
}

/**
 * Render player-style result cards for reveal (matches player-reveal.js renderPlayerResultCards).
 */
function renderAdminResultCards(players, closestWinsMode, correctYear) {
    var container = document.getElementById('admin-reveal-guesses');
    if (!container) return;
    if (!players || players.length === 0) { container.innerHTML = ''; return; }

    var bestDiff = null;
    if (closestWinsMode) {
        players.forEach(function(p) {
            if (!p.missed_round && p.years_off != null) {
                if (bestDiff === null || p.years_off < bestDiff) bestDiff = p.years_off;
            }
        });
    }

    var sorted = players.slice().sort(function(a, b) { return (b.round_score || 0) - (a.round_score || 0); });
    var html = '<div class="results-cards-scroll">';

    sorted.forEach(function(p) {
        var isMissed = p.missed_round === true;
        var yearsOff = p.years_off || 0;
        var roundScore = p.round_score || 0;
        var scoreClass = isMissed ? 'is-score-zero' : roundScore >= 10 ? 'is-score-high' : roundScore >= 1 ? 'is-score-medium' : 'is-score-zero';
        var isClosest = closestWinsMode && !isMissed && bestDiff !== null && yearsOff === bestDiff;
        var closestClass = isClosest ? ' is-closest-winner' : '';
        var guessDisplay = isMissed ? '—' : (p.guess || 'n/a');
        var yearsOffDisplay = isMissed ? BeatifyI18n.t('reveal.noGuessShort') || 'Missed' :
            yearsOff === 0 ? BeatifyI18n.t('reveal.exact') || 'Exact!' :
            (BeatifyI18n.t('reveal.shortOff', { years: yearsOff }) || yearsOff + ' off');
        var betIndicator = p.bet ? '<span class="card-bet">🎲</span>' : '';
        var closestBadge = isClosest ? '<span class="closest-winner-badge">🎯</span>' : '';
        var artistBadge = p.artist_bonus > 0 ? '<span class="player-card-artist-badge">🎤 +' + p.artist_bonus + '</span>' : '';

        html += '<div class="result-card ' + scoreClass + closestClass + '">' +
            '<div class="card-name">' + utils.escapeHtml(p.name) + betIndicator + closestBadge + '</div>' +
            '<div class="card-guess">' + guessDisplay + '</div>' +
            '<div class="card-accuracy">' + yearsOffDisplay + '</div>' +
            '<div class="card-score">+' + roundScore + artistBadge + '</div>' +
        '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
}

/**
 * Render read-only challenge options (artist/movie) for admin spectator view.
 */
function renderAdminChallengeOptions(containerId, options) {
    var container = document.getElementById(containerId);
    if (!container || !options) return;

    container.innerHTML = options.map(function(opt) {
        var label = typeof opt === 'string' ? opt : (opt.label || opt.name || opt);
        return '<div class="artist-option artist-option--readonly">' +
            utils.escapeHtml(label) + '</div>';
    }).join('');
}

// ---- END phase view ----

function showAdminEndView(data) {
    var section = document.getElementById('admin-end-section');
    if (!section) return;
    section.classList.remove('hidden');

    // Winner
    var winnerEl = document.getElementById('admin-end-winner');
    if (winnerEl && data.winner) {
        winnerEl.innerHTML = '<span class="winner-trophy">🏆</span> ' +
            utils.escapeHtml(data.winner.name) + ' — ' + data.winner.score + ' pts';
    }

    // Final leaderboard (player-style entries)
    if (data.leaderboard) {
        renderAdminLeaderboard(data.leaderboard, 'admin-end-leaderboard');
    }

    // Clean up game state for admin
    isPlaying = false;
    adminPlayerName = null;
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}

// ---- PAUSED phase view ----

function showAdminPausedView(data) {
    // Reuse the playing section but show pause overlay
    var section = document.getElementById('admin-playing-section');
    if (!section) return;
    section.classList.remove('hidden');

    var timerEl = document.getElementById('admin-timer');
    if (timerEl) timerEl.textContent = '⏸ ' + (BeatifyI18n.t('game.paused') || 'Paused');
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}

// ---- Admin game controls (sent via WS) ----

/**
 * #648: Send an admin WS command with feedback when disconnected.
 * Shows error + triggers reconnect if WS is down.
 */
function sendAdminCommand(payload) {
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        adminWs.send(JSON.stringify(payload));
        return true;
    }
    showError(BeatifyI18n.t('admin.connectionLost') || 'Connection lost — reconnecting...');
    adminReconnectAttempts = 0;
    connectAdminWebSocket();
    return false;
}

function adminNextRound() {
    sendAdminCommand({ type: 'admin', action: 'next_round' });
}

function adminStopSong() {
    sendAdminCommand({ type: 'admin', action: 'stop_song' });
}

function adminSeekForward() {
    sendAdminCommand({ type: 'admin', action: 'seek_forward', seconds: 10 });
}

function adminVolumeUp() {
    sendAdminCommand({ type: 'admin', action: 'set_volume', direction: 'up' });
}

function adminVolumeDown() {
    sendAdminCommand({ type: 'admin', action: 'set_volume', direction: 'down' });
}

function adminDismissGame() {
    if (adminWs && adminWs.readyState === WebSocket.OPEN) {
        adminWs.send(JSON.stringify({ type: 'admin', action: 'dismiss_game' }));
    }
    cachedQRUrl = null;
    isPlaying = false;
    adminPlayerName = null;
    showSetupView();
}


// ==========================================
// Playlist Editor (PR #549)
// ==========================================

/** Current editor state */
let editorSongs = [];
let editorFilename = '';
let editorSearchTimeout = null;

/**
 * Show the playlist editor populated with data
 * @param {Object} playlistData - { name, tags, songs }
 * @param {string} filename - e.g. "gen-z-anthems.json" or full path
 */
function showPlaylistEditor(playlistData, filename) {
    // Extract just the filename from a full path
    if (filename.includes('/')) {
        filename = filename.split('/').pop();
    }
    editorFilename = filename;
    editorSongs = (playlistData.songs || []).slice(); // shallow copy

    var editor = document.getElementById('playlist-editor');
    if (!editor) return;

    // Expand the import section if collapsed
    var importSection = document.getElementById('import-playlist');
    if (importSection && importSection.classList.contains('collapsed')) {
        importSection.classList.remove('collapsed');
        var header = importSection.querySelector('.section-header-collapsible');
        if (header) header.setAttribute('aria-expanded', 'true');
    }

    editor.classList.remove('hidden');

    document.getElementById('editor-playlist-name').value = playlistData.name || '';
    document.getElementById('editor-playlist-tags').value = (playlistData.tags || []).join(', ');

    renderEditorSongList();
    setupEditorListeners();
}

/**
 * Render the song list in the editor
 */
function renderEditorSongList() {
    var container = document.getElementById('editor-song-list');
    if (!container) return;

    if (editorSongs.length === 0) {
        container.innerHTML = '<p class="setting-hint">No songs yet. Use search to add songs.</p>';
        return;
    }

    container.innerHTML = editorSongs.map(function(song, idx) {
        var sp = song.uri ? '\u2713SP' : '\u2717SP';
        var yt = song.uri_youtube_music ? '\u2713YT' : '\u2717YT';
        var am = song.uri_apple_music ? '\u2713AM' : '\u2717AM';
        var ti = song.uri_tidal ? '\u2713TI' : '\u2717TI';
        var dz = song.uri_deezer ? '\u2713DZ' : '\u2717DZ';

        var spClass = song.uri ? 'color: #1DB954' : 'color: #666';
        var ytClass = song.uri_youtube_music ? 'color: #FF0000' : 'color: #666';
        var amClass = song.uri_apple_music ? 'color: #FA243C' : 'color: #666';
        var tiClass = song.uri_tidal ? 'color: #000' : 'color: #666';
        var dzClass = song.uri_deezer ? 'color: #A238FF' : 'color: #666';

        var artist = utils.escapeHtml(song.artist || '');
        var title = utils.escapeHtml(song.title || '');
        var year = song.year || '';

        return '<div class="list-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; gap: 8px; font-size: 0.85rem;">' +
            '<span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' +
                '\uD83C\uDFB5 ' + artist + ' - ' + title + (year ? ' (' + year + ')' : '') +
            '</span>' +
            '<span style="flex-shrink: 0; font-size: 0.7rem; white-space: nowrap;">' +
                '<span style="' + spClass + '">' + sp + '</span> ' +
                '<span style="' + ytClass + '">' + yt + '</span> ' +
                '<span style="' + amClass + '">' + am + '</span> ' +
                '<span style="' + tiClass + '">' + ti + '</span> ' +
                '<span style="' + dzClass + '">' + dz + '</span>' +
            '</span>' +
            '<button type="button" class="editor-remove-btn" data-index="' + idx + '" ' +
                'style="flex-shrink: 0; background: none; border: none; cursor: pointer; font-size: 1rem; padding: 2px 6px; color: var(--color-danger, #e74c3c);" ' +
                'title="Remove song">\u2715</button>' +
        '</div>';
    }).join('');

    // Attach remove handlers
    container.querySelectorAll('.editor-remove-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var idx = parseInt(this.dataset.index, 10);
            editorSongs.splice(idx, 1);
            renderEditorSongList();
        });
    });
}

/** Track whether editor listeners have been attached */
let editorListenersAttached = false;

/**
 * Setup editor event listeners (search + save)
 */
function setupEditorListeners() {
    if (editorListenersAttached) return;
    editorListenersAttached = true;

    // Debounced search
    var searchInput = document.getElementById('editor-search');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            clearTimeout(editorSearchTimeout);
            var q = this.value.trim();
            if (q.length < 2) {
                document.getElementById('editor-search-results').innerHTML = '';
                return;
            }
            editorSearchTimeout = setTimeout(function() {
                editorSearchSongs(q);
            }, 300);
        });
    }

    // Save button
    var saveBtn = document.getElementById('editor-save-btn');
    if (saveBtn) {
        saveBtn.addEventListener('click', async function() {
            var name = document.getElementById('editor-playlist-name')?.value?.trim();
            var tagsStr = document.getElementById('editor-playlist-tags')?.value?.trim();
            var tags = tagsStr ? tagsStr.split(',').map(function(t) { return t.trim(); }).filter(Boolean) : [];

            if (!name) { alert('Playlist name is required'); return; }

            saveBtn.disabled = true;
            saveBtn.textContent = '\u23F3 Saving...';

            try {
                var resp = await fetch('/beatify/api/edit-playlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file: editorFilename,
                        name: name,
                        tags: tags,
                        songs: editorSongs,
                    })
                });
                var data = await resp.json();
                if (data.success) {
                    saveBtn.textContent = '\u2713 Saved!';
                    setTimeout(function() { saveBtn.textContent = 'Save Playlist'; }, 2000);
                } else {
                    alert(data.error || 'Save failed');
                    saveBtn.textContent = 'Save Playlist';
                }
            } catch (e) {
                alert('Network error: ' + e.message);
                saveBtn.textContent = 'Save Playlist';
            }
            saveBtn.disabled = false;
        });
    }
}

/**
 * Search Spotify for songs to add
 * @param {string} query
 */
async function editorSearchSongs(query) {
    var resultsEl = document.getElementById('editor-search-results');
    if (!resultsEl) return;

    resultsEl.innerHTML = '<p class="setting-hint">\u23F3 Searching...</p>';

    try {
        var resp = await fetch('/beatify/api/spotify-search?q=' + encodeURIComponent(query));
        var data = await resp.json();

        if (data.error) {
            resultsEl.innerHTML = '<p class="setting-hint">\u274C ' + utils.escapeHtml(data.error) + '</p>';
            return;
        }

        var results = data.results || [];
        if (results.length === 0) {
            resultsEl.innerHTML = '<p class="setting-hint">No results found.</p>';
            return;
        }

        resultsEl.innerHTML = results.map(function(r, idx) {
            var artist = utils.escapeHtml(r.artist || '');
            var title = utils.escapeHtml(r.title || '');
            var year = r.year || '';
            return '<div class="list-item" style="display: flex; align-items: center; justify-content: space-between; padding: 6px 8px; gap: 8px; font-size: 0.85rem;">' +
                '<span style="flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">' +
                    artist + ' - ' + title + (year ? ' (' + year + ')' : '') +
                '</span>' +
                '<button type="button" class="editor-add-btn" data-search-index="' + idx + '" ' +
                    'style="flex-shrink: 0; background: none; border: none; cursor: pointer; font-size: 1.1rem; padding: 2px 6px; color: var(--color-primary, #1DB954);" ' +
                    'title="Add song">+</button>' +
            '</div>';
        }).join('');

        // Attach add handlers
        resultsEl.querySelectorAll('.editor-add-btn').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var idx = parseInt(this.dataset.searchIndex, 10);
                var song = results[idx];
                if (!song) return;

                this.disabled = true;
                this.textContent = '\u23F3';

                // Enrich via Odesli through import endpoint isn't available directly,
                // so we add the song with Spotify URI and attempt enrichment via Odesli client-side
                var enriched = {
                    title: song.title,
                    artist: song.artist,
                    year: song.year,
                    uri: song.uri,
                    uri_youtube_music: '',
                    uri_apple_music: '',
                    uri_tidal: '',
                    uri_deezer: '',
                    alt_artists: [],
                    fun_fact: '',
                    fun_fact_de: '',
                    fun_fact_es: '',
                    fun_fact_fr: '',
                    fun_fact_nl: '',
                };

                // Try Odesli enrichment
                try {
                    var odesliResp = await fetch('https://api.song.link/v1-alpha.1/links?url=' + encodeURIComponent(song.uri) + '&userCountry=US');
                    if (odesliResp.ok) {
                        var odesliData = await odesliResp.json();
                        var links = odesliData.linksByPlatform || {};

                        if (links.youtubeMusic) enriched.uri_youtube_music = links.youtubeMusic.url || '';

                        // Apple Music: extract numeric ID
                        var appleUrl = (links.appleMusic || {}).url || '';
                        if (appleUrl) {
                            var appleMatch = appleUrl.match(/\/(\d+)(?:\?|$)/);
                            if (appleMatch) enriched.uri_apple_music = 'applemusic://track/' + appleMatch[1];
                        }

                        // Tidal
                        var tidalUrl = (links.tidal || {}).url || '';
                        if (tidalUrl) {
                            var tidalMatch = tidalUrl.match(/\/track\/(\d+)/);
                            if (tidalMatch) enriched.uri_tidal = 'tidal://track/' + tidalMatch[1];
                        }

                        // Deezer
                        var deezerUrl = (links.deezer || {}).url || '';
                        if (deezerUrl) {
                            var deezerMatch = deezerUrl.match(/\/track\/(\d+)/);
                            if (deezerMatch) enriched.uri_deezer = 'deezer://track/' + deezerMatch[1];
                        }
                    }
                } catch (e) {
                    console.warn('[Editor] Odesli enrichment failed:', e);
                }

                editorSongs.push(enriched);
                renderEditorSongList();
                this.textContent = '\u2713';
            });
        });

    } catch (e) {
        resultsEl.innerHTML = '<p class="setting-hint">\u274C Network error: ' + utils.escapeHtml(e.message) + '</p>';
    }
}

/**
 * Load and open editor for an existing playlist file
 * @param {string} filename
 */
async function openPlaylistEditor(filename) {
    try {
        var resp = await fetch('/beatify/api/edit-playlist?file=' + encodeURIComponent(filename));
        var data = await resp.json();
        if (data.error) {
            alert('Failed to load playlist: ' + data.error);
            return;
        }
        showPlaylistEditor(data, filename);
    } catch (e) {
        alert('Network error: ' + e.message);
    }
}


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
