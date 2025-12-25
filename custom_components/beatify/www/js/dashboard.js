/**
 * Beatify Dashboard - Spectator Display (Story 10.4)
 * Read-only observer that connects to WebSocket and displays game state
 */
(function() {
    'use strict';

    // View elements
    var loadingView = document.getElementById('dashboard-loading');
    var noGameView = document.getElementById('dashboard-no-game');
    var lobbyView = document.getElementById('dashboard-lobby');
    var playingView = document.getElementById('dashboard-playing');
    var revealView = document.getElementById('dashboard-reveal');
    var endView = document.getElementById('dashboard-end');
    var pausedView = document.getElementById('dashboard-paused');

    // WebSocket connection
    var ws = null;
    var reconnectAttempts = 0;
    var MAX_RECONNECT_ATTEMPTS = 20;
    var MAX_RECONNECT_DELAY_MS = 30000;

    // State tracking
    var previousPlayers = [];
    var countdownInterval = null;
    var lastQRCodeUrl = null;

    /**
     * Show a specific view and hide all others
     * @param {string} viewId - ID of view to show
     */
    function showView(viewId) {
        var views = [loadingView, noGameView, lobbyView, playingView, revealView, endView, pausedView];
        views.forEach(function(v) {
            if (v) {
                v.classList.add('hidden');
            }
        });
        var view = document.getElementById(viewId);
        if (view) {
            view.classList.remove('hidden');
        }
    }

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Get reconnection delay with exponential backoff
     * @returns {number} Delay in milliseconds
     */
    function getReconnectDelay() {
        return Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY_MS);
    }

    /**
     * Connect to WebSocket as read-only observer (AC 10.4.1)
     */
    function connectWebSocket() {
        var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

        ws = new WebSocket(wsUrl);

        ws.onopen = function() {
            console.log('[Dashboard] WebSocket connected');
            reconnectAttempts = 0;
            // Request current state as read-only observer
            ws.send(JSON.stringify({ type: 'get_state' }));
        };

        ws.onmessage = function(event) {
            try {
                var data = JSON.parse(event.data);
                handleServerMessage(data);
            } catch (e) {
                console.error('[Dashboard] Failed to parse message:', e);
            }
        };

        ws.onclose = function() {
            console.log('[Dashboard] WebSocket closed');
            if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                reconnectAttempts++;
                var delay = getReconnectDelay();
                console.log('[Dashboard] Reconnecting in ' + delay + 'ms (attempt ' + reconnectAttempts + ')');
                setTimeout(connectWebSocket, delay);
            } else {
                showView('dashboard-no-game');
            }
        };

        ws.onerror = function(err) {
            console.error('[Dashboard] WebSocket error:', err);
        };
    }

    /**
     * Handle messages from server
     * @param {Object} data - Parsed message data
     */
    function handleServerMessage(data) {
        if (data.type === 'state') {
            handleStateUpdate(data);
        } else if (data.type === 'error') {
            console.log('[Dashboard] Server error:', data.message);
            // Dashboard ignores most errors since it's read-only
        }
        // Dashboard ignores submit_ack, song_stopped, volume_changed since it doesn't interact
    }

    /**
     * Handle state update from server
     * @param {Object} data - State data
     */
    function handleStateUpdate(data) {
        var phase = data.phase;

        if (!phase || phase === 'END' && !data.game_id) {
            // No active game
            showView('dashboard-no-game');
            stopCountdown();
            return;
        }

        switch (phase) {
            case 'LOBBY':
                stopCountdown();
                showView('dashboard-lobby');
                renderLobbyView(data);
                break;
            case 'PLAYING':
                showView('dashboard-playing');
                renderPlayingView(data);
                break;
            case 'REVEAL':
                stopCountdown();
                showView('dashboard-reveal');
                renderRevealView(data);
                break;
            case 'END':
                stopCountdown();
                showView('dashboard-end');
                renderEndView(data);
                break;
            case 'PAUSED':
                stopCountdown();
                showView('dashboard-paused');
                break;
            default:
                console.log('[Dashboard] Unknown phase:', phase);
        }
    }

    // ============================================
    // Lobby View (AC 10.4.2)
    // ============================================

    /**
     * Render lobby view with QR code and player list
     * @param {Object} data - State data
     */
    function renderLobbyView(data) {
        var players = data.players || [];

        // Render QR code
        if (data.join_url) {
            renderQRCode(data.join_url);
        }

        // Update player count
        var countEl = document.getElementById('dashboard-player-count');
        if (countEl) {
            var count = players.length;
            countEl.textContent = count + ' player' + (count !== 1 ? 's' : '') + ' joined';
        }

        // Render player list with slide-in animation
        renderPlayerList(players);
    }

    /**
     * Render QR code for joining game
     * @param {string} joinUrl - URL to encode
     */
    function renderQRCode(joinUrl) {
        var container = document.getElementById('dashboard-qr-code');
        if (!container) return;

        // Skip re-render if URL hasn't changed (prevents flicker)
        if (joinUrl === lastQRCodeUrl) return;
        lastQRCodeUrl = joinUrl;

        // Clear previous
        container.innerHTML = '';

        if (typeof QRCode !== 'undefined') {
            new QRCode(container, {
                text: joinUrl,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M
            });
        } else {
            container.innerHTML = '<p>QR code unavailable</p>';
        }
    }

    /**
     * Render player list in lobby
     * @param {Array} players - Array of player objects
     */
    function renderPlayerList(players) {
        var listEl = document.getElementById('dashboard-player-list');
        if (!listEl) return;

        // Story 11.4: Sort players - connected first, then disconnected
        var sortedPlayers = players.slice().sort(function(a, b) {
            if (a.connected !== b.connected) {
                return a.connected ? -1 : 1;
            }
            return 0;
        });

        // Find new players
        var previousNames = previousPlayers.map(function(p) { return p.name; });
        var newNames = sortedPlayers
            .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
            .map(function(p) { return p.name; });

        // Render player cards
        listEl.innerHTML = sortedPlayers.map(function(player) {
            var isNew = newNames.indexOf(player.name) !== -1;
            var isDisconnected = player.connected === false;
            var classes = ['dashboard-player-card'];
            if (isNew) classes.push('is-new');
            if (isDisconnected) classes.push('dashboard-player-card--disconnected');

            var awayBadge = isDisconnected ? '<span class="away-badge">(away)</span>' : '';

            return '<div class="' + classes.join(' ') + '">' +
                escapeHtml(player.name) + awayBadge +
            '</div>';
        }).join('');

        // Remove is-new class after animation
        setTimeout(function() {
            var newCards = listEl.querySelectorAll('.is-new');
            for (var i = 0; i < newCards.length; i++) {
                newCards[i].classList.remove('is-new');
            }
        }, 2000);

        previousPlayers = players.slice();
    }

    // ============================================
    // Playing View (AC 10.4.3)
    // ============================================

    /**
     * Render playing view with blurred album art, timer, and leaderboard
     * @param {Object} data - State data
     */
    function renderPlayingView(data) {
        var song = data.song || {};
        var players = data.players || [];

        // Update round indicator
        var currentRound = document.getElementById('dashboard-current-round');
        var totalRounds = document.getElementById('dashboard-total-rounds');
        if (currentRound) currentRound.textContent = data.round || 1;
        if (totalRounds) totalRounds.textContent = data.total_rounds || 10;

        // Update album art (blurred - AC 10.4.3)
        var albumArt = document.getElementById('dashboard-album-art');
        if (albumArt) {
            albumArt.src = song.album_art || '/beatify/static/img/no-artwork.svg';
            albumArt.onerror = function() {
                this.src = '/beatify/static/img/no-artwork.svg';
            };
        }

        // Start countdown
        if (data.deadline) {
            startCountdown(data.deadline);
        }

        // Render leaderboard with submission indicators and bet badges
        renderLeaderboard(data.leaderboard || [], players, 'dashboard-leaderboard', true, true);
    }

    /**
     * Start countdown timer (AC 10.4.3)
     * @param {number} deadline - Server deadline timestamp in milliseconds
     */
    function startCountdown(deadline) {
        stopCountdown();

        var timerElement = document.getElementById('dashboard-timer');
        if (!timerElement) return;

        timerElement.classList.remove('timer--warning', 'timer--critical');

        function updateCountdown() {
            var now = Date.now();
            var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

            timerElement.textContent = remaining;

            // Update timer style based on remaining time (AC 10.4.3)
            if (remaining <= 5) {
                timerElement.classList.remove('timer--warning');
                timerElement.classList.add('timer--critical');
            } else if (remaining <= 10) {
                timerElement.classList.remove('timer--critical');
                timerElement.classList.add('timer--warning');
            } else {
                timerElement.classList.remove('timer--warning', 'timer--critical');
            }

            if (remaining <= 0) {
                stopCountdown();
            }
        }

        updateCountdown();
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
     * Render leaderboard
     * @param {Array} leaderboard - Leaderboard entries
     * @param {Array} players - Players list (for submission status)
     * @param {string} containerId - Container element ID
     * @param {boolean} showSubmitted - Whether to show submission indicators
     * @param {boolean} showBet - Whether to show bet badges next to names
     */
    function renderLeaderboard(leaderboard, players, containerId, showSubmitted, showBet) {
        var container = document.getElementById(containerId);
        if (!container) return;

        // Build player submission and bet maps
        var submissionMap = {};
        var betMap = {};
        if (players) {
            players.forEach(function(p) {
                submissionMap[p.name] = p.submitted;
                betMap[p.name] = p.bet;
            });
        }

        var html = '';
        leaderboard.forEach(function(entry) {
            var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';

            // Rank change animation class
            var animationClass = '';
            if (entry.rank_change > 0) {
                animationClass = 'leaderboard-entry--climbing';
            } else if (entry.rank_change < 0) {
                animationClass = 'leaderboard-entry--falling';
            }

            // Story 11.4: Disconnected player styling
            var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

            // Rank change indicator (AC 10.4.4 - with arrows)
            var changeIndicator = '';
            if (entry.rank_change > 0) {
                changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
            } else if (entry.rank_change < 0) {
                changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';
            }

            // Streak indicator (AC 10.4.3 - with fire emoji)
            var streakIndicator = '';
            if (entry.streak >= 2) {
                var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
                streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
            }

            // Bet badge next to name during playing phase
            var betBadge = '';
            if (showBet && betMap[entry.name]) {
                betBadge = '<span class="bet-badge">BET</span>';
            }

            // Submission indicator (AC 10.4.3)
            var submittedIndicator = '';
            if (showSubmitted) {
                var isSubmitted = submissionMap[entry.name] === true;
                submittedIndicator = '<div class="entry-submitted ' + (isSubmitted ? 'is-submitted' : '') + '"></div>';
            }

            html += '<div class="leaderboard-entry ' + rankClass + ' ' + animationClass + ' ' + disconnectedClass + '">' +
                '<span class="entry-rank">#' + entry.rank + '</span>' +
                '<span class="entry-name">' + escapeHtml(entry.name) + awayBadge + betBadge + '</span>' +
                '<span class="entry-meta">' +
                    streakIndicator +
                    changeIndicator +
                '</span>' +
                '<span class="entry-score">' + entry.score + '</span>' +
                submittedIndicator +
            '</div>';
        });

        container.innerHTML = html;
    }

    // ============================================
    // Reveal View (AC 10.4.4)
    // ============================================

    /**
     * Render reveal view with song info and leaderboard
     * @param {Object} data - State data
     */
    function renderRevealView(data) {
        var song = data.song || {};
        var players = data.players || [];

        // Update album art (clear - no blur)
        var albumArt = document.getElementById('reveal-album-art');
        if (albumArt) {
            albumArt.src = song.album_art || '/beatify/static/img/no-artwork.svg';
            albumArt.onerror = function() {
                this.src = '/beatify/static/img/no-artwork.svg';
            };
        }

        // Update song info
        var artistEl = document.getElementById('reveal-artist');
        var titleEl = document.getElementById('reveal-title');
        var yearEl = document.getElementById('reveal-year');

        if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';
        if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
        if (yearEl) yearEl.textContent = song.year || '????';

        // Render top 3 guesses this round (AC 10.4.4)
        renderTopGuesses(players);

        // Render leaderboard with position changes
        renderRevealLeaderboard(data.leaderboard || []);
    }

    /**
     * Render top 3 guesses this round
     * @param {Array} players - Players with round results
     */
    function renderTopGuesses(players) {
        var container = document.getElementById('reveal-top-guesses-list');
        if (!container) return;

        // Sort by round_score descending, take top 3
        var sorted = players
            .filter(function(p) { return !p.missed_round; })
            .sort(function(a, b) {
                return (b.round_score || 0) - (a.round_score || 0);
            })
            .slice(0, 3);

        var html = '';
        sorted.forEach(function(player, index) {
            // Show guessed year in brackets
            var yearDisplay = player.guess ? '<span class="top-guess-year">(' + player.guess + ')</span>' : '';

            // Show BET badge with outcome
            var betBadge = '';
            if (player.bet) {
                var badgeClass = 'bet-badge';
                if (player.bet_outcome === 'won') badgeClass += ' bet-badge--won';
                else if (player.bet_outcome === 'lost') badgeClass += ' bet-badge--lost';
                betBadge = '<span class="' + badgeClass + '">BET</span>';
            }

            html += '<div class="top-guess-entry">' +
                '<span class="top-guess-rank">#' + (index + 1) + '</span>' +
                '<span class="top-guess-name">' + escapeHtml(player.name) + yearDisplay + '</span>' +
                '<span class="top-guess-points">+' + (player.round_score || 0) + betBadge + '</span>' +
            '</div>';
        });

        container.innerHTML = html;
    }

    /**
     * Render reveal leaderboard with position change indicators (AC 10.4.4)
     * @param {Array} leaderboard - Leaderboard entries
     */
    function renderRevealLeaderboard(leaderboard) {
        var container = document.getElementById('reveal-leaderboard');
        if (!container) return;

        var html = '';
        leaderboard.forEach(function(entry) {
            var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';

            // Rank change animation
            var animationClass = '';
            if (entry.rank_change > 0) {
                animationClass = 'leaderboard-entry--climbing';
            } else if (entry.rank_change < 0) {
                animationClass = 'leaderboard-entry--falling';
            }

            // Story 11.4: Disconnected player styling
            var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
            var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

            // Position change indicator (AC 10.4.4 - with arrows)
            var changeHtml = '';
            if (entry.rank_change > 0) {
                changeHtml = '<span class="entry-change is-positive">▲' + entry.rank_change + '</span>';
            } else if (entry.rank_change < 0) {
                changeHtml = '<span class="entry-change is-negative">▼' + Math.abs(entry.rank_change) + '</span>';
            }

            // Streak indicator (AC 10.4.3 - with fire emoji)
            var streakIndicator = '';
            if (entry.streak >= 2) {
                var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
                streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
            }

            html += '<div class="leaderboard-entry ' + rankClass + ' ' + animationClass + ' ' + disconnectedClass + '">' +
                '<span class="entry-rank">#' + entry.rank + '</span>' +
                '<span class="entry-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
                '<span class="entry-meta">' +
                    streakIndicator +
                    changeHtml +
                '</span>' +
                '<span class="entry-score">' + entry.score + '</span>' +
            '</div>';
        });

        container.innerHTML = html;
    }

    // ============================================
    // End View (AC 10.4.5)
    // ============================================

    /**
     * Render end view with podium and final leaderboard
     * @param {Object} data - State data
     */
    function renderEndView(data) {
        var leaderboard = data.leaderboard || [];

        // Update podium (AC 10.4.5)
        [1, 2, 3].forEach(function(place) {
            var player = leaderboard.find(function(p) { return p.rank === place; });
            var nameEl = document.getElementById('end-podium-' + place + '-name');
            var scoreEl = document.getElementById('end-podium-' + place + '-score');

            if (nameEl) nameEl.textContent = player ? escapeHtml(player.name) : '---';
            if (scoreEl) scoreEl.textContent = player ? player.score : '0';
        });

        // Render full leaderboard (Story 11.4: disconnected styling)
        var container = document.getElementById('end-leaderboard');
        if (container) {
            var html = '';
            leaderboard.forEach(function(entry) {
                var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
                var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
                var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

                html += '<div class="leaderboard-entry ' + rankClass + ' ' + disconnectedClass + '">' +
                    '<span class="entry-rank">#' + entry.rank + '</span>' +
                    '<span class="entry-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
                    '<span class="entry-score">' + entry.score + '</span>' +
                '</div>';
            });

            container.innerHTML = html;
        }
    }

    // ============================================
    // Initialization
    // ============================================

    /**
     * Initialize dashboard
     */
    function init() {
        console.log('[Dashboard] Initializing...');
        connectWebSocket();
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
