/**
 * Beatify Dashboard - Spectator Display (Story 10.4)
 * Read-only observer that connects to WebSocket and displays game state
 */
(function() {
    'use strict';

    // Alias BeatifyUtils for convenience
    var utils = window.BeatifyUtils || {};

    // View elements
    var loadingView = document.getElementById('dashboard-loading');
    var noGameView = document.getElementById('dashboard-no-game');
    var lobbyView = document.getElementById('dashboard-lobby');
    var playingView = document.getElementById('dashboard-playing');
    var revealView = document.getElementById('dashboard-reveal');
    var endView = document.getElementById('dashboard-end');
    var pausedView = document.getElementById('dashboard-paused');

    // All views array for showView helper
    var allViews = [loadingView, noGameView, lobbyView, playingView, revealView, endView, pausedView];

    // WebSocket connection
    var ws = null;
    var reconnectAttempts = 0;
    var MAX_RECONNECT_ATTEMPTS = 20;
    var MAX_RECONNECT_DELAY_MS = 30000;

    // State tracking
    var previousPlayers = [];
    var countdownInterval = null;
    var lastQRCodeUrl = null;

    // Utility functions from BeatifyUtils
    // waitForI18n, t, getLocalizedSongField, escapeHtml moved to BeatifyUtils

    /**
     * Show a specific view and hide all others
     * @param {string} viewId - ID of view to show
     */
    function showView(viewId) {
        utils.showView(allViews, viewId);
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
            // Debug: Log game_performance data (Story 14.4)
            if (data.game_performance) {
                console.log('[Dashboard] game_performance:', data.game_performance);
            }
            handleStateUpdate(data);
        } else if (data.type === 'error') {
            console.log('[Dashboard] Server error:', data.message);
            // Dashboard ignores most errors since it's read-only
        } else if (data.type === 'player_reaction') {
            // Live reactions from players (Story 18.9)
            showFloatingReaction(data.player_name, data.emoji);
        } else if (data.type === 'metadata_update') {
            // Issue #42: Handle async metadata update for fast transitions
            handleMetadataUpdate(data.song);
        }
        // Dashboard ignores submit_ack, song_stopped, volume_changed since it doesn't interact
    }

    /**
     * Handle async metadata update for fast transitions (Issue #42)
     * Updates album art with fade transition when metadata becomes available
     * @param {Object} song - Song metadata with artist, title, album_art
     */
    function handleMetadataUpdate(song) {
        if (!song) return;

        var albumArt = document.getElementById('dashboard-album-art');
        if (albumArt && song.album_art) {
            var newSrc = song.album_art;

            // Skip if already showing this image
            if (albumArt.src === newSrc) return;

            // Fade transition for smooth update
            albumArt.style.transition = 'opacity 0.3s ease-in-out';
            albumArt.style.opacity = '0.5';

            // Preload and swap
            var preloader = new Image();
            preloader.onload = function() {
                albumArt.src = newSrc;
                albumArt.style.opacity = '1';
            };
            preloader.onerror = function() {
                albumArt.src = '/beatify/static/img/no-artwork.svg';
                albumArt.style.opacity = '1';
            };
            preloader.src = newSrc;
        }

        console.log('[Dashboard] Metadata updated:', song.artist, '-', song.title);
    }

    /**
     * Handle state update from server
     * @param {Object} data - State data
     */
    function handleStateUpdate(data) {
        var phase = data.phase;

        // Apply language from game state (Story 12.5, 16.3)
        // Must re-render after language loads to update dynamic content
        // Guard: skip if i18n unavailable
        if (typeof BeatifyI18n !== 'undefined' && data.language && data.language !== BeatifyI18n.getLanguage()) {
            BeatifyI18n.setLanguage(data.language).then(function() {
                BeatifyI18n.initPageTranslations();
                // Re-render current view with correct language
                handleStateUpdate(data);
            });
            // Don't render yet - wait for language to load
            return;
        }

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

        // Render game settings indicator (top-right corner)
        renderGameSettings(data);

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
     * Render game settings indicator (rounds, difficulty)
     * @param {Object} data - State data with total_rounds and difficulty
     */
    function renderGameSettings(data) {
        var el = document.getElementById('dashboard-game-settings');
        if (!el) return;

        var rounds = data.total_rounds || 10;
        var difficulty = data.difficulty || 'normal';

        // Translate difficulty label
        var difficultyLabel = t('admin.difficulty' + difficulty.charAt(0).toUpperCase() + difficulty.slice(1), difficulty);

        el.textContent = rounds + ' ' + utils.t('dashboard.rounds', 'rounds') + ' • ' + difficultyLabel;
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
                utils.escapeHtml(player.name) + awayBadge +
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

        // Issue #23: Show/hide intro round badge
        var introBadge = document.getElementById('dashboard-intro-badge');
        if (introBadge) {
            if (data.is_intro_round) {
                introBadge.classList.remove('hidden');
                var badgeText = introBadge.querySelector('[data-i18n]');
                if (data.intro_stopped) {
                    introBadge.classList.add('intro-badge--stopped');
                    if (badgeText) {
                        badgeText.setAttribute('data-i18n', 'game.introStopped');
                        badgeText.textContent = utils.t('game.introStopped') || 'Intro complete!';
                    }
                } else {
                    introBadge.classList.remove('intro-badge--stopped');
                    if (badgeText) {
                        badgeText.setAttribute('data-i18n', 'game.introRound');
                        badgeText.textContent = utils.t('game.introRound') || 'INTRO ROUND';
                    }
                }
            } else {
                introBadge.classList.add('hidden');
                introBadge.classList.remove('intro-badge--stopped');
            }
        }

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

        // Update round statistics (Story 16.4)
        renderRoundStats(data, players);
    }

    /**
     * Render round statistics below leaderboard (Story 16.4)
     * @param {Object} data - State data
     * @param {Array} players - Players array
     */
    function renderRoundStats(data, players) {
        console.log('[Dashboard] renderRoundStats called, players:', players);
        console.log('[Dashboard] data.players:', data.players);

        // Calculate submission count
        var submitted = 0;
        var total = players.length;
        players.forEach(function(p) {
            if (p.submitted) submitted++;
        });

        console.log('[Dashboard] Submissions:', submitted, '/', total);

        var submissionsEl = document.getElementById('dashboard-submissions');
        if (submissionsEl) {
            submissionsEl.textContent = submitted + '/' + total;
            console.log('[Dashboard] Updated submissions element');
        } else {
            console.warn('[Dashboard] dashboard-submissions element not found');
        }

        // Time remaining is already shown in the main timer, but we update the stat too
        var timeEl = document.getElementById('dashboard-time-remaining');
        if (timeEl && data.deadline) {
            var remaining = Math.max(0, Math.ceil((data.deadline - Date.now()) / 1000));
            timeEl.textContent = remaining + 's';
        }
    }

    /**
     * Start countdown timer (AC 10.4.3)
     * @param {number} deadline - Server deadline timestamp in milliseconds
     */
    function startCountdown(deadline) {
        stopCountdown();

        var timerElement = document.getElementById('dashboard-timer');
        var timeStatEl = document.getElementById('dashboard-time-remaining');
        if (!timerElement) return;

        timerElement.classList.remove('timer--warning', 'timer--critical');

        function updateCountdown() {
            var now = Date.now();
            var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

            timerElement.textContent = remaining;

            // Also update round stats time (Story 16.4)
            if (timeStatEl) {
                timeStatEl.textContent = remaining + 's';
            }

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
                '<span class="entry-name">' + utils.escapeHtml(entry.name) + awayBadge + betBadge + '</span>' +
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

        // Render fun fact (Story 16.4)
        renderFunFact(song);

        // Render top 3 guesses this round (AC 10.4.4)
        renderTopGuesses(players);

        // Render leaderboard with position changes
        renderRevealLeaderboard(data.leaderboard || []);

        // Render motivational message (Story 14.4)
        renderMotivationalMessage(data.game_performance);

        // Render song difficulty rating (Story 15.1)
        renderSongDifficulty(data.song_difficulty);

        // Story 14.5 (AC1, AC2, AC7): Trigger celebration confetti on dashboard
        // M1 fix: Prioritize record over exact to avoid duplicate confetti
        if (data.game_performance && data.game_performance.is_new_record) {
            triggerConfetti('record');
        } else {
            // Check for any exact guesses this round
            var hasExactGuess = players.some(function(p) {
                return p.years_off === 0 && !p.missed_round;
            });
            if (hasExactGuess) {
                triggerConfetti('exact');
            }
        }
    }

    /**
     * Render fun fact below year in reveal view (Story 16.4, 16.3)
     * @param {Object} song - Song data with optional fun_fact
     */
    function renderFunFact(song) {
        var container = document.getElementById('dashboard-fun-fact');
        var textEl = document.getElementById('dashboard-fun-fact-text');

        // Get localized fun fact (Story 16.3)
        var funFact = utils.getLocalizedSongField(song, 'fun_fact');

        console.log('[Dashboard] renderFunFact called with song:', song);
        console.log('[Dashboard] fun_fact value:', funFact || 'no fun fact');

        if (!container || !textEl) {
            console.warn('[Dashboard] Fun fact elements not found');
            return;
        }

        // Hide if no fun fact
        if (!funFact || funFact.trim() === '') {
            container.classList.add('hidden');
            console.log('[Dashboard] No fun_fact, hiding container');
            return;
        }

        // Show fun fact
        textEl.textContent = funFact;
        container.classList.remove('hidden');
        console.log('[Dashboard] Fun fact shown:', funFact);
    }

    /**
     * Render motivational message during reveal phase (Story 14.4)
     * @param {Object|null} performance - Game performance data from state
     */
    function renderMotivationalMessage(performance) {
        var container = document.getElementById('reveal-motivational');
        if (!container) return;

        // Hide if no performance data or no message
        if (!performance || !performance.message) {
            container.classList.add('hidden');
            return;
        }

        var message = performance.message;
        var iconEl = container.querySelector('.motivational-icon');
        var textEl = container.querySelector('.motivational-text');

        // Set type-based styling and icon
        container.className = 'motivational-message motivational-message--' + message.type;

        // Icons for different message types
        var icons = {
            'first': '🌟',
            'record': '🏆',
            'strong': '🔥',
            'above': '📈',
            'close': '💪'
        };
        if (iconEl) iconEl.textContent = icons[message.type] || '';
        if (textEl) textEl.textContent = message.message || '';
    }

    /**
     * Render song difficulty rating (Story 15.1)
     * @param {Object|null} difficulty - Difficulty data with stars, label, accuracy, times_played
     */
    function renderSongDifficulty(difficulty) {
        var el = document.getElementById('song-difficulty');
        if (!el) return;

        // Hide if no difficulty data (AC4: insufficient plays)
        if (!difficulty) {
            el.classList.add('hidden');
            return;
        }

        // Build stars string
        var stars = '';
        for (var i = 0; i < difficulty.stars; i++) {
            stars += '<span class="star">&#9733;</span>';
        }

        // Render difficulty display
        el.innerHTML =
            '<div class="difficulty-stars difficulty-' + difficulty.stars + '">' + stars + '</div>' +
            '<span class="difficulty-label">' + utils.t('difficulty.' + difficulty.label) + '</span>' +
            '<span class="difficulty-accuracy">' + difficulty.accuracy + '% ' + utils.t('difficulty.accuracy') + '</span>';

        el.classList.remove('hidden');
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
                '<span class="top-guess-name">' + utils.escapeHtml(player.name) + yearDisplay + '</span>' +
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
                '<span class="entry-name">' + utils.escapeHtml(entry.name) + awayBadge + '</span>' +
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

            if (nameEl) nameEl.textContent = player ? utils.escapeHtml(player.name) : '---';
            if (scoreEl) scoreEl.textContent = player ? player.score : '0';
        });

        // Render stats comparison (Story 14.4)
        renderStatsComparison(data.game_performance);

        // Render superlatives / fun awards (Story 15.2)
        renderSuperlatives(data.superlatives);

        // Story 14.5 (AC3, AC7): Trigger winner confetti on dashboard
        // H2 fix: Only trigger if there's a valid winner with score > 0
        var winner = leaderboard.find(function(p) { return p.rank === 1; });
        if (winner && winner.score > 0) {
            triggerConfetti('winner');
        }

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
                    '<span class="entry-name">' + utils.escapeHtml(entry.name) + awayBadge + '</span>' +
                    '<span class="entry-score">' + entry.score + '</span>' +
                '</div>';
            });

            container.innerHTML = html;
        }
    }

    /**
     * Render stats comparison for end screen (Story 14.4)
     * @param {Object|null} performance - Game performance data from state
     */
    function renderStatsComparison(performance) {
        var container = document.getElementById('end-stats-comparison');
        if (!container) return;

        // Hide if no performance data
        if (!performance) {
            container.classList.add('hidden');
            return;
        }

        var iconEl = container.querySelector('.stats-comparison-icon');
        var textEl = container.querySelector('.stats-comparison-text');

        // Build comparison text based on performance
        var icon = '';
        var text = '';
        var cssClass = 'stats-comparison';

        if (performance.is_first_game) {
            icon = '🌟';
            text = 'First game recorded! Avg: ' + performance.current_avg.toFixed(1) + ' pts/round';
            cssClass += ' stats-comparison--first';
        } else if (performance.is_new_record) {
            icon = '🏆';
            text = 'NEW RECORD! ' + performance.current_avg.toFixed(1) + ' pts/round (prev: ' + performance.all_time_avg.toFixed(1) + ')';
            cssClass += ' stats-comparison--record';
        } else if (performance.is_above_average) {
            icon = '📈';
            text = performance.current_avg.toFixed(1) + ' pts/round (+' + performance.difference.toFixed(1) + ' vs all-time avg)';
            cssClass += ' stats-comparison--above';
        } else {
            icon = '📊';
            text = performance.current_avg.toFixed(1) + ' pts/round (' + performance.difference.toFixed(1) + ' vs all-time avg)';
            cssClass += ' stats-comparison--below';
        }

        container.className = cssClass;
        if (iconEl) iconEl.textContent = icon;
        if (textEl) textEl.textContent = text;
    }

    /**
     * Render superlatives / fun awards (Story 15.2)
     * @param {Array|null} superlatives - Array of award objects from state
     */
    function renderSuperlatives(superlatives) {
        var container = document.getElementById('superlatives-container');
        if (!container) return;

        // Hide if no superlatives
        if (!superlatives || superlatives.length === 0) {
            container.classList.add('hidden');
            return;
        }

        var html = '';
        superlatives.forEach(function(award, index) {
            var valueText = '';
            switch (award.value_label) {
                case 'avg_time':
                    valueText = award.value + 's ' + utils.t('superlatives.avgTime');
                    break;
                case 'streak':
                    valueText = award.value + ' ' + utils.t('superlatives.streak');
                    break;
                case 'bets':
                    valueText = award.value + ' ' + utils.t('superlatives.bets');
                    break;
                case 'points':
                    valueText = award.value + ' ' + utils.t('superlatives.points');
                    break;
                case 'close_guesses':
                    valueText = award.value + ' ' + utils.t('superlatives.closeGuesses');
                    break;
                default:
                    valueText = award.value;
            }

            html += '<div class="superlative-card superlative-card--' + award.id + '" style="animation-delay: ' + (index * 0.2) + 's">' +
                '<div class="superlative-emoji">' + award.emoji + '</div>' +
                '<div class="superlative-title">' + utils.t('superlatives.' + award.title) + '</div>' +
                '<div class="superlative-player">' + utils.escapeHtml(award.player_name) + '</div>' +
                '<div class="superlative-value">' + valueText + '</div>' +
            '</div>';
        });

        container.innerHTML = html;
        container.classList.remove('hidden');
    }

    // ============================================
    // Confetti System (Story 14.5 - AC7)
    // ============================================

    // Track active animations for cleanup (M3 fix)
    var confettiAnimationId = null;
    var confettiIntervalId = null;

    /**
     * Trigger confetti celebration animation (Story 14.5)
     * Uses canvas-confetti library for various celebration types
     * @param {string} type - 'exact', 'record', 'winner', or 'perfect'
     */
    function triggerConfetti(type) {
        // AC5: Respect accessibility preference
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return;
        }

        // Check if confetti library is loaded
        if (typeof confetti === 'undefined') {
            console.warn('[Dashboard Confetti] Library not loaded');
            return;
        }

        // Stop any existing animation before starting new one (M3 fix)
        stopConfetti();

        type = type || 'exact';

        switch (type) {
            case 'exact':
                // AC1: Gold burst for exact guess, 2 seconds (H1 fix - enforced duration)
                var exactDuration = 2 * 1000;
                var exactEnd = Date.now() + exactDuration;
                (function exactFrame() {
                    confetti({
                        particleCount: 15,
                        spread: 70,
                        origin: { y: 0.6 },
                        colors: ['#FFD700', '#FFA500', '#FFEC8B']
                    });
                    if (Date.now() < exactEnd) {
                        confettiAnimationId = requestAnimationFrame(exactFrame);
                    }
                }());
                break;

            case 'record':
                // AC2: Rainbow shower for new record, 3 seconds (H1 fix - enforced duration)
                var recordDuration = 3 * 1000;
                var recordEnd = Date.now() + recordDuration;
                (function recordFrame() {
                    confetti({
                        particleCount: 10,
                        spread: 180,
                        origin: { y: 0.3, x: Math.random() },
                        colors: ['#ff0000', '#ff7f00', '#ffff00', '#00ff00', '#0000ff', '#8b00ff']
                    });
                    if (Date.now() < recordEnd) {
                        confettiAnimationId = requestAnimationFrame(recordFrame);
                    }
                }());
                break;

            case 'winner':
                // AC3: Dual-side fireworks for winner, 4 seconds
                var winnerDuration = 4 * 1000;
                var winnerEnd = Date.now() + winnerDuration;
                (function winnerFrame() {
                    confetti({
                        particleCount: 10,
                        angle: 60,
                        spread: 55,
                        origin: { x: 0 },
                        colors: ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00']
                    });
                    confetti({
                        particleCount: 10,
                        angle: 120,
                        spread: 55,
                        origin: { x: 1 },
                        colors: ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00']
                    });
                    if (Date.now() < winnerEnd) {
                        confettiAnimationId = requestAnimationFrame(winnerFrame);
                    }
                }());
                break;

            case 'perfect':
                // AC4: Epic celebration for perfect game, 5 seconds
                var perfectDuration = 5 * 1000;
                var perfectEnd = Date.now() + perfectDuration;

                // M4 fix: Use setInterval for reliable center bursts
                confettiIntervalId = setInterval(function() {
                    confetti({
                        particleCount: 30,
                        spread: 100,
                        origin: { y: 0.6 },
                        colors: ['#FFD700', '#FFA500', '#FFEC8B']
                    });
                }, 500);

                // Clear interval when duration ends
                setTimeout(function() {
                    if (confettiIntervalId) {
                        clearInterval(confettiIntervalId);
                        confettiIntervalId = null;
                    }
                }, perfectDuration);

                (function perfectFrame() {
                    confetti({
                        particleCount: 7,
                        angle: 60,
                        spread: 55,
                        origin: { x: 0 },
                        colors: ['#FFD700', '#ff2d6a', '#00f5ff', '#00ff88']
                    });
                    confetti({
                        particleCount: 7,
                        angle: 120,
                        spread: 55,
                        origin: { x: 1 },
                        colors: ['#FFD700', '#ff2d6a', '#00f5ff', '#00ff88']
                    });
                    if (Date.now() < perfectEnd) {
                        confettiAnimationId = requestAnimationFrame(perfectFrame);
                    }
                }());
                break;

            default:
                console.warn('[Dashboard Confetti] Unknown type:', type);
        }
    }

    /**
     * Stop any ongoing confetti animations (M3 fix - proper cleanup)
     */
    function stopConfetti() {
        if (confettiAnimationId) {
            cancelAnimationFrame(confettiAnimationId);
            confettiAnimationId = null;
        }
        if (confettiIntervalId) {
            clearInterval(confettiIntervalId);
            confettiIntervalId = null;
        }
        if (typeof confetti !== 'undefined' && confetti.reset) {
            confetti.reset();
        }
    }

    // ============================================
    // Live Reactions (Story 18.9)
    // ============================================

    /**
     * Show a floating reaction bubble on the dashboard
     * @param {string} playerName - Name of the player who reacted
     * @param {string} emoji - The emoji reaction
     */
    function showFloatingReaction(playerName, emoji) {
        var container = document.getElementById('reaction-container');
        if (!container) return;

        var bubble = document.createElement('div');
        bubble.className = 'reaction-bubble';
        bubble.textContent = playerName + ' ' + emoji;

        // Random horizontal position (20% to 80% of screen width)
        bubble.style.left = (20 + Math.random() * 60) + '%';

        container.appendChild(bubble);

        // Remove after animation completes (3s)
        setTimeout(function() {
            bubble.remove();
        }, 3000);
    }

    // ============================================
    // Initialization
    // ============================================

    /**
     * Initialize dashboard
     */
    async function init() {
        console.log('[Dashboard] Initializing...');
        // Initialize i18n (Story 12.5)
        // Guard clause: wait for BeatifyI18n in case fallback script is loading
        var i18nAvailable = await utils.waitForI18n();
        if (!i18nAvailable) {
            console.error('[Dashboard] BeatifyI18n module failed to load - UI will use fallback text');
        } else {
            await BeatifyI18n.init();
            BeatifyI18n.initPageTranslations();
        }
        connectWebSocket();
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
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
                console.log('[Dashboard] SW registered:', registration.scope);
            }).catch(function(error) {
                console.warn('[Dashboard] SW registration failed:', error);
            });
        });
    }

})();
