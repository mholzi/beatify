/**
 * Beatify Player Page
 * Validates game and shows appropriate state
 */
(function() {
    'use strict';

    // Get game ID from URL
    const urlParams = new URLSearchParams(window.location.search);
    const gameId = urlParams.get('game');

    // View elements
    const loadingView = document.getElementById('loading-view');
    const notFoundView = document.getElementById('not-found-view');
    const endedView = document.getElementById('ended-view');
    const inProgressView = document.getElementById('in-progress-view');
    const joinView = document.getElementById('join-view');
    const lobbyView = document.getElementById('lobby-view');
    const gameView = document.getElementById('game-view');
    const revealView = document.getElementById('reveal-view');
    const endView = document.getElementById('end-view');

    /**
     * Show a specific view and hide all others
     * @param {string} viewId - ID of view to show
     */
    function showView(viewId) {
        [loadingView, notFoundView, endedView, inProgressView, joinView, lobbyView, gameView, revealView, endView].forEach(function(v) {
            if (v) {
                v.classList.add('hidden');
            }
        });
        const view = document.getElementById(viewId);
        if (view) {
            view.classList.remove('hidden');
        }
    }

    /**
     * Validate game ID format
     * @param {string} id - Game ID to validate
     * @returns {boolean} - True if valid format
     */
    function isValidGameIdFormat(id) {
        if (!id || typeof id !== 'string') {
            return false;
        }
        // Game IDs are alphanumeric with dashes and underscores, 8-16 chars
        // token_urlsafe(8) produces 11 characters
        return /^[a-zA-Z0-9_-]{8,16}$/.test(id);
    }

    /**
     * Check game status with the server
     */
    async function checkGameStatus() {
        // Validate game ID exists
        if (!gameId) {
            showView('not-found-view');
            return;
        }

        // Validate game ID format
        if (!isValidGameIdFormat(gameId)) {
            showView('not-found-view');
            return;
        }

        try {
            const response = await fetch(`/beatify/api/game-status?game=${encodeURIComponent(gameId)}`);
            const data = await response.json();

            if (!data.exists) {
                showView('not-found-view');
                return;
            }

            if (data.phase === 'END') {
                showView('ended-view');
                return;
            }

            if (data.can_join) {
                showView('join-view');
                // Full WebSocket connection in Epic 3
            } else {
                // REVEAL or PAUSED - can't join right now
                showView('in-progress-view');
            }

        } catch (err) {
            console.error('Failed to check game status:', err);
            showView('not-found-view');
        }
    }

    // Initialize
    checkGameStatus();

    // Wire refresh/retry buttons
    document.getElementById('refresh-btn')?.addEventListener('click', () => {
        showView('loading-view');
        checkGameStatus();
    });

    document.getElementById('retry-btn')?.addEventListener('click', () => {
        showView('loading-view');
        checkGameStatus();
    });

    // ============================================
    // Name Entry & Join Form (Story 3.1)
    // ============================================

    const MAX_NAME_LENGTH = 20;

    // ============================================
    // Player List Rendering (Story 3.3)
    // ============================================

    let previousPlayers = [];

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Render player list in lobby
     * @param {Array} players - Array of player objects
     */
    function renderPlayerList(players) {
        const listEl = document.getElementById('player-list');
        const countEl = document.getElementById('player-count');
        if (!listEl) return;

        // Update player count
        if (countEl) {
            const count = players.length;
            countEl.textContent = count + ' player' + (count !== 1 ? 's' : '');
        }

        // Find new players by comparing with previous list
        const previousNames = previousPlayers.map(function(p) { return p.name; });
        const newNames = players
            .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
            .map(function(p) { return p.name; });

        // Render player cards
        listEl.innerHTML = players.map(function(player) {
            const isNew = newNames.indexOf(player.name) !== -1;
            const isYou = player.name === playerName;
            const classes = [
                'player-card',
                isNew ? 'is-new' : '',
                isYou ? 'player-card--you' : '',
                !player.connected ? 'player-card--disconnected' : ''
            ].filter(Boolean).join(' ');

            return '<div class="' + classes + '" data-player="' + escapeHtml(player.name) + '">' +
                '<span class="player-name">' +
                    (player.is_admin ? '<span class="admin-badge">👑</span>' : '') +
                    escapeHtml(player.name) +
                    (isYou ? '<span class="you-badge">(You)</span>' : '') +
                '</span>' +
            '</div>';
        }).join('');

        // Remove .is-new class after animation
        setTimeout(function() {
            const newCards = listEl.querySelectorAll('.is-new');
            for (let i = 0; i < newCards.length; i++) {
                newCards[i].classList.remove('is-new');
            }
        }, 2000);

        previousPlayers = players.slice();
    }

    // ============================================
    // QR Code Sharing (Story 3.4)
    // ============================================

    let currentJoinUrl = null;

    /**
     * Render QR code for sharing
     * @param {string} joinUrl - URL to encode in QR
     */
    function renderQRCode(joinUrl) {
        if (!joinUrl) return;
        currentJoinUrl = joinUrl;

        const container = document.getElementById('player-qr-code');
        if (!container) return;

        // Clear previous QR
        container.innerHTML = '';

        // Generate QR code using qrcode-generator
        // Type 0 = auto, Error correction M
        var qr = qrcode(0, 'M');
        qr.addData(joinUrl);
        qr.make();

        // Create image (cell size 4 for inline display)
        container.innerHTML = qr.createImgTag(4, 0);

        // Add click handler for modal
        container.onclick = openQRModal;
        container.onkeydown = function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openQRModal();
            }
        };
    }

    /**
     * Open QR modal with enlarged code
     */
    function openQRModal() {
        if (!currentJoinUrl) return;

        var modal = document.getElementById('qr-modal');
        var modalCode = document.getElementById('qr-modal-code');
        if (!modal || !modalCode) return;

        // Clear and render larger QR
        modalCode.innerHTML = '';
        var qr = qrcode(0, 'M');
        qr.addData(currentJoinUrl);
        qr.make();
        modalCode.innerHTML = qr.createImgTag(8, 0);  // Larger cell size

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
        var modal = document.getElementById('qr-modal');
        var backdrop = modal ? modal.querySelector('.qr-modal-backdrop') : null;
        var closeBtn = document.getElementById('qr-modal-close');

        if (backdrop) {
            backdrop.addEventListener('click', closeQRModal);
        }
        if (closeBtn) {
            closeBtn.addEventListener('click', closeQRModal);
        }

        // Close on Escape key
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
                closeQRModal();
            }
        });
    }

    // ============================================
    // Admin Controls (Story 3.5)
    // ============================================

    let isAdmin = false;

    /**
     * Check if user is admin (from sessionStorage on redirect from admin page)
     * @returns {boolean}
     */
    function checkAdminStatus() {
        const storedAdmin = sessionStorage.getItem('beatify_is_admin');
        const storedName = sessionStorage.getItem('beatify_admin_name');

        if (storedAdmin === 'true' && storedName) {
            isAdmin = true;
            playerName = storedName;
            // Clear storage after reading (keep name for reconnection)
            sessionStorage.removeItem('beatify_is_admin');
        }
        return isAdmin;
    }

    /**
     * Update admin controls visibility based on player state
     * @param {Array} players - Players from state
     */
    function updateAdminControls(players) {
        const adminControls = document.getElementById('admin-controls');
        const lobbyStatus = document.getElementById('lobby-status');
        if (!adminControls) return;

        // Find if current player is admin from state
        const currentPlayer = players.find(function(p) { return p.name === playerName; });
        const playerIsAdmin = currentPlayer?.is_admin === true;

        if (playerIsAdmin) {
            adminControls.classList.remove('hidden');
            if (lobbyStatus) lobbyStatus.classList.add('hidden');
        } else {
            adminControls.classList.add('hidden');
            if (lobbyStatus) lobbyStatus.classList.remove('hidden');
        }
    }

    /**
     * Setup admin control event handlers
     */
    function setupAdminControls() {
        const startBtn = document.getElementById('start-game-btn');

        startBtn?.addEventListener('click', function() {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;

            startBtn.disabled = true;
            startBtn.textContent = 'Starting...';

            ws.send(JSON.stringify({
                type: 'admin',
                action: 'start_game'
            }));
        });
    }

    // ============================================
    // WebSocket Client (Story 3.2)
    // ============================================

    let ws = null;
    let playerName = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_DELAY_MS = 30000;
    const STORAGE_KEY_NAME = 'beatify_player_name';

    /**
     * Get reconnection delay with exponential backoff
     * @returns {number} Delay in milliseconds
     */
    function getReconnectDelay() {
        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s max
        return Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY_MS);
    }

    /**
     * Connect to WebSocket and send join message
     * @param {string} name - Player name
     */
    function connectWebSocket(name) {
        playerName = name;
        // Store name for reconnection (Epic 7 prep)
        try {
            localStorage.setItem(STORAGE_KEY_NAME, name);
        } catch (e) {
            // localStorage may be unavailable in private browsing
        }

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            reconnectAttempts = 0;
            var joinMsg = { type: 'join', name: name };
            if (isAdmin) {
                joinMsg.is_admin = true;
            }
            ws.send(JSON.stringify(joinMsg));
        };

        ws.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        ws.onclose = function() {
            // Attempt reconnection if we were connected and have a name
            if (playerName && reconnectAttempts < 5) {
                reconnectAttempts++;
                const delay = getReconnectDelay();
                console.log('WebSocket closed. Reconnecting in ' + delay + 'ms...');
                setTimeout(function() { connectWebSocket(playerName); }, delay);
            }
        };

        ws.onerror = function(err) {
            console.error('WebSocket error:', err);
        };
    }

    /**
     * Handle messages from server
     * @param {Object} data - Parsed message data
     */
    function handleServerMessage(data) {
        const joinBtn = document.getElementById('join-btn');
        const nameInput = document.getElementById('name-input');

        if (data.type === 'state') {
            if (data.phase === 'LOBBY') {
                showView('lobby-view');
                renderPlayerList(data.players || []);
                // Render QR code with join URL
                if (data.join_url) {
                    renderQRCode(data.join_url);
                }
                // Update admin controls visibility
                updateAdminControls(data.players || []);
            } else if (data.phase === 'PLAYING') {
                showView('game-view');
            } else if (data.phase === 'REVEAL') {
                showView('reveal-view');
            } else if (data.phase === 'END') {
                showView('end-view');
            }
        } else if (data.type === 'error') {
            // Handle GAME_ENDED error specially
            if (data.code === 'GAME_ENDED') {
                showView('end-view');
                return;
            }
            // Show error, re-enable form
            showJoinError(data.message);
            if (joinBtn) {
                joinBtn.disabled = false;
                joinBtn.textContent = 'Join Game';
            }
            if (nameInput) {
                nameInput.focus();
            }
            // Clear stored name on join error
            playerName = null;
        }
    }

    /**
     * Show join error message
     * @param {string} message - Error message to display
     */
    function showJoinError(message) {
        const validationMsg = document.getElementById('name-validation-msg');
        if (validationMsg) {
            validationMsg.textContent = message;
            validationMsg.classList.remove('hidden');
        }
    }

    /**
     * Validate player name
     * @param {string} name - Name to validate
     * @returns {{valid: boolean, name?: string, error?: string}}
     */
    function validateName(name) {
        const trimmed = (name || '').trim();
        if (!trimmed) {
            return { valid: false, error: 'Please enter a name' };
        }
        if (trimmed.length > MAX_NAME_LENGTH) {
            return { valid: false, error: 'Name too long (max 20 characters)' };
        }
        return { valid: true, name: trimmed };
    }

    /**
     * Handle join button click
     */
    function handleJoinClick() {
        const nameInput = document.getElementById('name-input');
        const joinBtn = document.getElementById('join-btn');
        const validationMsg = document.getElementById('name-validation-msg');
        if (!nameInput || !joinBtn) return;

        const result = validateName(nameInput.value);
        if (!result.valid) return;

        joinBtn.disabled = true;
        joinBtn.textContent = 'Joining...';

        // Clear any previous error
        if (validationMsg) {
            validationMsg.classList.add('hidden');
        }

        connectWebSocket(result.name);
    }

    /**
     * Setup join form event handlers
     */
    function setupJoinForm() {
        const nameInput = document.getElementById('name-input');
        const joinBtn = document.getElementById('join-btn');
        const validationMsg = document.getElementById('name-validation-msg');
        if (!nameInput || !joinBtn) return;

        nameInput.addEventListener('input', function() {
            const result = validateName(this.value);
            joinBtn.disabled = !result.valid;
            if (validationMsg) {
                validationMsg.textContent = (!result.valid && this.value) ? result.error : '';
                validationMsg.classList.toggle('hidden', result.valid || !this.value);
            }
        });

        joinBtn.addEventListener('click', handleJoinClick);
        nameInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && !joinBtn.disabled) {
                handleJoinClick();
            }
        });
    }

    // Wrap showView to auto-focus name input
    const originalShowView = showView;
    showView = function(viewId) {
        originalShowView(viewId);
        if (viewId === 'join-view') {
            setTimeout(function() {
                var nameInput = document.getElementById('name-input');
                if (nameInput) nameInput.focus();
            }, 100);
        }
    };

    // Initialize form, QR modal, and admin controls when DOM ready
    function initAll() {
        setupJoinForm();
        setupQRModal();
        setupAdminControls();

        // Check if this is an admin redirect
        if (checkAdminStatus() && playerName) {
            // Auto-connect as admin
            connectWebSocket(playerName);
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

})();
