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
    const pausedView = document.getElementById('paused-view');
    const endView = document.getElementById('end-view');
    const connectionLostView = document.getElementById('connection-lost-view');

    /**
     * Show a specific view and hide all others
     * @param {string} viewId - ID of view to show
     */
    function showView(viewId) {
        [loadingView, notFoundView, endedView, inProgressView, joinView, lobbyView, gameView, revealView, pausedView, endView, connectionLostView].forEach(function(v) {
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
                // Story 11.2: Check for session cookie to auto-reconnect
                var sessionCookie = getSessionCookie();
                if (sessionCookie) {
                    // Attempt session-based reconnection
                    connectWithSession();
                } else {
                    showView('join-view');
                }
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
    // Session Cookie Management (Story 11.1)
    // ============================================

    var SESSION_COOKIE_NAME = 'beatify_session';

    /**
     * Set session cookie with session ID
     * @param {string} sessionId - Session ID from server
     */
    function setSessionCookie(sessionId) {
        // Add Secure flag when on HTTPS (security best practice)
        var secureFlag = location.protocol === 'https:' ? '; Secure' : '';
        document.cookie = SESSION_COOKIE_NAME + '=' + sessionId +
            '; path=/beatify; SameSite=Strict; max-age=86400' + secureFlag;
    }

    /**
     * Get session cookie value
     * @returns {string|null} Session ID or null if not found
     */
    function getSessionCookie() {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.indexOf(SESSION_COOKIE_NAME + '=') === 0) {
                return cookie.substring(SESSION_COOKIE_NAME.length + 1);
            }
        }
        return null;
    }

    /**
     * Clear session cookie
     */
    function clearSessionCookie() {
        document.cookie = SESSION_COOKIE_NAME + '=; path=/beatify; max-age=0';
    }

    /**
     * Validate UUID format (basic check)
     * @param {string} str - String to validate
     * @returns {boolean} True if valid UUID format
     */
    function isValidUUID(str) {
        if (!str || typeof str !== 'string') return false;
        // UUID v4 format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx (36 chars with dashes)
        // Python uuid.uuid4() without dashes: 32 hex chars
        // Allow both formats
        return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(str) ||
               /^[a-f0-9]{32}$/i.test(str);
    }

    /**
     * Attempt to connect with existing session (Story 11.2)
     * Called when page loads and session cookie exists
     */
    function connectWithSession() {
        var sessionId = getSessionCookie();
        if (!sessionId || !isValidUUID(sessionId)) {
            // No session or invalid format, clear and show join form
            if (sessionId) clearSessionCookie();
            showView('join-view');
            return;
        }

        var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            reconnectAttempts = 0;
            isReconnecting = false;
            hideReconnectingOverlay();

            // Send reconnect message with session ID
            ws.send(JSON.stringify({
                type: 'reconnect',
                session_id: sessionId
            }));
        };

        ws.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        ws.onclose = function() {
            // If we have a playerName (reconnect succeeded), try to reconnect
            if (playerName && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                isReconnecting = true;
                reconnectAttempts++;
                showReconnectingOverlay();
                updateReconnectStatus(reconnectAttempts);

                var delay = getReconnectDelay();
                console.log('WebSocket closed. Reconnecting in ' + delay + 'ms... (attempt ' + reconnectAttempts + ')');
                setTimeout(function() { connectWithSession(); }, delay);
            } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
                isReconnecting = false;
                hideReconnectingOverlay();
                showConnectionLostView();
            } else {
                // No playerName means reconnect failed, show join form
                showView('join-view');
            }
        };

        ws.onerror = function(err) {
            console.error('WebSocket error:', err);
        };
    }

    /**
     * Show welcome back toast (Story 11.2)
     * @param {string} name - Player name
     */
    function showWelcomeBackToast(name) {
        var indicator = document.getElementById('volume-indicator');
        if (indicator) {
            indicator.textContent = 'Welcome back, ' + name + '!';
            indicator.classList.remove('hidden');
            indicator.classList.add('is-visible');
            setTimeout(function() {
                indicator.classList.remove('is-visible');
                setTimeout(function() {
                    indicator.classList.add('hidden');
                }, 300);
            }, 2000);
        }
    }

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

        // Story 11.4: Sort players - connected first, then disconnected
        var sortedPlayers = players.slice().sort(function(a, b) {
            if (a.connected !== b.connected) {
                return a.connected ? -1 : 1;
            }
            return 0;  // Preserve order within groups
        });

        // Find new players by comparing with previous list
        const previousNames = previousPlayers.map(function(p) { return p.name; });
        const newNames = sortedPlayers
            .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
            .map(function(p) { return p.name; });

        // Render player cards
        listEl.innerHTML = sortedPlayers.map(function(player) {
            const isNew = newNames.indexOf(player.name) !== -1;
            const isYou = player.name === playerName;
            const isDisconnected = player.connected === false;
            const classes = [
                'player-card',
                isNew ? 'is-new' : '',
                isYou ? 'player-card--you' : '',
                isDisconnected ? 'player-card--disconnected' : ''
            ].filter(Boolean).join(' ');

            // Story 11.4: Add "(away)" badge for disconnected players
            var awayBadge = isDisconnected ? '<span class="away-badge">(away)</span>' : '';

            return '<div class="' + classes + '" data-player="' + escapeHtml(player.name) + '">' +
                '<span class="player-name">' +
                    escapeHtml(player.name) +
                    (isYou ? '<span class="you-badge">(You)</span>' : '') +
                    awayBadge +
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

        var container = document.getElementById('player-qr-code');
        if (!container) return;

        // Clear previous QR
        container.innerHTML = '';

        // Generate QR code using qrcodejs (matches admin.js pattern)
        if (typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: joinUrl,
                width: 128,
                height: 128,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });
        } else {
            container.innerHTML = '<p class="status-error">QR code library not loaded</p>';
        }

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

        // Generate larger QR code using qrcodejs (matches admin.js pattern)
        if (typeof QRCode !== 'undefined') {
            new QRCode(modalCode, {
                text: currentJoinUrl,
                width: 256,
                height: 256,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });
        } else {
            modalCode.innerHTML = '<p class="status-error">QR code library not loaded</p>';
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
    // Countdown Timer (Story 4.2)
    // ============================================

    let countdownInterval = null;

    /**
     * Start countdown timer
     * @param {number} deadline - Server deadline timestamp in milliseconds
     */
    function startCountdown(deadline) {
        // Clear any existing countdown
        stopCountdown();

        var timerElement = document.getElementById('timer');
        if (!timerElement) return;

        // Remove previous state classes
        timerElement.classList.remove('timer--warning', 'timer--critical');

        function updateCountdown() {
            var now = Date.now();
            var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

            timerElement.textContent = remaining;

            // Update timer color based on remaining time
            if (remaining <= 5) {
                timerElement.classList.remove('timer--warning');
                timerElement.classList.add('timer--critical');
            } else if (remaining <= 10) {
                timerElement.classList.remove('timer--critical');
                timerElement.classList.add('timer--warning');
            } else {
                timerElement.classList.remove('timer--warning', 'timer--critical');
            }

            // ARIA announcements at key moments (Story 9.7)
            if (remaining === 10) {
                timerElement.setAttribute('aria-label', '10 seconds remaining');
            } else if (remaining === 5) {
                timerElement.setAttribute('aria-label', '5 seconds!');
            } else if (remaining === 0) {
                timerElement.setAttribute('aria-label', 'Time is up!');
            } else {
                timerElement.setAttribute('aria-label', 'Time remaining: ' + remaining + ' seconds');
            }

            // Stop countdown when reaching 0
            if (remaining <= 0) {
                stopCountdown();
            }
        }

        // Initial update immediately
        updateCountdown();

        // Then update every second
        countdownInterval = setInterval(updateCountdown, 1000);
    }

    /**
     * Stop countdown timer
     */
    function stopCountdown() {
        if (countdownInterval) {
            clearInterval(countdownInterval);
            countdownInterval = null;
        }
    }

    /**
     * Update game view with round data
     * @param {Object} data - State data from server
     */
    function updateGameView(data) {
        // Update round indicator
        var currentRound = document.getElementById('current-round');
        var totalRounds = document.getElementById('total-rounds');
        var lastRoundBanner = document.getElementById('last-round-banner');

        if (currentRound) currentRound.textContent = data.round || 1;
        if (totalRounds) totalRounds.textContent = data.total_rounds || 10;

        // Show/hide last round banner
        if (lastRoundBanner) {
            if (data.last_round) {
                lastRoundBanner.classList.remove('hidden');
            } else {
                lastRoundBanner.classList.add('hidden');
            }
        }

        // Update album cover
        var albumCover = document.getElementById('album-cover');
        var albumLoading = document.getElementById('album-loading');

        if (albumCover && data.song) {
            // Show loading state
            if (albumLoading) albumLoading.classList.remove('hidden');

            var newSrc = data.song.album_art || '/beatify/static/img/no-artwork.svg';

            // Handle image load
            albumCover.onload = function() {
                if (albumLoading) albumLoading.classList.add('hidden');
            };

            // Handle image error - fallback to placeholder
            albumCover.onerror = function() {
                albumCover.src = '/beatify/static/img/no-artwork.svg';
                if (albumLoading) albumLoading.classList.add('hidden');
            };

            albumCover.src = newSrc;
        }

        // Render submission tracker
        renderSubmissionTracker(data.players);

        // Update leaderboard (Story 5.5)
        if (data.leaderboard) {
            updateLeaderboard(data, 'leaderboard-list');
        }
    }

    // ============================================
    // Submission Tracker (Story 4.4)
    // ============================================

    /**
     * Get initials from player name
     * @param {string} name - Player name
     * @returns {string} Initials (1-2 characters)
     */
    function getInitials(name) {
        if (!name) return '?';
        var trimmed = name.trim();
        if (!trimmed) return '?';

        // Handle hyphenated names: "Mary-Jane" -> "MJ"
        var parts = trimmed.split(/[\s-]+/).filter(Boolean);
        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }
        // Single word: take first 2 chars, or 1 if single char name
        return trimmed.slice(0, Math.min(2, trimmed.length)).toUpperCase();
    }

    /**
     * Render submission tracker showing who has submitted
     * @param {Array} players - Array of player objects
     */
    function renderSubmissionTracker(players) {
        var tracker = document.getElementById('submission-tracker');
        var container = document.getElementById('submitted-players');
        var countEl = document.getElementById('submission-count');

        if (!tracker || !container || !countEl) return;

        var playerList = players || [];
        var submittedCount = playerList.filter(function(p) {
            return p.submitted;
        }).length;
        var totalCount = playerList.length;

        // Update count
        countEl.textContent = submittedCount + '/' + totalCount + ' submitted';

        // Check if all submitted
        var allSubmitted = submittedCount === totalCount && totalCount > 0;
        tracker.classList.toggle('all-submitted', allSubmitted);

        // Compact mode for many players
        var isCompact = playerList.length > 10;
        tracker.classList.toggle('is-compact', isCompact);

        if (isCompact) {
            container.innerHTML = '';
            return;
        }

        // Render player indicators (Story 9.10: added is-betting class, Story 11.4: disconnected)
        container.innerHTML = playerList.map(function(player) {
            var initials = getInitials(player.name);
            var isCurrentPlayer = player.name === playerName;
            var isDisconnected = player.connected === false;
            var classes = [
                'player-indicator',
                player.submitted ? 'is-submitted' : '',
                isCurrentPlayer ? 'is-current-player' : '',
                player.bet ? 'is-betting' : '',
                isDisconnected ? 'player-indicator--disconnected' : ''
            ].filter(Boolean).join(' ');

            return '<div class="' + classes + '">' +
                '<div class="player-avatar">' +
                    '<span class="player-initials">' + escapeHtml(initials) + '</span>' +
                '</div>' +
                '<span class="player-name">' + escapeHtml(player.name) + '</span>' +
            '</div>';
        }).join('');
    }

    // ============================================
    // Leaderboard (Story 5.5)
    // ============================================

    /**
     * Update leaderboard display
     * @param {Object} data - State data containing leaderboard
     * @param {string} targetListId - ID of list container (for different views)
     */
    function updateLeaderboard(data, targetListId) {
        var leaderboard = data.leaderboard || [];
        var listEl = document.getElementById(targetListId || 'leaderboard-list');
        if (!listEl) return;

        // Mark is_current client-side
        leaderboard.forEach(function(entry) {
            entry.is_current = (entry.name === playerName);
        });

        // Smart compression for >10 players (Story 9.5)
        var displayList = compressLeaderboard(leaderboard, playerName);

        var html = '';
        displayList.forEach(function(entry) {
            // Handle separator
            if (entry.separator) {
                html += '<div class="leaderboard-separator">...</div>';
                return;
            }

            var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
            var currentClass = entry.is_current ? 'is-current' : '';

            // Rank change animation class (Story 9.5)
            var animationClass = '';
            if (entry.rank_change > 0) {
                animationClass = 'leaderboard-entry--climbing';
            } else if (entry.rank_change < 0) {
                animationClass = 'leaderboard-entry--falling';
            }

            // Rank change indicator
            var changeIndicator = '';
            if (entry.rank_change > 0) {
                changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
            } else if (entry.rank_change < 0) {
                changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';
            }

            // Streak indicator with hot glow for 5+ (Story 9.5)
            var streakIndicator = '';
            if (entry.streak >= 2) {
                var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
                streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
            }

            // Story 11.4: Disconnected player styling
            var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

            html += '<div class="leaderboard-entry ' + rankClass + ' ' + currentClass + ' ' + animationClass + ' ' + disconnectedClass + '" data-rank="' + entry.rank + '">' +
                '<span class="entry-rank">#' + entry.rank + '</span>' +
                '<span class="entry-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
                '<span class="entry-meta">' +
                    streakIndicator +
                    changeIndicator +
                '</span>' +
                '<span class="entry-score">' + entry.score + '</span>' +
            '</div>';
        });

        listEl.innerHTML = html;

        // Scroll to current player if many players
        if (leaderboard.length > 8) {
            scrollToCurrentPlayer(listEl);
        }

        // Update quick indicator
        updateYouIndicator(leaderboard);
    }

    /**
     * Compress leaderboard for display when >10 players (Story 9.5)
     * Shows: top 5, separator, current player if not in top/bottom, separator, bottom 3
     * @param {Array} players - Full leaderboard
     * @param {string} currentPlayerName - Name of current player
     * @returns {Array} Compressed display list
     */
    function compressLeaderboard(players, currentPlayerName) {
        if (players.length <= 10) return players;

        var top5 = players.slice(0, 5);
        var bottom3 = players.slice(-3);
        var currentIdx = -1;

        // Find current player index
        for (var i = 0; i < players.length; i++) {
            if (players[i].name === currentPlayerName) {
                currentIdx = i;
                break;
            }
        }

        // If current player in top 5 or bottom 3, no middle section needed
        if (currentIdx < 5 || currentIdx >= players.length - 3) {
            return [].concat(top5, [{ separator: true }], bottom3);
        }

        // Show current player in middle
        return [].concat(
            top5,
            [{ separator: true }],
            [players[currentIdx]],
            [{ separator: true }],
            bottom3
        );
    }

    /**
     * Scroll leaderboard to show current player
     * @param {Element} listEl - Leaderboard list element
     */
    function scrollToCurrentPlayer(listEl) {
        var currentEntry = listEl.querySelector('.leaderboard-entry.is-current');
        if (currentEntry) {
            currentEntry.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    /**
     * Update "You: #X" quick indicator
     * @param {Array} leaderboard - Leaderboard entries
     */
    function updateYouIndicator(leaderboard) {
        var youEl = document.getElementById('leaderboard-you');
        var currentPlayer = leaderboard.find(function(e) { return e.is_current; });
        if (youEl && currentPlayer) {
            youEl.textContent = 'You: #' + currentPlayer.rank;
            youEl.classList.remove('hidden');
        }
    }

    /**
     * Setup leaderboard toggle behavior
     */
    function setupLeaderboardToggle() {
        var toggle = document.getElementById('leaderboard-toggle');
        var leaderboard = document.getElementById('game-leaderboard');
        if (toggle && leaderboard) {
            toggle.addEventListener('click', function() {
                leaderboard.classList.toggle('is-expanded');
                var icon = toggle.querySelector('.toggle-icon');
                if (icon) {
                    icon.textContent = leaderboard.classList.contains('is-expanded') ? '▲' : '▼';
                }
            });
        }
    }

    // ============================================
    // Year Selector & Submission (Story 4.3)
    // ============================================

    let hasSubmitted = false;
    let betActive = false;  // Betting state (Story 5.3)
    let currentRoundNumber = 0;  // Track round to detect new rounds

    /**
     * Initialize year selector interaction
     */
    function initYearSelector() {
        var slider = document.getElementById('year-slider');
        var yearDisplay = document.getElementById('selected-year');

        if (!slider || !yearDisplay) return;

        // Update display on slider change
        slider.addEventListener('input', function() {
            yearDisplay.textContent = this.value;
        });

        // Bet toggle handler (Story 5.3)
        var betToggle = document.getElementById('bet-toggle');
        if (betToggle) {
            betToggle.addEventListener('click', function() {
                if (hasSubmitted) return;
                betActive = !betActive;
                betToggle.classList.toggle('is-active', betActive);
            });
        }

        // Submit button handler
        var submitBtn = document.getElementById('submit-btn');
        if (submitBtn) {
            submitBtn.addEventListener('click', handleSubmitGuess);
        }
    }

    /**
     * Handle guess submission
     */
    function handleSubmitGuess() {
        if (hasSubmitted) return;

        var slider = document.getElementById('year-slider');
        var submitBtn = document.getElementById('submit-btn');

        if (!slider || !submitBtn) return;

        var year = parseInt(slider.value, 10);

        // Disable and show loading
        submitBtn.disabled = true;
        submitBtn.classList.add('is-loading');

        // Send submission via WebSocket (with bet flag - Story 5.3)
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'submit',
                year: year,
                bet: betActive
            }));
        } else {
            // WebSocket not connected
            showSubmitError('Connection lost. Please refresh.');
            submitBtn.disabled = false;
            submitBtn.classList.remove('is-loading');
        }
    }

    /**
     * Handle server acknowledgment of submission
     */
    function handleSubmitAck() {
        hasSubmitted = true;

        var yearSelector = document.getElementById('year-selector');
        var submitBtn = document.getElementById('submit-btn');
        var confirmation = document.getElementById('submitted-confirmation');
        var betToggle = document.getElementById('bet-toggle');

        if (yearSelector) {
            yearSelector.classList.add('is-submitted');
        }

        if (submitBtn) {
            submitBtn.classList.add('hidden');
        }

        // Hide bet toggle after submission (Story 5.3)
        if (betToggle) {
            betToggle.classList.add('hidden');
        }

        if (confirmation) {
            confirmation.classList.remove('hidden');
        }
    }

    /**
     * Handle submission error
     * @param {Object} data - Error data from server
     */
    function handleSubmitError(data) {
        var submitBtn = document.getElementById('submit-btn');

        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('is-loading');
        }

        if (data.code === 'ROUND_EXPIRED') {
            showSubmitError("Time's up!");
            // Disable further attempts
            hasSubmitted = true;
            if (submitBtn) submitBtn.disabled = true;
        } else if (data.code === 'ALREADY_SUBMITTED') {
            // Already submitted, update UI
            handleSubmitAck();
        } else {
            showSubmitError(data.message || 'Submission failed');
        }
    }

    /**
     * Show error on submit button
     * @param {string} message - Error message
     */
    function showSubmitError(message) {
        var submitBtn = document.getElementById('submit-btn');
        if (submitBtn) {
            submitBtn.textContent = message;
            submitBtn.classList.add('is-error');
            setTimeout(function() {
                submitBtn.textContent = 'Submit Guess';
                submitBtn.classList.remove('is-error');
            }, 2000);
        }
    }

    /**
     * Reset submission state for new round
     */
    function resetSubmissionState() {
        hasSubmitted = false;
        betActive = false;  // Reset bet (Story 5.3)

        var yearSelector = document.getElementById('year-selector');
        var submitBtn = document.getElementById('submit-btn');
        var confirmation = document.getElementById('submitted-confirmation');
        var slider = document.getElementById('year-slider');
        var betToggle = document.getElementById('bet-toggle');

        if (yearSelector) {
            yearSelector.classList.remove('is-submitted');
        }

        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.classList.remove('hidden', 'is-loading', 'is-error');
            submitBtn.textContent = 'Submit Guess';
        }

        // Reset bet toggle (Story 5.3)
        if (betToggle) {
            betToggle.classList.remove('hidden', 'is-active');
        }

        if (confirmation) {
            confirmation.classList.add('hidden');
        }

        // Reset slider to middle value
        if (slider) {
            slider.value = 1990;
            var yearDisplay = document.getElementById('selected-year');
            if (yearDisplay) yearDisplay.textContent = '1990';
        }
    }

    // ============================================
    // Reveal View (Story 4.6)
    // ============================================

    /**
     * Update reveal view with round results
     * @param {Object} data - State data from server
     */
    function updateRevealView(data) {
        var song = data.song || {};
        var players = data.players || [];

        // Update round info
        var roundEl = document.getElementById('reveal-round');
        var totalEl = document.getElementById('reveal-total');
        if (roundEl) roundEl.textContent = data.round || 1;
        if (totalEl) totalEl.textContent = data.total_rounds || 10;

        // Update album cover
        var albumCover = document.getElementById('reveal-album-cover');
        if (albumCover) {
            albumCover.src = song.album_art || '/beatify/static/img/no-artwork.svg';
        }

        // Update correct year
        var correctYear = document.getElementById('correct-year');
        if (correctYear) {
            correctYear.textContent = song.year || '????';
        }

        // Update song info
        var titleEl = document.getElementById('song-title');
        var artistEl = document.getElementById('song-artist');
        if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
        if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';

        // Update fun fact
        var funFactContainer = document.getElementById('fun-fact-container');
        var funFactText = document.getElementById('fun-fact');
        if (funFactContainer && funFactText) {
            if (song.fun_fact) {
                funFactText.textContent = song.fun_fact;
                funFactContainer.classList.remove('hidden');
            } else {
                funFactContainer.classList.add('hidden');
            }
        }

        // Find current player's result
        var currentPlayer = null;
        for (var i = 0; i < players.length; i++) {
            if (players[i].name === playerName) {
                currentPlayer = players[i];
                break;
            }
        }

        // Show celebration-first reveal (Story 9.4)
        showRevealEmotion(currentPlayer, song.year);
        renderPersonalResult(currentPlayer, song.year);

        // Render player result cards (Story 9.10)
        renderPlayerResultCards(players);

        // Update leaderboard (Story 5.5)
        if (data.leaderboard) {
            updateLeaderboard(data, 'reveal-leaderboard-list');
        }

        // Show admin controls if admin
        var adminControls = document.getElementById('reveal-admin-controls');
        var nextRoundBtn = document.getElementById('next-round-btn');
        if (adminControls && currentPlayer && currentPlayer.is_admin) {
            adminControls.classList.remove('hidden');

            // Update button text for last round
            if (nextRoundBtn) {
                if (data.last_round) {
                    nextRoundBtn.textContent = 'Final Results';
                    nextRoundBtn.classList.add('is-final');
                } else {
                    nextRoundBtn.textContent = 'Next Round';
                    nextRoundBtn.classList.remove('is-final');
                }
                nextRoundBtn.disabled = false;
            }
        } else if (adminControls) {
            adminControls.classList.add('hidden');
        }
    }

    /**
     * Show celebration-first emotion before data (Story 9.4)
     * @param {Object} player - Current player data
     * @param {number} correctYear - The correct year
     */
    function showRevealEmotion(player, correctYear) {
        var emotionEl = document.getElementById('reveal-emotion');
        var personalResult = document.getElementById('personal-result');
        if (!emotionEl) return;

        // Reset emotion element
        emotionEl.className = 'reveal-emotion';
        emotionEl.innerHTML = '';
        emotionEl.classList.add('hidden');

        // Reset personal result delay
        if (personalResult) {
            personalResult.classList.remove('is-delayed');
        }

        // Stop any existing confetti
        stopConfetti();

        // Fun text alternatives for each outcome (20 each)
        var exactTexts = [
            'NAILED IT!', 'PERFECT!', 'BULLSEYE!', 'GENIUS!', 'LEGENDARY!',
            'FLAWLESS!', 'SPOT ON!', 'CRUSHING IT!', 'UNSTOPPABLE!', 'GODLIKE!',
            'MIND READER!', 'TIME LORD!', 'AMAZING!', 'SUPERSTAR!', 'EPIC WIN!',
            'BOOM!', 'WIZARDRY!', 'SORCERY!', 'UNREAL!', 'INCREDIBLE!'
        ];
        var exactSubtitles = [
            'Perfect guess!', 'You absolute legend!', 'Are you from this era?',
            'Living encyclopedia!', 'Music historian!', 'Ears of gold!',
            'Did you write this song?', 'Spooky accurate!', 'Take a bow!',
            'Chef\'s kiss!', 'No notes!', 'Mic drop moment!', 'Hall of fame!',
            'Pure perfection!', 'Textbook answer!', 'Nerd alert!', 'Scary good!',
            'You\'re on fire!', 'The oracle speaks!', 'Bow down everyone!'
        ];

        var closeTexts = [
            'SO CLOSE!', 'ALMOST!', 'NEARLY!', 'CLOSE ONE!', 'JUST MISSED!',
            'HOT!', 'WARM!', 'NICE TRY!', 'GOOD EAR!', 'SOLID!',
            'RESPECTABLE!', 'NOT BAD!', 'DECENT!', 'FAIR PLAY!', 'CLOSE CALL!',
            'INCHES AWAY!', 'HAIR\'S WIDTH!', 'TANTALIZINGLY CLOSE!', 'OOH!', 'AHH!'
        ];
        var closeSubtitles = [
            'So tantalizingly close!', 'You could taste it!', 'Almost had it!',
            'Just a whisker off!', 'The vibes were right!', 'Trust your gut more!',
            'Your instincts are good!', 'Nearly nailed it!', 'Close but no cigar!',
            'A worthy attempt!', 'You\'re getting warmer!', 'In the ballpark!',
            'Right neighborhood!', 'Solid guess!', 'Can\'t be mad at that!',
            'Points on the board!', 'That\'ll do!', 'Respectable effort!',
            'Keep that energy!', 'You\'re onto something!'
        ];

        var wrongTexts = [
            'OOPS!', 'YIKES!', 'UH OH!', 'WELP!', 'SWING AND A MISS!',
            'NOT QUITE!', 'WAY OFF!', 'NOPE!', 'WRONG ERA!', 'TIME WARP!',
            'PLOT TWIST!', 'SURPRISE!', 'WHOOPSIE!', 'AWKWARD!', 'BRUH!',
            'REALLY?', 'NICE TRY!', 'OOF!', 'YEET!', 'RIP!'
        ];
        var wrongSubtitles = [
            'That was... creative!', 'Bold strategy!', 'Points for confidence!',
            'Wrong decade, friend!', 'Time machine needed!', 'History is hard!',
            'We\'ve all been there!', 'Shake it off!', 'Next round is yours!',
            'Interesting theory!', 'Alternative timeline!', 'Parallel universe guess!',
            'The vibes deceived you!', 'Music is tricky!', 'Happens to the best!',
            'Plot twist energy!', 'Confidently incorrect!', 'Swing for the fences!',
            'At least you tried!', 'Character building moment!'
        ];

        var missedTexts = [
            'NO GUESS', 'TIME\'S UP!', 'TOO SLOW!', 'MISSED IT!', 'SNOOZE!',
            'ASLEEP?', 'HELLO?', 'EARTH TO YOU!', 'FROZEN!', 'AFK!',
            'BUFFERING...', 'TIMED OUT!', 'GHOST MODE!', 'VANISHED!', 'INVISIBLE!',
            'SILENCE!', 'CRICKETS!', 'NADA!', 'ZILCH!', 'ABSENT!'
        ];
        var missedSubtitles = [
            'Time ran out!', 'The clock waits for no one!', 'Too busy vibing?',
            'Song was that good huh?', 'Analysis paralysis!', 'Indecision is a decision!',
            'Phone died?', 'Cat walked on keyboard?', 'Snack break?',
            'Lost in the music!', 'Daydreaming!', 'Zoned out!',
            'Brain freeze!', 'Decision fatigue!', 'Overthinking it!',
            'Commitment issues!', 'Stage fright!', 'Performance anxiety!',
            'Better luck next round!', 'Wake up call!'
        ];

        // Helper to pick random from array
        function randomFrom(arr) {
            return arr[Math.floor(Math.random() * arr.length)];
        }

        // Determine emotion category
        var emotionType = 'missed';
        var emotionText = randomFrom(missedTexts);
        var subtitle = randomFrom(missedSubtitles);

        if (player && !player.missed_round) {
            var yearsOff = player.years_off || 0;

            if (yearsOff === 0) {
                emotionType = 'exact';
                emotionText = randomFrom(exactTexts);
                subtitle = randomFrom(exactSubtitles);
            } else if (yearsOff <= 2) {
                emotionType = 'close';
                emotionText = randomFrom(closeTexts);
                subtitle = randomFrom(closeSubtitles) + ' Off by ' + yearsOff + ' year' + (yearsOff > 1 ? 's' : '') + '!';
            } else if (yearsOff <= 5) {
                emotionType = 'close';
                emotionText = randomFrom(closeTexts);
                subtitle = 'Off by ' + yearsOff + ' years';
            } else {
                emotionType = 'wrong';
                emotionText = randomFrom(wrongTexts);
                subtitle = randomFrom(wrongSubtitles) + ' Off by ' + yearsOff + ' years!';
            }
        } else if (player && player.missed_round) {
            emotionType = 'missed';
            emotionText = randomFrom(missedTexts);
            subtitle = randomFrom(missedSubtitles);
        }

        // Build emotion HTML
        var emotionHtml = '<span class="reveal-emotion-text">' + emotionText + '</span>';
        if (subtitle) {
            emotionHtml += '<div class="reveal-emotion-subtitle">' + subtitle + '</div>';
        }
        emotionEl.innerHTML = emotionHtml;

        // Apply emotion class
        emotionEl.classList.add('reveal-emotion--' + emotionType);
        emotionEl.classList.remove('hidden');

        // Trigger confetti for exact match
        if (emotionType === 'exact') {
            triggerConfetti();
        }

        // Add delay class to personal result for fade-in effect
        if (personalResult && emotionType !== 'missed') {
            personalResult.classList.add('is-delayed');
        }
    }

    /**
     * Render personal result in reveal view
     * @param {Object} player - Current player data
     * @param {number} correctYear - The correct year
     */
    function renderPersonalResult(player, correctYear) {
        var resultContent = document.getElementById('result-content');
        if (!resultContent) return;

        if (!player) {
            resultContent.innerHTML = '<div class="result-missed">Player not found</div>';
            return;
        }

        if (player.missed_round) {
            // Enhanced missed round display (Story 5.4)
            var missedHtml =
                '<div class="result-missed-container">' +
                    '<div class="result-missed-icon">⏰</div>' +
                    '<div class="result-missed-text">No guess submitted</div>' +
                '</div>';

            // Show broken streak if they had one (>= 2)
            var previousStreak = player.previous_streak || 0;
            if (previousStreak >= 2) {
                missedHtml +=
                    '<div class="streak-broken">' +
                        '<span class="streak-broken-icon">💔</span>' +
                        '<span class="streak-broken-text">Lost ' + previousStreak + '-streak!</span>' +
                    '</div>';
            }

            missedHtml += '<div class="result-score is-zero">0 pts</div>';
            resultContent.innerHTML = missedHtml;
            return;
        }

        var yearsOff = player.years_off || 0;
        var yearsOffText = yearsOff === 0 ? 'Exact!' :
                           yearsOff === 1 ? '1 year off' :
                           yearsOff + ' years off';

        var resultClass = yearsOff === 0 ? 'is-exact' :
                          yearsOff <= 3 ? 'is-close' : 'is-far';

        // Speed bonus display (Story 5.1)
        var speedMultiplier = player.speed_multiplier || 1.0;
        var baseScore = player.base_score || 0;
        var hasSpeedBonus = speedMultiplier > 1.0;

        // Streak bonus display (Story 5.2)
        var streakBonus = player.streak_bonus || 0;

        var scoreBreakdown = '';
        if (hasSpeedBonus && baseScore > 0) {
            scoreBreakdown =
                '<div class="result-row">' +
                    '<span class="result-label">Base score</span>' +
                    '<span class="result-value">' + baseScore + ' pts</span>' +
                '</div>' +
                '<div class="result-row">' +
                    '<span class="result-label">Speed bonus</span>' +
                    '<span class="result-value is-bonus">' + speedMultiplier.toFixed(2) + 'x</span>' +
                '</div>';
        }

        // Bet outcome row (Story 5.3)
        var betOutcomeHtml = '';
        if (player.bet_outcome === 'won') {
            betOutcomeHtml =
                '<div class="result-row bet-won-row">' +
                    '<span class="result-label">🎲 Bet paid off!</span>' +
                    '<span class="result-value is-bet-won">2x</span>' +
                '</div>';
        } else if (player.bet_outcome === 'lost') {
            betOutcomeHtml =
                '<div class="result-row bet-lost-row">' +
                    '<span class="result-label">🎲 Bet lost</span>' +
                    '<span class="result-value is-bet-lost">No bonus</span>' +
                '</div>';
        }

        // Streak bonus row (Story 5.2)
        var streakBonusHtml = '';
        if (streakBonus > 0) {
            streakBonusHtml =
                '<div class="result-row streak-bonus-row">' +
                    '<span class="result-label">' + player.streak + '-streak bonus!</span>' +
                    '<span class="result-value is-streak">+' + streakBonus + ' pts</span>' +
                '</div>';
        }

        // Calculate total (round_score already includes bet + speed bonus, add streak separately)
        var totalScore = player.round_score + streakBonus;

        resultContent.innerHTML =
            '<div class="result-row">' +
                '<span class="result-label">Your guess</span>' +
                '<span class="result-value">' + player.guess + '</span>' +
            '</div>' +
            '<div class="result-row">' +
                '<span class="result-label">Correct year</span>' +
                '<span class="result-value">' + correctYear + '</span>' +
            '</div>' +
            '<div class="result-row">' +
                '<span class="result-label">Accuracy</span>' +
                '<span class="result-value ' + resultClass + '">' + yearsOffText + '</span>' +
            '</div>' +
            scoreBreakdown +
            betOutcomeHtml +
            '<div class="result-score">+' + player.round_score + ' pts</div>' +
            streakBonusHtml +
            (streakBonus > 0 ? '<div class="result-total">Total: +' + totalScore + ' pts</div>' : '');
    }

    /**
     * Render player result cards on reveal (Story 9.10)
     * Shows all players' guesses, years off, and points in horizontal scroll
     * @param {Array} players - All players from state
     */
    function renderPlayerResultCards(players) {
        var container = document.getElementById('reveal-results-cards');
        if (!container) return;

        if (!players || players.length === 0) {
            container.innerHTML = '';
            return;
        }

        // Sort players by round_score descending (best first)
        var sorted = players.slice().sort(function(a, b) {
            return (b.round_score || 0) - (a.round_score || 0);
        });

        var html = '<div class="results-cards-header">All Players</div>';
        html += '<div class="results-cards-scroll">';

        sorted.forEach(function(player) {
            var isCurrentPlayer = player.name === playerName;
            var isMissed = player.missed_round === true;
            var yearsOff = player.years_off || 0;
            var roundScore = player.round_score || 0;

            // Determine score-based class per AC #13 (Code Review fix)
            var scoreClass = isMissed ? 'is-score-zero' :
                             roundScore >= 10 ? 'is-score-high' :
                             roundScore >= 1 ? 'is-score-medium' : 'is-score-zero';

            // Guess display
            var guessDisplay = isMissed ? '—' : player.guess;
            var yearsOffDisplay = isMissed ? 'No guess' :
                                  yearsOff === 0 ? 'Exact!' :
                                  yearsOff + ' off';

            // Bet indicator
            var betIndicator = player.bet ? '<span class="card-bet">🎲</span>' : '';

            html += '<div class="result-card ' + scoreClass + (isCurrentPlayer ? ' is-current' : '') + '">' +
                '<div class="card-name">' + escapeHtml(player.name) + betIndicator + '</div>' +
                '<div class="card-guess">' + guessDisplay + '</div>' +
                '<div class="card-accuracy">' + yearsOffDisplay + '</div>' +
                '<div class="card-score">+' + roundScore + '</div>' +
            '</div>';
        });

        html += '</div>';
        container.innerHTML = html;
    }

    // ============================================
    // End View (Story 5.6)
    // ============================================

    /**
     * Update end view with final standings and stats
     * @param {Object} data - State data with leaderboard and game_stats
     */
    function updateEndView(data) {
        var leaderboard = data.leaderboard || [];

        // Mark is_current client-side
        leaderboard.forEach(function(entry) {
            entry.is_current = (entry.name === playerName);
        });

        // Update podium (positions 1, 2, 3)
        [1, 2, 3].forEach(function(place) {
            var player = leaderboard.find(function(p) { return p.rank === place; });
            var nameEl = document.getElementById('podium-' + place + '-name');
            var scoreEl = document.getElementById('podium-' + place + '-score');
            if (nameEl) nameEl.textContent = player ? escapeHtml(player.name) : '---';
            if (scoreEl) scoreEl.textContent = player ? player.score : '0';
        });

        // Find current player's stats
        var currentPlayer = leaderboard.find(function(p) { return p.is_current; });

        // Update your result
        var rankEl = document.getElementById('your-final-rank');
        var scoreEl = document.getElementById('your-final-score');
        var bestStreakEl = document.getElementById('stat-best-streak');
        var roundsEl = document.getElementById('stat-rounds');
        var betsEl = document.getElementById('stat-bets');

        if (currentPlayer) {
            if (rankEl) rankEl.textContent = '#' + currentPlayer.rank;
            if (scoreEl) scoreEl.textContent = currentPlayer.score + ' points';
            if (bestStreakEl) bestStreakEl.textContent = currentPlayer.best_streak || 0;
            if (roundsEl) roundsEl.textContent = currentPlayer.rounds_played || 0;
            if (betsEl) betsEl.textContent = currentPlayer.bets_won || 0;
        }

        // Update full leaderboard (Story 11.4: disconnected styling)
        var listEl = document.getElementById('final-leaderboard-list');
        if (listEl) {
            listEl.innerHTML = leaderboard.map(function(entry) {
                var currentClass = entry.is_current ? 'is-current' : '';
                var disconnectedClass = entry.connected === false ? 'final-entry--disconnected' : '';
                var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';
                return '<div class="final-entry ' + currentClass + ' ' + disconnectedClass + '">' +
                    '<span class="final-rank">#' + entry.rank + '</span>' +
                    '<span class="final-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
                    '<span class="final-score">' + entry.score + '</span>' +
                '</div>';
            }).join('');
        }

        // Show admin or player controls
        var adminControls = document.getElementById('end-admin-controls');
        var playerMessage = document.getElementById('end-player-message');

        if (currentPlayer && currentPlayer.is_admin) {
            if (adminControls) adminControls.classList.remove('hidden');
            if (playerMessage) playerMessage.classList.add('hidden');
            // Wire up new game button
            var newGameBtn = document.getElementById('new-game-btn');
            if (newGameBtn) {
                newGameBtn.onclick = handleNewGame;
            }
        } else {
            if (adminControls) adminControls.classList.add('hidden');
            if (playerMessage) playerMessage.classList.remove('hidden');
        }
    }

    // ============================================
    // Paused View (Story 7-1)
    // ============================================

    /**
     * Update paused view based on pause reason
     * @param {Object} data - State data with pause_reason
     */
    function updatePausedView(data) {
        var messageEl = document.getElementById('pause-message');
        if (messageEl) {
            if (data.pause_reason === 'admin_disconnected') {
                messageEl.textContent = 'Waiting for host to reconnect...';
            } else {
                messageEl.textContent = 'Game paused. Please wait...';
            }
        }
    }

    /**
     * Handle new game button click (Story 6.6)
     */
    function handleNewGame() {
        if (!confirm('Start a new game?')) {
            return;
        }

        var btn = document.getElementById('new-game-btn');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Redirecting...';
        }

        // Clear admin session storage
        try {
            sessionStorage.removeItem('beatify_admin_name');
            sessionStorage.removeItem('beatify_is_admin');
        } catch (e) {
            // Ignore storage errors
        }

        // Redirect to admin page for new game setup
        window.location.href = '/beatify/admin';
    }

    // Debounce state to prevent rapid clicks
    var nextRoundPending = false;
    var NEXT_ROUND_DEBOUNCE_MS = 2000;

    /**
     * Handle next round button click
     */
    function handleNextRound() {
        // Prevent rapid clicks
        if (nextRoundPending) {
            return;
        }

        if (ws && ws.readyState === WebSocket.OPEN) {
            nextRoundPending = true;

            // Update both buttons (reveal-view and control bar) - Story 6.3
            var revealBtn = document.getElementById('next-round-btn');
            var barBtn = document.getElementById('next-round-admin-btn');

            if (revealBtn) {
                revealBtn.disabled = true;
                revealBtn.textContent = 'Loading...';
            }
            if (barBtn) {
                barBtn.disabled = true;
                var labelEl = barBtn.querySelector('.control-label');
                if (labelEl) labelEl.textContent = 'Wait...';
            }

            ws.send(JSON.stringify({
                type: 'admin',
                action: 'next_round'
            }));

            // Reset after debounce period (server state change will also update UI)
            setTimeout(function() {
                nextRoundPending = false;
                if (revealBtn) revealBtn.disabled = false;
                if (barBtn) barBtn.disabled = false;
            }, NEXT_ROUND_DEBOUNCE_MS);
        }
    }

    // ============================================
    // Admin Control Bar (Story 6.1)
    // ============================================

    // Debounce state for admin actions
    let adminActionPending = false;
    var ADMIN_ACTION_DEBOUNCE_MS = 500;

    // Song stopped state (Story 6.2)
    let songStopped = false;

    // Volume state (Story 6.4)
    let currentVolume = 0.5;

    /**
     * Debounce admin actions to prevent rapid repeated clicks
     * @returns {boolean} True if action can proceed, false if debounced
     */
    function debounceAdminAction() {
        if (adminActionPending) return false;
        adminActionPending = true;
        setTimeout(function() { adminActionPending = false; }, ADMIN_ACTION_DEBOUNCE_MS);
        return true;
    }

    /**
     * Show admin control bar for admin players
     */
    function showAdminControlBar() {
        if (!isAdmin) return;
        var bar = document.getElementById('admin-control-bar');
        if (bar) {
            bar.classList.remove('hidden');
            document.body.classList.add('has-control-bar'); // M3 fix
        }
    }

    /**
     * Hide admin control bar
     */
    function hideAdminControlBar() {
        var bar = document.getElementById('admin-control-bar');
        if (bar) {
            bar.classList.add('hidden');
            document.body.classList.remove('has-control-bar'); // M3 fix
        }
    }

    /**
     * Update control bar button states based on phase
     * @param {string} phase - Current game phase
     */
    function updateControlBarState(phase) {
        var stopBtn = document.getElementById('stop-song-btn');
        var nextBtn = document.getElementById('next-round-admin-btn');

        if (phase === 'PLAYING') {
            // Reset song stopped state for new round (Story 6.2)
            resetSongStoppedState();
            // Stop Song enabled (unless already stopped)
            if (stopBtn && !songStopped) {
                stopBtn.classList.remove('is-disabled');
                stopBtn.disabled = false;
            }
            // Next Round enabled for "Skip" functionality (Story 6.3)
            if (nextBtn) {
                nextBtn.classList.remove('is-disabled');
                nextBtn.disabled = false;
                var labelEl = nextBtn.querySelector('.control-label');
                if (labelEl) labelEl.textContent = 'Skip';
            }
        } else if (phase === 'REVEAL') {
            // Stop Song disabled, Next Round enabled
            if (stopBtn) {
                stopBtn.classList.add('is-disabled');
                stopBtn.disabled = true;
            }
            if (nextBtn) {
                nextBtn.classList.remove('is-disabled');
                nextBtn.disabled = false;
                var labelEl = nextBtn.querySelector('.control-label');
                if (labelEl) labelEl.textContent = 'Next';
            }
        } else {
            // LOBBY or END: disable Next Round (Story 6.3)
            if (nextBtn) {
                nextBtn.classList.add('is-disabled');
                nextBtn.disabled = true;
                var labelEl = nextBtn.querySelector('.control-label');
                if (labelEl) labelEl.textContent = 'Next';
            }
        }
        // Volume and End Game always enabled (no changes needed)
    }

    /**
     * Handle Stop Song button
     */
    function handleStopSong() {
        if (!debounceAdminAction()) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        ws.send(JSON.stringify({
            type: 'admin',
            action: 'stop_song'
        }));
    }

    /**
     * Handle Volume Up button
     */
    function handleVolumeUp() {
        // Check limit before debounce (M2 fix)
        if (currentVolume >= 1.0) {
            showVolumeLimitFeedback('max');
            return;
        }
        if (!debounceAdminAction()) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        ws.send(JSON.stringify({
            type: 'admin',
            action: 'set_volume',
            direction: 'up'
        }));
    }

    /**
     * Handle Volume Down button
     */
    function handleVolumeDown() {
        // Check limit before debounce (M2 fix)
        if (currentVolume <= 0.0) {
            showVolumeLimitFeedback('min');
            return;
        }
        if (!debounceAdminAction()) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        ws.send(JSON.stringify({
            type: 'admin',
            action: 'set_volume',
            direction: 'down'
        }));
    }

    /**
     * Show feedback when volume is at limit (M2 fix)
     * @param {string} limit - 'max' or 'min'
     */
    function showVolumeLimitFeedback(limit) {
        var indicator = document.getElementById('volume-indicator');
        if (!indicator) return;

        indicator.textContent = limit === 'max' ? '🔊 Max' : '🔇 Min';
        indicator.classList.remove('hidden');
        indicator.classList.add('is-visible');

        // Fade out after 1s (shorter than normal feedback)
        setTimeout(function() {
            indicator.classList.remove('is-visible');
            setTimeout(function() {
                indicator.classList.add('hidden');
            }, 300);
        }, 1000);
    }

    /**
     * Handle End Game button
     */
    function handleEndGame() {
        if (!confirm('End game and show final results?')) return;
        if (!debounceAdminAction()) return;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            alert('Connection lost. Please refresh.');
            return;
        }

        // Update button state (Story 6.5)
        var endBtn = document.getElementById('end-game-btn');
        if (endBtn) {
            endBtn.disabled = true;
            var labelEl = endBtn.querySelector('.control-label');
            if (labelEl) labelEl.textContent = 'Ending...';
        }

        ws.send(JSON.stringify({
            type: 'admin',
            action: 'end_game'
        }));
    }

    /**
     * Handle Next Round from control bar (reuse reveal logic)
     */
    function handleNextRoundFromBar() {
        handleNextRound();
    }

    /**
     * Setup admin control bar event handlers
     */
    function setupAdminControlBar() {
        var stopBtn = document.getElementById('stop-song-btn');
        var volUpBtn = document.getElementById('volume-up-btn');
        var volDownBtn = document.getElementById('volume-down-btn');
        var nextBtn = document.getElementById('next-round-admin-btn');
        var endBtn = document.getElementById('end-game-btn');

        if (stopBtn) stopBtn.addEventListener('click', handleStopSong);
        if (volUpBtn) volUpBtn.addEventListener('click', handleVolumeUp);
        if (volDownBtn) volDownBtn.addEventListener('click', handleVolumeDown);
        if (nextBtn) nextBtn.addEventListener('click', handleNextRoundFromBar);
        if (endBtn) endBtn.addEventListener('click', handleEndGame);
    }

    /**
     * Handle song stopped notification from server (Story 6.2)
     */
    function handleSongStopped() {
        songStopped = true;
        var stopBtn = document.getElementById('stop-song-btn');
        if (stopBtn) {
            stopBtn.classList.add('is-stopped');
            stopBtn.classList.add('is-disabled');
            stopBtn.disabled = true;
            var iconEl = stopBtn.querySelector('.control-icon');
            var labelEl = stopBtn.querySelector('.control-label');
            if (iconEl) iconEl.textContent = '✓';
            if (labelEl) labelEl.textContent = 'Stopped';
        }
    }

    /**
     * Reset song stopped state for new round (Story 6.2)
     */
    function resetSongStoppedState() {
        songStopped = false;
        var stopBtn = document.getElementById('stop-song-btn');
        if (stopBtn) {
            stopBtn.classList.remove('is-stopped');
            stopBtn.classList.remove('is-disabled');
            stopBtn.disabled = false;
            var iconEl = stopBtn.querySelector('.control-icon');
            var labelEl = stopBtn.querySelector('.control-label');
            if (iconEl) iconEl.textContent = '⏹️';
            if (labelEl) labelEl.textContent = 'Stop';
        }
    }

    /**
     * Handle volume changed response from server (Story 6.4)
     * @param {number} level - New volume level (0.0 to 1.0)
     */
    function handleVolumeChanged(level) {
        currentVolume = level;
        showVolumeIndicator(level);
        updateVolumeLimitStates(level);
    }

    /**
     * Show brief volume indicator popup (Story 6.4)
     * @param {number} level - Volume level
     */
    function showVolumeIndicator(level) {
        var indicator = document.getElementById('volume-indicator');
        if (!indicator) return;

        var percentage = Math.round(level * 100);
        indicator.textContent = '🔊 ' + percentage + '%';
        indicator.classList.remove('hidden');
        indicator.classList.add('is-visible');

        // Fade out after 1.5s
        setTimeout(function() {
            indicator.classList.remove('is-visible');
            setTimeout(function() {
                indicator.classList.add('hidden');
            }, 300);
        }, 1500);
    }

    /**
     * Update volume buttons when at limits (Story 6.4)
     * @param {number} level - Current volume level
     */
    function updateVolumeLimitStates(level) {
        var upBtn = document.getElementById('volume-up-btn');
        var downBtn = document.getElementById('volume-down-btn');

        if (upBtn) {
            upBtn.classList.toggle('is-at-limit', level >= 1.0);
        }
        if (downBtn) {
            downBtn.classList.toggle('is-at-limit', level <= 0.0);
        }
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
        const leaveGameContainer = document.getElementById('leave-game-container');
        if (!adminControls) return;

        // Find if current player is admin from state
        const currentPlayer = players.find(function(p) { return p.name === playerName; });
        const playerIsAdmin = currentPlayer?.is_admin === true;

        if (playerIsAdmin) {
            adminControls.classList.remove('hidden');
            if (lobbyStatus) lobbyStatus.classList.add('hidden');
            // Story 11.5: Admin cannot leave, hide button
            if (leaveGameContainer) leaveGameContainer.classList.add('hidden');
        } else {
            adminControls.classList.add('hidden');
            if (lobbyStatus) lobbyStatus.classList.remove('hidden');
            // Story 11.5: Non-admin can leave
            if (leaveGameContainer) leaveGameContainer.classList.remove('hidden');
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

        // Story 11.5: Leave Game button
        const leaveBtn = document.getElementById('leave-game-btn');
        leaveBtn?.addEventListener('click', function() {
            handleLeaveGame();
        });
    }

    // ============================================
    // WebSocket Client (Story 3.2)
    // ============================================

    let ws = null;
    let playerName = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;  // Story 7-3: Increased for resilience
    const MAX_RECONNECT_DELAY_MS = 30000;
    const STORAGE_KEY_NAME = 'beatify_player_name';
    const STORAGE_KEY_GAME_ID = 'beatify_game_id';

    // Reconnection state (Story 7-3)
    let isReconnecting = false;

    // Intentional leave flag (Story 11.5) - prevents auto-reconnect after Leave Game
    let intentionalLeave = false;

    /**
     * Get reconnection delay with exponential backoff
     * @returns {number} Delay in milliseconds
     */
    function getReconnectDelay() {
        // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s max
        return Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY_MS);
    }

    /**
     * Get stored player name for this game (Story 7-3)
     * @returns {string|null} Stored name or null
     */
    function getStoredPlayerName() {
        try {
            var storedGameId = localStorage.getItem(STORAGE_KEY_GAME_ID);
            var storedName = localStorage.getItem(STORAGE_KEY_NAME);
            console.log('[Beatify] Checking localStorage - storedGameId:', storedGameId, 'currentGameId:', gameId, 'storedName:', storedName);

            if (storedGameId && storedGameId === gameId) {
                console.log('[Beatify] Game ID match, returning stored name:', storedName);
                return storedName;
            }

            if (storedGameId && storedGameId !== gameId) {
                // Different game, clear stored name
                console.log('[Beatify] Different game ID, clearing stored data');
                localStorage.removeItem(STORAGE_KEY_NAME);
                localStorage.removeItem(STORAGE_KEY_GAME_ID);
            }
        } catch (e) {
            console.error('[Beatify] localStorage error:', e);
        }
        return null;
    }

    /**
     * Store player name for reconnection (Story 7-3)
     * @param {string} name - Player name to store
     */
    function storePlayerName(name) {
        try {
            localStorage.setItem(STORAGE_KEY_NAME, name);
            localStorage.setItem(STORAGE_KEY_GAME_ID, gameId);
            console.log('[Beatify] Stored player name:', name, 'for game:', gameId);
        } catch (e) {
            console.error('[Beatify] Failed to store player name:', e);
        }
    }

    /**
     * Clear stored player name (Story 7-3)
     */
    function clearStoredPlayerName() {
        try {
            localStorage.removeItem(STORAGE_KEY_NAME);
            localStorage.removeItem(STORAGE_KEY_GAME_ID);
        } catch (e) {
            // localStorage unavailable
        }
    }

    /**
     * Show reconnecting overlay (Story 7-3)
     */
    function showReconnectingOverlay() {
        var overlay = document.getElementById('reconnecting-overlay');
        if (overlay) {
            overlay.classList.remove('hidden');
        }
    }

    /**
     * Hide reconnecting overlay (Story 7-3)
     */
    function hideReconnectingOverlay() {
        var overlay = document.getElementById('reconnecting-overlay');
        if (overlay) {
            overlay.classList.add('hidden');
        }
    }

    /**
     * Update reconnecting overlay status (Story 7-3)
     * @param {number} attempt - Current attempt number
     */
    function updateReconnectStatus(attempt) {
        var statusEl = document.getElementById('reconnect-status');
        if (statusEl) {
            statusEl.textContent = 'Reconnecting... (Attempt ' + attempt + '/' + MAX_RECONNECT_ATTEMPTS + ')';
        }
    }

    /**
     * Show connection lost view (Story 7-4)
     */
    function showConnectionLostView() {
        showView('connection-lost-view');
    }

    /**
     * Setup retry connection button (Story 7-4)
     */
    function setupRetryConnection() {
        var retryBtn = document.getElementById('retry-connection-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', function() {
                if (playerName) {
                    reconnectAttempts = 0;
                    showView('loading-view');
                    connectWebSocket(playerName);
                } else {
                    // No player name - go back to join view
                    checkGameStatus();
                }
            });
        }
    }

    /**
     * Connect to WebSocket and send join message
     * @param {string} name - Player name
     */
    function connectWebSocket(name) {
        playerName = name;
        // Store name for reconnection (Story 7-3)
        storePlayerName(name);

        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            reconnectAttempts = 0;
            isReconnecting = false;
            hideReconnectingOverlay();

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
            // Story 11.5: Skip auto-reconnect if user intentionally left
            if (intentionalLeave) {
                intentionalLeave = false;  // Reset flag
                return;
            }
            // Attempt reconnection if we were connected and have a name
            if (playerName && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                isReconnecting = true;
                reconnectAttempts++;
                showReconnectingOverlay();
                updateReconnectStatus(reconnectAttempts);

                const delay = getReconnectDelay();
                console.log('WebSocket closed. Reconnecting in ' + delay + 'ms... (attempt ' + reconnectAttempts + ')');
                setTimeout(function() { connectWebSocket(playerName); }, delay);
            } else if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
                // Max attempts reached - show connection lost view (Story 7-4)
                isReconnecting = false;
                hideReconnectingOverlay();
                showConnectionLostView();
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
            // Update isAdmin from players list (Story 6.1)
            var players = data.players || [];
            var currentPlayer = players.find(function(p) { return p.name === playerName; });
            if (currentPlayer) {
                isAdmin = currentPlayer.is_admin === true;
            }

            if (data.phase === 'LOBBY') {
                stopCountdown();
                hideAdminControlBar();  // Story 6.1
                currentRoundNumber = 0;  // Reset for new game
                setEnergyLevel('warmup');  // Story 9.9
                showView('lobby-view');
                renderPlayerList(players);
                // Render QR code with join URL
                if (data.join_url) {
                    renderQRCode(data.join_url);
                }
                // Update admin controls visibility
                updateAdminControls(players);
            } else if (data.phase === 'PLAYING') {
                // Only reset submission state when round actually changes
                var newRound = data.round || 1;
                if (newRound !== currentRoundNumber) {
                    currentRoundNumber = newRound;
                    resetSubmissionState();  // Reset for new round
                }
                setEnergyLevel('party');  // Story 9.9
                showView('game-view');
                updateGameView(data);
                if (data.deadline) {
                    startCountdown(data.deadline);
                }
                initYearSelector();
                setupLeaderboardToggle();  // Story 5.5
                // Show admin control bar (Story 6.1)
                showAdminControlBar();
                updateControlBarState('PLAYING');
            } else if (data.phase === 'REVEAL') {
                stopCountdown();
                setEnergyLevel('party');  // Story 9.9 - maintain party for reveal
                showView('reveal-view');
                updateRevealView(data);
                // Show admin control bar (Story 6.1)
                showAdminControlBar();
                updateControlBarState('REVEAL');
            } else if (data.phase === 'PAUSED') {
                // Story 7-1: Show paused view
                stopCountdown();
                hideAdminControlBar();
                setEnergyLevel('warmup');  // Story 9.9 - lower energy during pause
                showView('paused-view');
                updatePausedView(data);
            } else if (data.phase === 'END') {
                stopCountdown();
                hideAdminControlBar();  // Story 6.1
                currentRoundNumber = 0;  // Reset for potential new game
                setEnergyLevel('warmup');  // Story 9.9 - final standings, lower energy
                showView('end-view');
                updateEndView(data);  // Story 5.6
                // Clear stored player name (game is over - Story 7-3)
                clearStoredPlayerName();
            }
        } else if (data.type === 'join_ack') {
            // Handle join acknowledgment with session_id (Story 11.1)
            if (data.session_id) {
                setSessionCookie(data.session_id);
            }
        } else if (data.type === 'reconnect_ack') {
            // Handle session-based reconnect acknowledgment (Story 11.2)
            if (data.success && data.name) {
                playerName = data.name;
                storePlayerName(data.name);
                showWelcomeBackToast(data.name);
                // State message will follow with full game state
            }
        } else if (data.type === 'submit_ack') {
            // Handle successful guess submission
            handleSubmitAck();
        } else if (data.type === 'error') {
            // Handle submission-related errors
            if (data.code === 'ROUND_EXPIRED' || data.code === 'ALREADY_SUBMITTED') {
                handleSubmitError(data);
                return;
            }
            // Handle GAME_ENDED error specially
            if (data.code === 'GAME_ENDED') {
                showView('end-view');
                return;
            }
            // Handle NOT_ADMIN error (Story 6.1)
            if (data.code === 'NOT_ADMIN') {
                isAdmin = false;
                hideAdminControlBar();
                console.warn('Admin action rejected: not admin');
                return;
            }
            // Handle SESSION_TAKEOVER - another tab took over (Story 11.2)
            if (data.code === 'SESSION_TAKEOVER') {
                isReconnecting = false;
                hideReconnectingOverlay();
                // Don't clear session cookie - other tab is using it
                playerName = null;
                showConnectionLostView();
                console.warn('Session taken over by another tab');
                return;
            }
            // Handle SESSION_NOT_FOUND - session expired or game reset (Story 11.2)
            if (data.code === 'SESSION_NOT_FOUND') {
                clearSessionCookie();
                // Prevent reconnect attempts by reusing intentionalLeave flag
                intentionalLeave = true;
                // Close WebSocket cleanly to prevent onclose reconnect
                if (ws) {
                    ws.close();
                }
                // Fall back to join form
                showView('join-view');
                return;
            }
            // Handle ADMIN_CANNOT_LEAVE - host tried to leave (Story 11.5)
            if (data.code === 'ADMIN_CANNOT_LEAVE') {
                // Reset intentional leave flag since action was blocked
                intentionalLeave = false;
                // Show user-friendly error message
                alert(data.message || 'Host cannot leave. End the game instead.');
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
        } else if (data.type === 'song_stopped') {
            // Story 6.2 - handle song stopped notification
            handleSongStopped();
        } else if (data.type === 'volume_changed') {
            // Story 6.4 - handle volume changed response
            handleVolumeChanged(data.level);
        } else if (data.type === 'game_ended') {
            // Story 7-5 - game has fully ended
            handleGameEnded();
        } else if (data.type === 'left') {
            // Story 11.5 - player left game successfully
            handleLeftGame();
        }
    }

    /**
     * Handle successful leave game response (Story 11.5)
     */
    function handleLeftGame() {
        // Clear all stored session data
        clearStoredPlayerName();
        clearSessionCookie();

        // Reset local state
        playerName = null;
        isAdmin = false;

        // Show join view for potential rejoin
        showView('join-view');
    }

    /**
     * Handle leave game button click (Story 11.5)
     */
    function handleLeaveGame() {
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            return;
        }

        // Safety check - admin shouldn't see button, but double-check
        if (isAdmin) {
            alert('Host cannot leave. End the game instead.');
            return;
        }

        // Confirmation dialog per AC #1
        if (!confirm('Leave the game? Your score will be lost.')) {
            return;
        }

        // Set intentional leave flag to prevent auto-reconnect
        intentionalLeave = true;

        // Send leave message to server
        ws.send(JSON.stringify({ type: 'leave' }));
    }

    /**
     * Handle game ended notification (Story 7-5)
     */
    function handleGameEnded() {
        // Clear all stored session data
        clearStoredPlayerName();
        clearSessionCookie();  // Story 11.1 - clear session cookie on game end
        try {
            sessionStorage.removeItem('beatify_admin_name');
            sessionStorage.removeItem('beatify_is_admin');
        } catch (e) {
            // Ignore storage errors
        }

        // Reset local state
        playerName = null;
        isAdmin = false;

        // Close WebSocket to prevent stale connections
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.close();
        }
        ws = null;

        // If already showing end view, just update the message
        if (!endView || !endView.classList.contains('hidden')) {
            return;
        }

        // Update end message with rejoin hint
        var endMessage = document.getElementById('end-player-message');
        if (endMessage) {
            endMessage.innerHTML =
                '<p>Thanks for playing!</p>' +
                '<p class="rejoin-hint">Scan the QR code again to join the next game.</p>';
            endMessage.classList.remove('hidden');
        }

        showView('end-view');
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

    // Wrap showView to auto-focus name input and set energy level (Story 9.9)
    const originalShowView = showView;
    showView = function(viewId) {
        originalShowView(viewId);

        // Set calm energy for entry screens (Story 9.9)
        if (viewId === 'join-view' || viewId === 'loading-view' ||
            viewId === 'not-found-view' || viewId === 'ended-view' ||
            viewId === 'in-progress-view' || viewId === 'connection-lost-view') {
            setEnergyLevel('calm');
        }

        if (viewId === 'join-view') {
            setTimeout(function() {
                var nameInput = document.getElementById('name-input');
                if (nameInput) nameInput.focus();
            }, 100);
        }
    };

    // ============================================
    // Energy Escalation System (Story 9.9)
    // ============================================

    /**
     * Set energy level class on body based on game phase
     * @param {string} level - 'calm', 'warmup', or 'party'
     */
    function setEnergyLevel(level) {
        document.body.classList.remove('energy-calm', 'energy-warmup', 'energy-party');
        document.body.classList.add('energy-' + level);
    }

    // ============================================
    // Confetti System (Story 9.4)
    // ============================================

    /**
     * Lightweight canvas confetti for exact match celebration
     */
    var confettiCanvas = null;
    var confettiCtx = null;
    var confettiParticles = [];
    var confettiAnimationId = null;

    /**
     * Initialize confetti canvas
     */
    function initConfetti() {
        confettiCanvas = document.getElementById('confetti-canvas');
        if (confettiCanvas) {
            confettiCtx = confettiCanvas.getContext('2d');
            resizeConfettiCanvas();
            window.addEventListener('resize', resizeConfettiCanvas);
        }
    }

    /**
     * Resize confetti canvas to match window
     */
    function resizeConfettiCanvas() {
        if (confettiCanvas) {
            confettiCanvas.width = window.innerWidth;
            confettiCanvas.height = window.innerHeight;
        }
    }

    /**
     * Create confetti particle
     */
    function createConfettiParticle() {
        var colors = ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00', '#ff6600'];
        return {
            x: Math.random() * confettiCanvas.width,
            y: -20,
            size: Math.random() * 10 + 5,
            color: colors[Math.floor(Math.random() * colors.length)],
            speedY: Math.random() * 3 + 2,
            speedX: Math.random() * 4 - 2,
            rotation: Math.random() * 360,
            rotationSpeed: Math.random() * 10 - 5
        };
    }

    /**
     * Trigger confetti animation
     */
    function triggerConfetti() {
        // Check for reduced motion preference
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            // Show static celebration icon instead
            showStaticCelebration();
            return;
        }

        if (!confettiCanvas || !confettiCtx) {
            initConfetti();
        }

        // Create particles
        confettiParticles = [];
        for (var i = 0; i < 100; i++) {
            confettiParticles.push(createConfettiParticle());
        }

        // Start animation
        animateConfetti();

        // Auto-clear after 3 seconds
        setTimeout(stopConfetti, 3000);
    }

    /**
     * Animate confetti particles
     */
    function animateConfetti() {
        if (!confettiCtx || confettiParticles.length === 0) return;

        confettiCtx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);

        confettiParticles.forEach(function(p) {
            p.y += p.speedY;
            p.x += p.speedX;
            p.rotation += p.rotationSpeed;

            confettiCtx.save();
            confettiCtx.translate(p.x, p.y);
            confettiCtx.rotate(p.rotation * Math.PI / 180);
            confettiCtx.fillStyle = p.color;
            confettiCtx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size);
            confettiCtx.restore();
        });

        // Remove off-screen particles
        confettiParticles = confettiParticles.filter(function(p) {
            return p.y < confettiCanvas.height + 20;
        });

        if (confettiParticles.length > 0) {
            confettiAnimationId = requestAnimationFrame(animateConfetti);
        }
    }

    /**
     * Stop confetti animation
     */
    function stopConfetti() {
        if (confettiAnimationId) {
            cancelAnimationFrame(confettiAnimationId);
            confettiAnimationId = null;
        }
        confettiParticles = [];
        if (confettiCtx && confettiCanvas) {
            confettiCtx.clearRect(0, 0, confettiCanvas.width, confettiCanvas.height);
        }
    }

    /**
     * Show static celebration for reduced motion users
     */
    function showStaticCelebration() {
        var emotionEl = document.getElementById('reveal-emotion');
        if (emotionEl) {
            // Add a static celebration icon
            var existingIcon = emotionEl.querySelector('.celebration-icon');
            if (!existingIcon) {
                var icon = document.createElement('span');
                icon.className = 'celebration-icon';
                icon.textContent = ' 🎉';
                emotionEl.appendChild(icon);
            }
        }
    }

    /**
     * Setup reveal view event handlers
     */
    function setupRevealControls() {
        var nextRoundBtn = document.getElementById('next-round-btn');
        if (nextRoundBtn) {
            nextRoundBtn.addEventListener('click', handleNextRound);
        }
    }

    // Initialize form, QR modal, and admin controls when DOM ready
    function initAll() {
        setupJoinForm();
        setupQRModal();
        setupAdminControls();
        setupRevealControls();
        setupAdminControlBar();  // Story 6.1
        setupRetryConnection();  // Story 7-4
        initConfetti();  // Story 9.4

        // Check if this is an admin redirect
        if (checkAdminStatus() && playerName) {
            // Auto-connect as admin
            connectWebSocket(playerName);
            return;
        }

        // Auto-reconnect from localStorage on page reload (Story 7-3)
        var storedName = getStoredPlayerName();
        if (storedName && gameId) {
            console.log('[Beatify] Auto-reconnecting as:', storedName);
            // Auto-connect with stored name
            connectWebSocket(storedName);
            return;
        }

        // No stored name - prefill form if we have a partial match
        if (storedName) {
            var nameInput = document.getElementById('name-input');
            var joinBtn = document.getElementById('join-btn');
            if (nameInput) {
                nameInput.value = storedName;
                if (joinBtn) {
                    var result = validateName(storedName);
                    joinBtn.disabled = !result.valid;
                }
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }

})();
