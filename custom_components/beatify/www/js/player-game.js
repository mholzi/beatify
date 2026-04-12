/**
 * Beatify Player - Game Module
 * Playing phase: guess submission, timer, betting, steal mechanic, artist/movie challenge UI
 */

import {
    state, escapeHtml, showConfirmModal,
    prefersReducedMotion, animateValue, animateScoreChange, showPointsPopup,
    previousState, isPreviousStateInitialized, isStreakMilestone, detectRankChanges,
    updatePreviousState, AnimationUtils, AnimationQueue,
    LEADERBOARD_LAZY_CONFIG, lazyLeaderboardState,
    initLeaderboardObserver, renderLazyLeaderboardRange,
    renderLeaderboardEntry, calculateInitialVisibleRange,
    setupLeaderboardResizeHandler, setEnergyLevel,
    triggerConfetti, stopConfetti
} from './player-utils.js';

var utils = window.BeatifyUtils || {};

// ============================================
// Countdown Timer (Story 4.2)
// ============================================

var countdownInterval = null;

/**
 * Start countdown timer
 * @param {number} deadline - Server deadline timestamp in milliseconds
 */
export function startCountdown(deadline) {
    stopCountdown();

    var timerElement = document.getElementById('timer');
    if (!timerElement) return;

    timerElement.classList.remove('timer--warning', 'timer--critical');

    function updateCountdown() {
        var now = Date.now();
        var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

        timerElement.textContent = remaining;

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
export function stopCountdown() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}

// ============================================
// Game View (Story 4.2)
// ============================================

/**
 * Update game view with round data
 * @param {Object} data - State data from server
 */
export function updateGameView(data) {
    var currentRound = document.getElementById('current-round');
    var totalRounds = document.getElementById('total-rounds');
    var lastRoundBanner = document.getElementById('last-round-banner');

    if (currentRound) currentRound.textContent = data.round || 1;
    if (totalRounds) totalRounds.textContent = data.total_rounds || 10;

    if (lastRoundBanner) {
        if (data.last_round) {
            lastRoundBanner.classList.remove('hidden');
        } else {
            lastRoundBanner.classList.add('hidden');
        }
    }

    // Issue #442: Show/hide Closest Wins badge
    var closestBadge = document.getElementById('closest-wins-badge');
    if (closestBadge) {
        if (data.closest_wins_mode) {
            closestBadge.classList.remove('hidden');
        } else {
            closestBadge.classList.add('hidden');
        }
    }

    // Issue #23: Show/hide intro round badge + splash overlay
    var introBadge = document.getElementById('intro-badge');
    var introSplash = document.getElementById('intro-splash');
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
                if (introSplash && !introSplash._shown) {
                    introSplash._shown = true;
                    introSplash.classList.remove('hidden');
                    setTimeout(function() {
                        introSplash.classList.add('hidden');
                    }, 2000);
                }
            }
        } else {
            introBadge.classList.add('hidden');
            introBadge.classList.remove('intro-badge--stopped');
            if (introSplash) {
                introSplash.classList.add('hidden');
                introSplash._shown = false;
            }
        }
    }

    // Update album cover
    var albumCover = document.getElementById('album-cover');
    var albumLoading = document.getElementById('album-loading');

    if (albumCover && data.song) {
        if (albumLoading) albumLoading.classList.remove('hidden');

        var newSrc = data.song.album_art || '/beatify/static/img/no-artwork.svg';

        albumCover.onload = function() {
            if (albumLoading) albumLoading.classList.add('hidden');
        };

        albumCover.onerror = function() {
            albumCover.src = '/beatify/static/img/no-artwork.svg';
            if (albumLoading) albumLoading.classList.add('hidden');
        };

        albumCover.src = newSrc;
    }

    renderSubmissionTracker(data.players);

    if (data.leaderboard) {
        updateLeaderboard(data, 'leaderboard-list');
    }

    updateStealUI(data.players);

    if (data.artist_challenge !== undefined) {
        renderArtistChallenge(data.artist_challenge, 'PLAYING');
    }

    if (data.movie_challenge !== undefined) {
        renderMovieChallenge(data.movie_challenge, 'PLAYING');
    }
}

/**
 * Handle async metadata update for fast transitions (Issue #42)
 * @param {Object} song - Song metadata with artist, title, album_art
 */
export function handleMetadataUpdate(song) {
    if (!song) return;

    var albumCover = document.getElementById('album-cover');
    var albumLoading = document.getElementById('album-loading');

    if (albumCover && song.album_art) {
        var newSrc = song.album_art;

        if (albumCover.src === newSrc) return;

        albumCover.style.transition = 'opacity 0.3s ease-in-out';
        albumCover.style.opacity = '0.5';

        var preloader = new Image();
        preloader.onload = function() {
            albumCover.src = newSrc;
            albumCover.style.opacity = '1';
            if (albumLoading) albumLoading.classList.add('hidden');
        };
        preloader.onerror = function() {
            albumCover.src = '/beatify/static/img/no-artwork.svg';
            albumCover.style.opacity = '1';
            if (albumLoading) albumLoading.classList.add('hidden');
        };
        preloader.src = newSrc;
    }

    console.log('[Metadata] Updated:', song.artist, '-', song.title);
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

    var parts = trimmed.split(/[\s-]+/).filter(Boolean);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return trimmed.slice(0, Math.min(2, trimmed.length)).toUpperCase();
}

/**
 * Render submission tracker showing who has submitted
 * @param {Array} players - Array of player objects
 */
function renderSubmissionTracker(players) {
    var tracker = document.getElementById('submission-tracker');
    var container = document.getElementById('submitted-players');

    if (!tracker || !container) return;

    var playerList = players || [];
    var submittedCount = playerList.filter(function(p) {
        return p.submitted;
    }).length;
    var totalCount = playerList.length;

    var allSubmitted = submittedCount === totalCount && totalCount > 0;
    tracker.classList.toggle('all-submitted', allSubmitted);

    container.innerHTML = playerList.map(function(player) {
        var initials = getInitials(player.name);
        var isCurrentPlayer = player.name === state.playerName;
        var isDisconnected = player.connected === false;
        var classes = [
            'player-indicator',
            player.submitted ? 'is-submitted' : '',
            isCurrentPlayer ? 'is-current-player' : '',
            isDisconnected ? 'player-indicator--disconnected' : ''
        ].filter(Boolean).join(' ');

        var badges = '';
        if (player.steal_used) {
            badges += '<span class="player-badge player-badge--steal">🥷</span>';
        }
        if (player.bet) {
            badges += '<span class="player-badge player-badge--bet">🎲</span>';
        }

        return '<div class="' + classes + '">' +
            badges +
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
 * Update leaderboard display (Story 18.1: Lazy loading for 10+ players)
 * @param {Object} data - State data containing leaderboard
 * @param {string} targetListId - ID of list container (for different views)
 * @param {boolean} isRevealPhase - True if rendering during REVEAL phase (animate scores)
 */
export function updateLeaderboard(data, targetListId, isRevealPhase) {
    var leaderboard = data.leaderboard || [];
    var listEl = document.getElementById(targetListId || 'leaderboard-list');
    if (!listEl) return;

    var shouldAnimate = isRevealPhase && isPreviousStateInitialized();

    var rankChanges = shouldAnimate ? detectRankChanges(leaderboard) : {};

    leaderboard.forEach(function(entry) {
        entry.is_current = (entry.name === state.playerName);

        var rankChange = rankChanges[entry.name];
        if (rankChange) {
            entry._rankChange = rankChange;
        }

        var prevPlayer = previousState.players[entry.name];
        var prevScore = prevPlayer ? prevPlayer.score : entry.score;
        entry._prevScore = prevScore;
        entry._displayScore = isRevealPhase ? prevScore : entry.score;
    });

    var displayList = compressLeaderboard(leaderboard, state.playerName);

    var useLazyLoading = leaderboard.length >= LEADERBOARD_LAZY_CONFIG.MIN_PLAYERS_FOR_LAZY;

    if (useLazyLoading) {
        if (!lazyLeaderboardState.observer) {
            initLeaderboardObserver(listEl);
        }

        lazyLeaderboardState.fullData = displayList;
        lazyLeaderboardState.isLazyEnabled = true;
        lazyLeaderboardState.listEl = listEl;

        lazyLeaderboardState.visibleRange = calculateInitialVisibleRange(displayList, state.playerName);

        renderLazyLeaderboardRange();
    } else {
        lazyLeaderboardState.isLazyEnabled = false;

        var html = '';
        displayList.forEach(function(entry) {
            html += renderLeaderboardEntry(entry);
        });

        listEl.innerHTML = html;
    }

    var scoreAnimations = [];
    if (shouldAnimate) {
        displayList.forEach(function(entry) {
            if (!entry.separator && entry._prevScore !== entry.score) {
                scoreAnimations.push({
                    name: entry.name,
                    prevScore: entry._prevScore,
                    newScore: entry.score
                });
            }
        });
    }

    if (shouldAnimate && scoreAnimations.length > 0) {
        requestAnimationFrame(function() {
            var entryMap = {};
            var entries = listEl.querySelectorAll('.leaderboard-entry[data-name]');
            for (var i = 0; i < entries.length; i++) {
                var entry = entries[i];
                var name = entry.getAttribute('data-name');
                if (name) {
                    entryMap[name] = entry;
                }
            }

            scoreAnimations.forEach(function(anim) {
                var entryEl = entryMap[anim.name];
                if (entryEl) {
                    var scoreEl = entryEl.querySelector('.entry-score');
                    if (scoreEl) {
                        animateValue(scoreEl, anim.prevScore, anim.newScore, 500);
                    }
                }
            });
        });
    }

    if (leaderboard.length > 8) {
        scrollToCurrentPlayer(listEl);
    }

    updateYouIndicator(leaderboard);

    updateLeaderboardSummary(leaderboard);

    updatePreviousState(data.players || [], leaderboard);
}

/**
 * Compress leaderboard for display when >10 players (Story 9.5)
 * @param {Array} players - Full leaderboard
 * @param {string} currentPlayerName - Name of current player
 * @returns {Array} Compressed display list
 */
function compressLeaderboard(players, currentPlayerName) {
    if (players.length <= 10) return players;

    var top5 = players.slice(0, 5);
    var bottom3 = players.slice(-3);
    var currentIdx = -1;

    for (var i = 0; i < players.length; i++) {
        if (players[i].name === currentPlayerName) {
            currentIdx = i;
            break;
        }
    }

    if (currentIdx < 5 || currentIdx >= players.length - 3) {
        return [].concat(top5, [{ separator: true }], bottom3);
    }

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
        youEl.textContent = utils.t('leaderboard.you') + ' #' + currentPlayer.rank;
        youEl.classList.remove('hidden');
    }
}

/**
 * Setup leaderboard toggle behavior (collapsible section pattern)
 */
export function setupLeaderboardToggle() {
    var toggle = document.getElementById('leaderboard-toggle');
    var leaderboard = document.getElementById('game-leaderboard');
    if (toggle && leaderboard && !toggle.hasAttribute('data-initialized')) {
        toggle.setAttribute('data-initialized', 'true');
        toggle.addEventListener('click', function() {
            var isCollapsed = leaderboard.classList.toggle('collapsed');
            toggle.setAttribute('aria-expanded', !isCollapsed);
        });
    }
}

/**
 * Update leaderboard summary badge with leader info
 * @param {Array} leaderboard - Leaderboard array
 * @param {string} summaryId - Optional specific summary element ID
 */
export function updateLeaderboardSummary(leaderboard, summaryId) {
    var summaryIds = summaryId ? [summaryId] : ['leaderboard-summary', 'reveal-leaderboard-summary'];

    summaryIds.forEach(function(id) {
        var summaryEl = document.getElementById(id);
        if (!summaryEl || !leaderboard || leaderboard.length === 0) return;

        var leader = leaderboard[0];
        if (leader) {
            summaryEl.textContent = leader.name + ': ' + leader.score;
        }
    });
}

/**
 * Setup reveal leaderboard toggle behavior (collapsible section pattern)
 */
export function setupRevealLeaderboardToggle() {
    var toggle = document.getElementById('reveal-leaderboard-toggle');
    var leaderboard = document.getElementById('reveal-leaderboard');
    if (toggle && leaderboard && !toggle.hasAttribute('data-initialized')) {
        toggle.setAttribute('data-initialized', 'true');
        toggle.addEventListener('click', function() {
            var isCollapsed = leaderboard.classList.toggle('collapsed');
            toggle.setAttribute('aria-expanded', !isCollapsed);
        });
    }
}

/**
 * Setup toggle for round analytics section (collapsed by default)
 */
export function setupRoundAnalyticsToggle() {
    var toggle = document.getElementById('round-analytics-toggle');
    var section = document.getElementById('round-analytics');
    if (toggle && section && !toggle.hasAttribute('data-initialized')) {
        toggle.setAttribute('data-initialized', 'true');
        toggle.addEventListener('click', function() {
            var isCollapsed = section.classList.toggle('collapsed');
            toggle.setAttribute('aria-expanded', !isCollapsed);
        });
    }
}

// ============================================
// Year Selector & Submission (Story 4.3)
// ============================================

var hasSubmitted = false;
var betActive = false;
var hasStealAvailable = false;

// Artist Challenge state (Story 20.5)
var artistChallengeComplete = false;
var pendingArtistGuess = null;
var winningArtist = null;
var ARTIST_DEBOUNCE_MS = 300;
var lastArtistGuessTime = 0;

// Movie Challenge state (Issue #28)
var movieChallengeComplete = false;
var pendingMovieGuess = null;
var MOVIE_DEBOUNCE_MS = 500;
var lastMovieGuessTime = 0;

/**
 * Initialize year selector interaction
 */
export function initYearSelector() {
    var slider = document.getElementById('year-slider');
    var yearDisplay = document.getElementById('selected-year');

    if (!slider || !yearDisplay) return;

    slider.addEventListener('input', function() {
        yearDisplay.textContent = this.value;
    });

    var betToggle = document.getElementById('bet-toggle');
    if (betToggle) {
        betToggle.addEventListener('click', function() {
            if (hasSubmitted) return;
            betActive = !betActive;
            betToggle.classList.toggle('is-active', betActive);
        });
    }

    var submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', handleSubmitGuess);
    }

    var stealBtn = document.getElementById('steal-btn');
    if (stealBtn) {
        stealBtn.addEventListener('click', handleStealClick);
    }

    var stealModalClose = document.getElementById('steal-modal-close');
    if (stealModalClose) {
        stealModalClose.addEventListener('click', closeStealModal);
    }

    var stealModal = document.getElementById('steal-modal');
    if (stealModal) {
        var backdrop = stealModal.querySelector('.steal-modal-backdrop');
        if (backdrop) {
            backdrop.addEventListener('click', closeStealModal);
        }
    }
}

/**
 * Handle guess submission
 */
export function handleSubmitGuess() {
    if (hasSubmitted) return;

    var slider = document.getElementById('year-slider');
    var submitBtn = document.getElementById('submit-btn');

    if (!slider || !submitBtn) return;

    var year = parseInt(slider.value, 10);

    submitBtn.disabled = true;
    submitBtn.classList.add('is-loading');

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({
            type: 'submit',
            year: year,
            bet: betActive
        }));
    } else {
        showSubmitError(utils.t('errors.connectionLost'));
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
    }
}

/**
 * Handle server acknowledgment of submission
 */
export function handleSubmitAck() {
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
export function handleSubmitError(data) {
    var submitBtn = document.getElementById('submit-btn');

    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
    }

    if (data.code === 'ROUND_EXPIRED') {
        showSubmitError(utils.t('errors.timesUp'));
        hasSubmitted = true;
        if (submitBtn) submitBtn.disabled = true;
    } else if (data.code === 'ALREADY_SUBMITTED') {
        handleSubmitAck();
    } else {
        showSubmitError(data.message || 'Submission failed');
    }
}

/**
 * Show error on submit button
 * @param {string} message - Error message
 */
export function showSubmitError(message) {
    var submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.textContent = message;
        submitBtn.classList.add('is-error');
        setTimeout(function() {
            submitBtn.textContent = utils.t('game.submitGuess');
            submitBtn.classList.remove('is-error');
        }, 2000);
    }
}

/**
 * Reset submission state for new round
 */
export function resetSubmissionState() {
    hasSubmitted = false;
    betActive = false;

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
        submitBtn.textContent = utils.t('game.submitGuess');
    }

    if (betToggle) {
        betToggle.classList.remove('hidden', 'is-active');
    }

    if (confirmation) {
        confirmation.classList.add('hidden');
    }

    if (slider) {
        slider.value = 1990;
        var yearDisplay = document.getElementById('selected-year');
        if (yearDisplay) yearDisplay.textContent = '1990';
    }

    hasStealAvailable = false;
    hideStealUI();

    resetArtistChallengeState();

    resetMovieChallengeState();
}

// ============================================
// Artist Challenge (Story 20.5)
// ============================================

/**
 * Render artist challenge UI
 * @param {Object} artistChallenge - Artist challenge data from server
 * @param {string} phase - Current game phase (PLAYING, REVEAL)
 */
export function renderArtistChallenge(artistChallenge, phase) {
    var container = document.getElementById('artist-challenge-container');
    if (!container) return;

    if (!artistChallenge || !artistChallenge.options) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');

    var optionsEl = document.getElementById('artist-options');
    var resultEl = document.getElementById('artist-result');

    var currentOptions = Array.from(optionsEl.querySelectorAll('.artist-option-btn'))
        .map(function(btn) { return btn.dataset.artist; });
    var newOptions = artistChallenge.options;

    if (JSON.stringify(currentOptions) !== JSON.stringify(newOptions)) {
        optionsEl.innerHTML = '';
        newOptions.forEach(function(artist, index) {
            var btn = document.createElement('button');
            btn.className = 'artist-option-btn';
            btn.dataset.artist = artist;
            btn.dataset.index = index;
            btn.textContent = artist;
            btn.addEventListener('click', function() {
                handleArtistGuess(artist);
            });
            optionsEl.appendChild(btn);
        });
    }

    if (artistChallenge.winner) {
        var buttons = optionsEl.querySelectorAll('.artist-option-btn');
        buttons.forEach(function(btn) {
            btn.classList.add('is-disabled');
            btn.classList.remove('is-loading', 'is-wrong');

            var correctArtist = artistChallenge.correct_artist || winningArtist;
            if (correctArtist && btn.dataset.artist === correctArtist) {
                btn.classList.add('is-winner');
            }
        });

        if (artistChallenge.winner === state.playerName) {
            var bonusPoints = artistChallenge.bonus_points || 5;
            resultEl.textContent = (utils.t('artistChallenge.youGotIt') || 'You got it! +{points} points')
                .replace('{points}', bonusPoints);
            resultEl.className = 'artist-result is-winner';
        } else {
            var msg = (utils.t('artistChallenge.someoneBeatYou') || '{winner} got it first!')
                .replace('{winner}', artistChallenge.winner);
            resultEl.textContent = msg;
            resultEl.className = 'artist-result is-late';
        }
        resultEl.classList.remove('hidden');
        artistChallengeComplete = true;
    } else if (!artistChallengeComplete) {
        resultEl.classList.add('hidden');
    }
}

/**
 * Handle artist guess button click
 * @param {string} artist - The artist name that was clicked
 */
function handleArtistGuess(artist) {
    var now = Date.now();
    if (now - lastArtistGuessTime < ARTIST_DEBOUNCE_MS) return;
    lastArtistGuessTime = now;

    if (artistChallengeComplete) return;

    var btn = document.querySelector('.artist-option-btn[data-artist="' + CSS.escape(artist) + '"]');
    if (btn) {
        btn.classList.add('is-loading');
    }

    pendingArtistGuess = artist;

    try {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send(JSON.stringify({
                type: 'artist_guess',
                artist: artist
            }));
        }
    } catch (e) {
        console.error('Artist guess send failed:', e);
        if (btn) {
            btn.classList.remove('is-loading');
        }
        pendingArtistGuess = null;
    }
}

/**
 * Handle artist_guess_ack from server (Story 20.3 protocol)
 * @param {Object} data - Ack response from server
 */
export function handleArtistGuessAck(data) {
    var btn = pendingArtistGuess
        ? document.querySelector('.artist-option-btn[data-artist="' + CSS.escape(pendingArtistGuess) + '"]')
        : null;

    if (data.correct && data.first) {
        winningArtist = pendingArtistGuess;
        if (btn) {
            btn.classList.remove('is-loading');
            btn.classList.add('is-correct');
            var badge = document.createElement('span');
            badge.className = 'artist-points-badge';
            badge.textContent = '+' + (data.bonus_points || 5);
            btn.appendChild(badge);
        }
        disableAllArtistButtons();
        var bonusText = (utils.t('artistChallenge.youGotIt') || 'You got it! +{points} points')
            .replace('{points}', data.bonus_points || 5);
        showArtistResult(bonusText, true);
        artistChallengeComplete = true;

    } else if (data.correct && !data.first) {
        winningArtist = pendingArtistGuess;
        if (btn) {
            btn.classList.remove('is-loading');
            btn.classList.add('is-correct');
        }
        disableAllArtistButtons();
        var msg = (utils.t('artistChallenge.someoneBeatYou') || '{winner} got it first!')
            .replace('{winner}', data.winner || 'Someone');
        showArtistResult(msg, false);
        artistChallengeComplete = true;

    } else {
        if (btn) {
            btn.classList.remove('is-loading');
            btn.classList.add('is-wrong', 'is-selected');
        }
        disableAllArtistButtons();
        showArtistResult(utils.t('artistChallenge.wrongGuess') || 'Wrong guess!', false);
        artistChallengeComplete = true;
    }

    pendingArtistGuess = null;
}

/**
 * Disable all artist option buttons
 */
function disableAllArtistButtons() {
    document.querySelectorAll('.artist-option-btn').forEach(function(btn) {
        btn.classList.add('is-disabled');
        btn.classList.remove('is-loading');
    });
}

/**
 * Show artist challenge result message
 * @param {string} message - Result message to display
 * @param {boolean} isWinner - Whether current player won
 */
function showArtistResult(message, isWinner) {
    var resultEl = document.getElementById('artist-result');
    if (resultEl) {
        resultEl.textContent = message;
        resultEl.className = 'artist-result ' + (isWinner ? 'is-winner' : 'is-late');
        resultEl.classList.remove('hidden');
    }
}

/**
 * Reset artist challenge state for new round
 */
function resetArtistChallengeState() {
    artistChallengeComplete = false;
    pendingArtistGuess = null;
    winningArtist = null;

    var container = document.getElementById('artist-challenge-container');
    if (container) container.classList.add('hidden');

    var optionsEl = document.getElementById('artist-options');
    if (optionsEl) optionsEl.innerHTML = '';

    var resultEl = document.getElementById('artist-result');
    if (resultEl) {
        resultEl.classList.add('hidden');
        resultEl.className = 'artist-result hidden';
    }
}

/**
 * Render artist challenge reveal section (Story 20.6)
 * @param {Object} artistChallenge - Artist challenge data with correct_artist and winner
 * @param {string} currentPlayerName - Current player's name for comparison
 */
export function renderArtistReveal(artistChallenge, currentPlayerName) {
    var section = document.getElementById('artist-reveal-section');
    if (!section) return;

    if (!artistChallenge || !artistChallenge.correct_artist) {
        section.classList.add('hidden');
        return;
    }

    section.classList.remove('hidden');

    var nameEl = document.getElementById('artist-reveal-name');
    if (nameEl) {
        nameEl.textContent = artistChallenge.correct_artist;
    }

    var winnerEl = document.getElementById('artist-reveal-winner');
    if (winnerEl) {
        if (artistChallenge.winner) {
            winnerEl.classList.remove('hidden');
            if (artistChallenge.winner === currentPlayerName) {
                var bonusPoints = artistChallenge.bonus_points || 5;
                winnerEl.textContent = (utils.t('artistChallenge.youGotIt') || 'You got it! +{points} points')
                    .replace('{points}', bonusPoints);
                winnerEl.className = 'artist-reveal-winner is-you';
            } else {
                var msg = (utils.t('artistChallenge.winnerWas') || '{winner} got it first!')
                    .replace('{winner}', artistChallenge.winner);
                winnerEl.textContent = msg;
                winnerEl.className = 'artist-reveal-winner is-other';
            }
        } else {
            winnerEl.textContent = utils.t('artistChallenge.noWinner') || 'No one guessed the artist';
            winnerEl.className = 'artist-reveal-winner artist-reveal-no-winner';
            winnerEl.classList.remove('hidden');
        }
    }
}

// ============================================
// Movie Challenge (Issue #28)
// ============================================

/**
 * Render movie challenge UI
 * @param {Object} movieChallenge - Movie challenge data from server
 * @param {string} phase - Current game phase (PLAYING, REVEAL)
 */
export function renderMovieChallenge(movieChallenge, phase) {
    var container = document.getElementById('movie-challenge-container');
    if (!container) return;

    if (!movieChallenge || !movieChallenge.options) {
        container.classList.add('hidden');
        return;
    }

    container.classList.remove('hidden');

    var optionsEl = document.getElementById('movie-options');
    var resultEl = document.getElementById('movie-result');

    var currentOptions = Array.from(optionsEl.querySelectorAll('.movie-option-btn'))
        .map(function(btn) { return btn.dataset.movie; });
    var newOptions = movieChallenge.options;

    if (JSON.stringify(currentOptions) !== JSON.stringify(newOptions)) {
        optionsEl.innerHTML = '';
        newOptions.forEach(function(movie, index) {
            var btn = document.createElement('button');
            btn.className = 'movie-option-btn';
            btn.dataset.movie = movie;
            btn.dataset.index = index;
            btn.textContent = movie;
            btn.addEventListener('click', function() {
                handleMovieGuess(movie);
            });
            optionsEl.appendChild(btn);
        });
    }

    if (movieChallengeComplete) {
        var buttons = optionsEl.querySelectorAll('.movie-option-btn');
        buttons.forEach(function(btn) {
            btn.classList.add('is-disabled');
        });
    }
}

/**
 * Handle movie guess button click
 * @param {string} movie - The movie name that was clicked
 */
function handleMovieGuess(movie) {
    var now = Date.now();
    if (now - lastMovieGuessTime < MOVIE_DEBOUNCE_MS) return;
    lastMovieGuessTime = now;

    if (movieChallengeComplete) return;

    var btn = document.querySelector('.movie-option-btn[data-movie="' + CSS.escape(movie) + '"]');
    if (btn) {
        btn.classList.add('is-loading');
    }

    pendingMovieGuess = movie;

    try {
        if (state.ws && state.ws.readyState === WebSocket.OPEN) {
            state.ws.send(JSON.stringify({
                type: 'movie_guess',
                movie: movie
            }));
        }
    } catch (e) {
        console.error('Movie guess send failed:', e);
        if (btn) {
            btn.classList.remove('is-loading');
        }
        pendingMovieGuess = null;
    }
}

/**
 * Handle movie_guess_ack from server (Issue #28)
 * @param {Object} data - Ack response from server
 */
export function handleMovieGuessAck(data) {
    var btn = pendingMovieGuess
        ? document.querySelector('.movie-option-btn[data-movie="' + CSS.escape(pendingMovieGuess) + '"]')
        : null;

    if (data.already_guessed) {
        if (btn) {
            btn.classList.remove('is-loading');
        }
        showMovieResult(utils.t('movieChallenge.alreadyGuessed') || 'Already guessed!', false);
        movieChallengeComplete = true;
        disableAllMovieButtons();

    } else if (data.correct) {
        if (btn) {
            btn.classList.remove('is-loading');
            btn.classList.add('is-correct');
            if (data.bonus > 0) {
                var badge = document.createElement('span');
                badge.className = 'movie-rank-badge';
                badge.textContent = '+' + data.bonus;
                btn.appendChild(badge);
            }
        }
        disableAllMovieButtons();
        var bonusText = (utils.t('movieChallenge.youGotIt') || 'Correct! #{rank} — +{bonus} points')
            .replace('{rank}', data.rank || 1)
            .replace('{bonus}', data.bonus || 0);
        showMovieResult(bonusText, true);
        movieChallengeComplete = true;

    } else {
        if (btn) {
            btn.classList.remove('is-loading');
            btn.classList.add('is-wrong', 'is-selected');
        }
        disableAllMovieButtons();
        showMovieResult(utils.t('movieChallenge.wrongGuess') || 'Not quite...', false);
        movieChallengeComplete = true;
    }

    pendingMovieGuess = null;
}

/**
 * Disable all movie option buttons
 */
function disableAllMovieButtons() {
    document.querySelectorAll('.movie-option-btn').forEach(function(btn) {
        btn.classList.add('is-disabled');
        btn.classList.remove('is-loading');
    });
}

/**
 * Show movie challenge result message
 * @param {string} message - Result message to display
 * @param {boolean} isWinner - Whether current player guessed correctly
 */
function showMovieResult(message, isWinner) {
    var resultEl = document.getElementById('movie-result');
    if (resultEl) {
        resultEl.textContent = message;
        resultEl.className = 'movie-result ' + (isWinner ? 'is-winner' : 'is-late');
        resultEl.classList.remove('hidden');
    }
}

/**
 * Reset movie challenge state for new round
 */
function resetMovieChallengeState() {
    movieChallengeComplete = false;
    pendingMovieGuess = null;

    var container = document.getElementById('movie-challenge-container');
    if (container) container.classList.add('hidden');

    var optionsEl = document.getElementById('movie-options');
    if (optionsEl) optionsEl.innerHTML = '';

    var resultEl = document.getElementById('movie-result');
    if (resultEl) {
        resultEl.classList.add('hidden');
        resultEl.className = 'movie-result hidden';
    }
}

/**
 * Render movie challenge reveal section (Issue #28)
 * @param {Object} movieChallenge - Movie challenge data with correct_movie and results
 * @param {string} currentPlayerName - Current player's name for comparison
 */
export function renderMovieReveal(movieChallenge, currentPlayerName) {
    var section = document.getElementById('movie-reveal-section');
    if (!section) return;

    if (!movieChallenge || !movieChallenge.correct_movie) {
        section.classList.add('hidden');
        return;
    }

    section.classList.remove('hidden');

    var nameEl = document.getElementById('movie-reveal-name');
    if (nameEl) {
        nameEl.textContent = movieChallenge.correct_movie;
    }

    var winnersEl = document.getElementById('movie-reveal-winners');
    if (winnersEl && movieChallenge.results) {
        var winners = movieChallenge.results.winners || [];
        if (winners.length > 0) {
            winnersEl.innerHTML = '';
            winnersEl.classList.remove('hidden');

            var title = document.createElement('div');
            title.className = 'movie-reveal-winners-title';
            title.textContent = utils.t('movieChallenge.winnersTitle') || 'Movie Quiz Winners';
            winnersEl.appendChild(title);

            winners.forEach(function(winner) {
                var entry = document.createElement('div');
                entry.className = 'movie-reveal-winner-entry';
                if (winner.name === currentPlayerName) {
                    entry.classList.add('is-you');
                } else {
                    entry.classList.add('is-other');
                }
                entry.textContent = winner.name + ' — +' + winner.bonus + ' (' + winner.time + 's)';
                winnersEl.appendChild(entry);
            });
        } else {
            winnersEl.innerHTML = '';
            winnersEl.classList.remove('hidden');
            var noWinner = document.createElement('div');
            noWinner.className = 'movie-reveal-no-winner';
            noWinner.textContent = utils.t('movieChallenge.noWinner') || 'No one guessed the movie';
            winnersEl.appendChild(noWinner);
        }
    }
}

// ============================================
// Steal Power-up (Story 15.3)
// ============================================

/**
 * Update steal UI based on player state
 * @param {Array} players - Array of player objects
 */
function updateStealUI(players) {
    if (!state.playerName || !players) return;

    var currentPlayer = players.find(function(p) {
        return p.name === state.playerName;
    });

    if (!currentPlayer) return;

    hasStealAvailable = currentPlayer.steal_available && !hasSubmitted;

    var stealIndicator = document.getElementById('steal-indicator');
    var stealBtn = document.getElementById('steal-btn');

    if (hasStealAvailable) {
        if (stealIndicator) stealIndicator.classList.remove('hidden');
        if (stealBtn) stealBtn.classList.remove('hidden');
    } else {
        hideStealUI();
    }
}

/**
 * Hide all steal UI elements
 */
function hideStealUI() {
    var stealIndicator = document.getElementById('steal-indicator');
    var stealBtn = document.getElementById('steal-btn');

    if (stealIndicator) stealIndicator.classList.add('hidden');
    if (stealBtn) stealBtn.classList.add('hidden');
}

/**
 * Handle steal button click - request targets and open modal
 */
function handleStealClick() {
    if (!hasStealAvailable || hasSubmitted) return;

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({ type: 'get_steal_targets' }));
    }
}

/**
 * Open steal modal with available targets
 * @param {Array} targets - Array of player names who have submitted
 */
function openStealModal(targets) {
    var modal = document.getElementById('steal-modal');
    var targetList = document.getElementById('steal-target-list');

    if (!modal || !targetList) return;

    targetList.innerHTML = '';

    if (!targets || targets.length === 0) {
        var noTargets = document.createElement('p');
        noTargets.className = 'steal-no-targets';
        noTargets.textContent = utils.t('steal.waitForSubmit');
        targetList.appendChild(noTargets);
    } else {
        targets.forEach(function(target) {
            var btn = document.createElement('button');
            btn.className = 'steal-target-btn';
            btn.textContent = target;
            btn.addEventListener('click', function() {
                selectStealTarget(target);
            });
            targetList.appendChild(btn);
        });
    }

    modal.classList.remove('hidden');
}

/**
 * Close steal modal
 */
function closeStealModal() {
    var modal = document.getElementById('steal-modal');
    if (modal) modal.classList.add('hidden');
}

/**
 * Select a steal target and confirm
 * @param {string} targetName - Name of player to steal from
 */
async function selectStealTarget(targetName) {
    var confirmMsg = utils.t('steal.confirm').replace('{name}', targetName);
    var confirmed = await showConfirmModal(
        utils.t('steal.confirmTitle') || 'Steal Answer?',
        confirmMsg,
        utils.t('steal.confirmButton') || 'Steal',
        utils.t('common.cancel')
    );
    if (!confirmed) {
        return;
    }

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({
            type: 'steal',
            target: targetName
        }));
    }

    closeStealModal();
}

/**
 * Handle steal acknowledgment from server
 * @param {Object} data - Response data with target and year
 */
export function handleStealAck(data) {
    if (data.success) {
        hasStealAvailable = false;
        hasSubmitted = true;

        hideStealUI();

        var yearSelector = document.getElementById('year-selector');
        var submitBtn = document.getElementById('submit-btn');
        var confirmation = document.getElementById('submitted-confirmation');

        if (yearSelector) yearSelector.classList.add('is-submitted');
        if (submitBtn) submitBtn.classList.add('hidden');
        if (confirmation) confirmation.classList.remove('hidden');

        showStealConfirmation(data.target, data.year);

        var yearDisplay = document.getElementById('selected-year');
        var slider = document.getElementById('year-slider');
        if (yearDisplay) yearDisplay.textContent = data.year;
        if (slider) slider.value = data.year;
    }
}

/**
 * Handle steal targets response from server
 * @param {Object} data - Response data with targets array
 */
export function handleStealTargets(data) {
    openStealModal(data.targets || []);
}

/**
 * Show steal confirmation toast
 * @param {string} target - Name of player stolen from
 * @param {number} year - The stolen year guess
 */
function showStealConfirmation(target, year) {
    var toast = document.getElementById('steal-confirmation');
    var text = document.getElementById('steal-confirmation-text');

    if (!toast || !text) return;

    var msg = utils.t('steal.success')
        .replace('{name}', target)
        .replace('{year}', year);
    text.textContent = msg;

    toast.classList.remove('hidden');

    setTimeout(function() {
        toast.classList.add('hidden');
    }, 3000);
}

// ============================================
// Admin Control Bar (Story 6.1)
// ============================================

var adminActionPending = false;
var ADMIN_ACTION_DEBOUNCE_MS = 500;

var songStopped = false;

var currentVolume = 0.5;

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
export function showAdminControlBar() {
    if (!state.isAdmin) return;
    var bar = document.getElementById('admin-control-bar');
    if (bar) {
        bar.classList.remove('hidden');
        document.body.classList.add('has-control-bar');
    }
}

/**
 * Hide admin control bar
 */
export function hideAdminControlBar() {
    var bar = document.getElementById('admin-control-bar');
    if (bar) {
        bar.classList.add('hidden');
        document.body.classList.remove('has-control-bar');
    }
}

// ============================================
// Live Reactions (Story 18.9)
// ============================================

/**
 * Show reaction bar during REVEAL phase
 */
export function showReactionBar() {
    var bar = document.getElementById('reaction-bar');
    if (bar) {
        bar.classList.remove('hidden');
    }
}

/**
 * Hide reaction bar (non-REVEAL phases)
 */
export function hideReactionBar() {
    var bar = document.getElementById('reaction-bar');
    if (bar) {
        bar.classList.add('hidden');
    }
}

/**
 * Send reaction via WebSocket (fire-and-forget)
 * @param {string} emoji - The emoji to send
 */
function sendReaction(emoji) {
    if (state.hasReactedThisPhase) {
        return;
    }

    state.hasReactedThisPhase = true;

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({
            type: 'reaction',
            emoji: emoji
        }));
    }
}

/**
 * Setup reaction bar click handlers
 */
export function setupReactionBar() {
    var bar = document.getElementById('reaction-bar');
    if (!bar) return;

    var buttons = bar.querySelectorAll('.reaction-btn');
    buttons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            var emoji = btn.getAttribute('data-emoji');
            if (emoji) {
                sendReaction(emoji);
            }
        });
    });
}

/**
 * Show floating reaction bubble from another player (Story 18.9)
 * @param {string} senderName - Name of player who sent reaction
 * @param {string} emoji - The emoji reaction
 */
export function showFloatingReaction(senderName, emoji) {
    var container = document.getElementById('reaction-container');
    if (!container) return;

    var bubble = document.createElement('div');
    bubble.className = 'reaction-bubble';
    bubble.textContent = senderName + ' ' + emoji;

    bubble.style.left = (20 + Math.random() * 60) + '%';

    container.appendChild(bubble);

    setTimeout(function() {
        bubble.remove();
    }, 3000);
}

/**
 * Update control bar button states based on phase
 * @param {string} phase - Current game phase
 */
export function updateControlBarState(phase) {
    var stopBtn = document.getElementById('stop-song-btn');
    var nextBtn = document.getElementById('next-round-admin-btn');

    if (phase === 'PLAYING') {
        resetSongStoppedState();
        if (stopBtn && !songStopped) {
            stopBtn.classList.remove('is-disabled');
            stopBtn.disabled = false;
        }
        if (nextBtn) {
            nextBtn.classList.remove('is-disabled');
            nextBtn.disabled = false;
            var labelEl = nextBtn.querySelector('.control-label');
            if (labelEl) labelEl.textContent = utils.t('game.skip');
        }
    } else if (phase === 'REVEAL') {
        if (stopBtn && !songStopped) {
            stopBtn.classList.remove('is-disabled');
            stopBtn.disabled = false;
        }
        if (nextBtn) {
            nextBtn.classList.remove('is-disabled');
            nextBtn.disabled = false;
            var labelEl = nextBtn.querySelector('.control-label');
            if (labelEl) labelEl.textContent = utils.t('game.next');
        }
    } else {
        if (nextBtn) {
            nextBtn.classList.add('is-disabled');
            nextBtn.disabled = true;
            var labelEl = nextBtn.querySelector('.control-label');
            if (labelEl) labelEl.textContent = utils.t('game.next');
        }
    }
}

/**
 * Handle Stop Song button (Story 16.6)
 */
function handleStopSong() {
    if (songStopped) return;

    if (!debounceAdminAction()) return;

    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        console.warn('[Beatify] Cannot stop song: WebSocket not connected');
        return;
    }

    var stopBtn = document.getElementById('stop-song-btn');
    if (stopBtn) {
        stopBtn.classList.add('is-disabled');
        stopBtn.disabled = true;
        var labelEl = stopBtn.querySelector('.control-label');
        if (labelEl) labelEl.textContent = utils.t('game.stopping');
    }

    state.ws.send(JSON.stringify({
        type: 'admin',
        action: 'stop_song'
    }));
}

/**
 * Handle Volume Up button
 */
function handleVolumeUp() {
    if (currentVolume >= 1.0) {
        showVolumeLimitFeedback('max');
        return;
    }
    if (!debounceAdminAction()) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;

    state.ws.send(JSON.stringify({
        type: 'admin',
        action: 'set_volume',
        direction: 'up'
    }));
}

/**
 * Handle Volume Down button
 */
function handleVolumeDown() {
    if (currentVolume <= 0.0) {
        showVolumeLimitFeedback('min');
        return;
    }
    if (!debounceAdminAction()) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;

    state.ws.send(JSON.stringify({
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
async function handleEndGame() {
    var confirmed = await showConfirmModal(
        utils.t('admin.endGameConfirm') || 'End Game?',
        utils.t('admin.endGameWarning') || 'All players will be disconnected.',
        utils.t('admin.endGame') || 'End Game',
        utils.t('common.cancel')
    );
    if (!confirmed) return;
    if (!debounceAdminAction()) return;
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        alert(utils.t('errors.CONNECTION_LOST'));
        return;
    }

    var endBtn = document.getElementById('end-game-btn');
    if (endBtn) {
        endBtn.disabled = true;
        var labelEl = endBtn.querySelector('.control-label');
        if (labelEl) labelEl.textContent = utils.t('game.ending');
    }

    state.ws.send(JSON.stringify({
        type: 'admin',
        action: 'end_game'
    }));
}

// Debounce state to prevent rapid clicks
var nextRoundPending = false;
var NEXT_ROUND_DEBOUNCE_MS = 2000;

/**
 * Handle next round button click
 */
export function handleNextRound() {
    if (nextRoundPending) {
        return;
    }

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        nextRoundPending = true;

        var revealBtn = document.getElementById('next-round-btn');
        var barBtn = document.getElementById('next-round-admin-btn');

        if (revealBtn) {
            revealBtn.disabled = true;
            revealBtn.textContent = utils.t('game.loading');
        }
        if (barBtn) {
            barBtn.disabled = true;
            var labelEl = barBtn.querySelector('.control-label');
            if (labelEl) labelEl.textContent = utils.t('game.wait');
        }

        state.ws.send(JSON.stringify({
            type: 'admin',
            action: 'next_round'
        }));

        // No setTimeout here — button stays disabled until the server
        // sends a state update (phase change to PLAYING). This prevents
        // the button from re-enabling before the new song is ready.
    }
}

/**
 * Reset next-round pending state. Called when a new game state arrives
 * (phase change), so the button can be used again in the next reveal.
 * Note: updateRevealView() in player-reveal.js already re-enables the
 * button and resets its text on each REVEAL phase — this is a defensive
 * measure to ensure consistent state even if the call order changes.
 */
export function resetNextRoundPending() {
    nextRoundPending = false;
    var revealBtn = document.getElementById('next-round-btn');
    var barBtn = document.getElementById('next-round-admin-btn');
    if (revealBtn) {
        revealBtn.disabled = false;
        revealBtn.textContent = utils.t('admin.nextRound');
    }
    if (barBtn) {
        barBtn.disabled = false;
        var labelEl = barBtn.querySelector('.control-label');
        if (labelEl) labelEl.textContent = utils.t('admin.nextRound');
    }
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
export function setupAdminControlBar() {
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
export function handleSongStopped() {
    songStopped = true;
    var stopBtn = document.getElementById('stop-song-btn');
    if (stopBtn) {
        stopBtn.classList.add('is-stopped');
        stopBtn.classList.add('is-disabled');
        stopBtn.disabled = true;
        var iconEl = stopBtn.querySelector('.control-icon');
        var labelEl = stopBtn.querySelector('.control-label');
        if (iconEl) iconEl.textContent = '✓';
        if (labelEl) labelEl.textContent = utils.t('game.stopped');
    }
}

/**
 * Reset song stopped state for new round (Story 6.2)
 */
export function resetSongStoppedState() {
    songStopped = false;
    var stopBtn = document.getElementById('stop-song-btn');
    if (stopBtn) {
        stopBtn.classList.remove('is-stopped');
        stopBtn.classList.remove('is-disabled');
        stopBtn.disabled = false;
        var iconEl = stopBtn.querySelector('.control-icon');
        var labelEl = stopBtn.querySelector('.control-label');
        if (iconEl) iconEl.textContent = '⏹️';
        if (labelEl) labelEl.textContent = utils.t('game.stop');
    }
}

/**
 * Handle volume changed response from server (Story 6.4)
 * @param {number} level - New volume level (0.0 to 1.0)
 */
export function handleVolumeChanged(level) {
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

/**
 * Setup reveal view event handlers
 * Story 18.3: Added tap-to-skip animations (AC4)
 */
export function setupRevealControls() {
    var nextRoundBtn = document.getElementById('next-round-btn');
    if (nextRoundBtn) {
        nextRoundBtn.addEventListener('click', handleNextRound);
    }

    var revealViewEl = document.getElementById('reveal-view');
    if (revealViewEl) {
        revealViewEl.addEventListener('click', function(e) {
            if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                return;
            }
            if (AnimationQueue.isRunning()) {
                AnimationQueue.skipAll();
            }
            stopConfetti();
        });
    }
}

// ============================================
// Intro Splash Modal (Issue #292)
// ============================================

/**
 * Show the intro splash modal
 * @param {boolean} isAdmin - Whether the current player is admin
 */
export function showIntroSplashModal(isAdmin) {
    var modal = document.getElementById('intro-splash-modal');
    if (!modal) return;
    modal.classList.remove('hidden');

    var confirmBtn = document.getElementById('intro-splash-confirm-btn');
    var waitingMsg = modal.querySelector('.intro-splash-modal-waiting');
    if (confirmBtn) {
        if (isAdmin) {
            confirmBtn.classList.remove('hidden');
            if (waitingMsg) waitingMsg.classList.add('hidden');
            confirmBtn.onclick = function() {
                if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                    state.ws.send(JSON.stringify({ type: 'admin', action: 'confirm_intro_splash' }));
                }
            };
        } else {
            confirmBtn.classList.add('hidden');
            if (waitingMsg) waitingMsg.classList.remove('hidden');
        }
    }
}

/**
 * Hide the intro splash modal
 */
export function hideIntroSplashModal() {
    var modal = document.getElementById('intro-splash-modal');
    if (!modal) return;
    modal.classList.add('hidden');
}
