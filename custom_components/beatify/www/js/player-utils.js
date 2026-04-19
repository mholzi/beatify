/**
 * Beatify Player - Utility Module
 * AnimationQueue, easing functions, score popups, confetti helpers, DOM utilities
 */

var utils = window.BeatifyUtils || {};

// ============================================
// Shared Mutable State (imported by all modules)
// ============================================

export var state = {
    ws: null,
    playerName: null,
    isAdmin: false,
    reconnectAttempts: 0,
    isReconnecting: false,
    intentionalLeave: false,
    hasReactedThisPhase: false,
    currentRoundNumber: 0,
    gameId: new URLSearchParams(window.location.search).get('game'),
    // Connection functions set by core module (avoids circular deps)
    connectWithSession: null,
    connectWebSocket: null
};

// ============================================
// View Management
// ============================================

var loadingView = document.getElementById('loading-view');
var notFoundView = document.getElementById('not-found-view');
var endedView = document.getElementById('ended-view');
var inProgressView = document.getElementById('in-progress-view');
var joinView = document.getElementById('join-view');
var tourView = document.getElementById('tour-view');
var readyView = document.getElementById('ready-view');
var lobbyView = document.getElementById('lobby-view');
var gameView = document.getElementById('game-view');
var revealView = document.getElementById('reveal-view');
var pausedView = document.getElementById('paused-view');
var endView = document.getElementById('end-view');
var connectionLostView = document.getElementById('connection-lost-view');

var allViews = [loadingView, notFoundView, endedView, inProgressView, joinView, tourView, readyView, lobbyView, gameView, revealView, pausedView, endView, connectionLostView];

/**
 * Show a specific view and hide all others
 * Wrapped with auto-focus and energy level (Story 9.9)
 * @param {string} viewId - ID of view to show
 */
export function showView(viewId) {
    utils.showView(allViews, viewId);

    // Post-QR onboarding tour + transition ready screen have their own
    // branding (wordmark hero inside ready-view, step progress in tour-view).
    // Hide the outer .player-header when either is active so the logo doesn't
    // double up with the ready wordmark + clutter the tour header.
    var isLearningScreen = viewId === 'tour-view' || viewId === 'ready-view';
    if (document.body) {
        document.body.classList.toggle('is-learning-screen', isLearningScreen);
    }

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
}

// ============================================
// Confirmation Modal
// ============================================

/**
 * Show a styled confirmation modal instead of browser confirm()
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @param {string} [confirmText] - Text for confirm button
 * @param {string} [cancelText] - Text for cancel button
 * @returns {Promise<boolean>} - Resolves to true if confirmed, false if cancelled
 */
export function showConfirmModal(title, message, confirmText, cancelText) {
    return new Promise(function(resolve) {
        var modal = document.getElementById('confirm-modal');
        var titleEl = document.getElementById('confirm-modal-title');
        var messageEl = document.getElementById('confirm-modal-message');
        var yesBtn = document.getElementById('confirm-modal-yes');
        var noBtn = document.getElementById('confirm-modal-no');

        if (!modal || !titleEl || !messageEl || !yesBtn || !noBtn) {
            resolve(confirm(message || title));
            return;
        }

        titleEl.textContent = title;
        messageEl.textContent = message;
        yesBtn.textContent = confirmText || utils.t('common.confirm') || 'Confirm';
        noBtn.textContent = cancelText || utils.t('common.cancel') || 'Cancel';

        modal.classList.remove('hidden');

        function cleanup() {
            modal.classList.add('hidden');
            yesBtn.removeEventListener('click', onConfirm);
            noBtn.removeEventListener('click', onCancel);
            backdrop.removeEventListener('click', onCancel);
        }

        function onConfirm() {
            cleanup();
            resolve(true);
        }

        function onCancel() {
            cleanup();
            resolve(false);
        }

        var backdrop = modal.querySelector('.modal-backdrop');

        yesBtn.addEventListener('click', onConfirm);
        noBtn.addEventListener('click', onCancel);
        if (backdrop) backdrop.addEventListener('click', onCancel);
    });
}

// ============================================
// HTML Escaping
// ============================================

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
export function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// Score Animation Utilities (Story 13.2)
// ============================================

/**
 * Check if user prefers reduced motion
 * @returns {boolean} True if reduced motion is preferred
 */
export function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Easing function for smooth deceleration
 * @param {number} t - Progress value 0-1
 * @returns {number} Eased value
 */
export function easeOutQuart(t) {
    return 1 - Math.pow(1 - t, 4);
}

/**
 * Animate a numeric value from start to end
 * Story 18.3: Now device-tier aware with instant updates for low-end devices
 * @param {HTMLElement} element - Element to update textContent
 * @param {number} start - Starting value
 * @param {number} end - Ending value
 * @param {number} duration - Animation duration in ms
 * @param {Function} easing - Easing function (optional, defaults to easeOutQuart)
 * @returns {Object} Controller with cancel() and skipToEnd() methods
 */
export function animateValue(element, start, end, duration, easing) {
    if (prefersReducedMotion() || start === end) {
        element.textContent = end;
        return { cancel: function() {}, skipToEnd: function() { element.textContent = end; } };
    }

    var quality = AnimationUtils.getQualitySettings();
    if (quality.scoreDuration === 0) {
        element.textContent = end;
        return { cancel: function() {}, skipToEnd: function() { element.textContent = end; } };
    }

    var adjustedDuration = Math.min(duration, quality.scoreDuration || duration);

    easing = easing || easeOutQuart;
    var startTime = null;
    var animationId = null;
    var cancelled = false;
    var finalValue = end;

    function step(timestamp) {
        if (cancelled) return;

        if (!startTime) startTime = timestamp;
        var elapsed = timestamp - startTime;
        var progress = Math.min(elapsed / adjustedDuration, 1);
        var easedProgress = easing(progress);

        var currentValue = Math.round(start + (finalValue - start) * easedProgress);
        element.textContent = currentValue;

        if (progress < 1) {
            animationId = requestAnimationFrame(step);
        }
    }

    animationId = requestAnimationFrame(step);

    return {
        cancel: function() {
            cancelled = true;
            if (animationId) {
                cancelAnimationFrame(animationId);
            }
        },
        skipToEnd: function() {
            cancelled = true;
            if (animationId) {
                cancelAnimationFrame(animationId);
            }
            element.textContent = finalValue;
        }
    };
}

/**
 * Animate score change with visual effects
 * @param {HTMLElement} element - Score element to animate
 * @param {number} oldScore - Previous score value
 * @param {number} newScore - New score value
 * @param {Object} options - Effect options: { betWon, betLost, streakMilestone, isBigScore }
 */
export function animateScoreChange(element, oldScore, newScore, options) {
    options = options || {};

    var duration = 500;
    if (options.betWon) {
        duration = 800;
    } else if (options.isBigScore) {
        duration = 700;
    } else if (options.betLost) {
        duration = 400;
    }

    element.classList.add('score-animating');

    var animationClass = null;
    if (options.betWon) {
        animationClass = 'score-glow-gold';
    } else if (options.betLost) {
        animationClass = 'score-shake';
        element.classList.add('score-flash-red');
    } else if (options.streakMilestone) {
        animationClass = 'score-burst';
    } else if (options.isBigScore) {
        animationClass = 'score-pop';
    }

    if (animationClass && !prefersReducedMotion()) {
        element.classList.add(animationClass);
    }

    animateValue(element, oldScore, newScore, duration);

    function cleanup() {
        element.classList.remove('score-animating');
        if (animationClass) {
            element.classList.remove(animationClass);
        }
        element.classList.remove('score-flash-red');
    }

    if (animationClass && !prefersReducedMotion()) {
        element.addEventListener('animationend', function onEnd() {
            element.removeEventListener('animationend', onEnd);
            cleanup();
        });
    } else {
        setTimeout(cleanup, duration + 50);
    }
}

/**
 * Show floating points popup above target element
 * @param {HTMLElement} targetElement - Element to position popup relative to
 * @param {number} points - Points value to display
 * @param {Object} options - Options: { text, isStreak, isBetWin }
 */
export function showPointsPopup(targetElement, points, options) {
    options = options || {};

    if (prefersReducedMotion()) {
        return;
    }

    var popup = document.createElement('div');
    popup.className = 'points-popup';
    popup.textContent = options.text || ('+' + points);

    if (options.isStreak) {
        popup.classList.add('points-popup--streak');
    } else if (options.isBetWin) {
        popup.classList.add('points-popup--gold');
    }

    var rect = targetElement.getBoundingClientRect();
    popup.style.left = (rect.left + rect.width / 2) + 'px';
    popup.style.top = rect.top + 'px';

    document.body.appendChild(popup);

    popup.addEventListener('animationend', function() {
        if (popup.parentNode) {
            popup.parentNode.removeChild(popup);
        }
    });

    setTimeout(function() {
        if (popup.parentNode) {
            popup.parentNode.removeChild(popup);
        }
    }, 1200);
}

// ============================================
// Previous State Cache (Story 13.2)
// ============================================

export var previousState = {
    players: {},
    leaderboard: [],
    initialized: false
};

/**
 * Check if previous state has been initialized
 * @returns {boolean} True if state has been initialized
 */
export function isPreviousStateInitialized() {
    return previousState.initialized;
}

var STREAK_MILESTONES = [3, 5, 10, 15, 20, 25];

/**
 * Check if a streak milestone was just reached
 * @param {number} oldStreak - Previous streak value
 * @param {number} newStreak - Current streak value
 * @returns {number|null} Milestone reached or null
 */
export function isStreakMilestone(oldStreak, newStreak) {
    for (var i = 0; i < STREAK_MILESTONES.length; i++) {
        var milestone = STREAK_MILESTONES[i];
        if (oldStreak < milestone && newStreak >= milestone) {
            return milestone;
        }
    }
    return null;
}

/**
 * Detect rank changes in leaderboard
 * @param {Array} newLeaderboard - New leaderboard array
 * @returns {Object} Map of name -> 'up', 'down', 'new', or undefined
 */
export function detectRankChanges(newLeaderboard) {
    var newOrder = newLeaderboard.map(function(entry) { return entry.name; });
    var changes = {};

    newOrder.forEach(function(name, newRank) {
        var oldRank = previousState.leaderboard.indexOf(name);
        if (oldRank === -1) {
            changes[name] = 'new';
        } else if (newRank < oldRank) {
            changes[name] = 'up';
        } else if (newRank > oldRank) {
            changes[name] = 'down';
        }
    });

    return changes;
}

/**
 * Update previous state cache after rendering
 * @param {Array} players - Current players array
 * @param {Array} leaderboard - Current leaderboard array
 */
export function updatePreviousState(players, leaderboard) {
    previousState.players = {};
    players.forEach(function(player) {
        previousState.players[player.name] = {
            score: player.score,
            rank: player.rank || 0,
            streak: player.streak || 0
        };
    });

    if (leaderboard) {
        previousState.leaderboard = leaderboard.map(function(entry) {
            return entry.name;
        });
    }

    previousState.initialized = true;
}

/**
 * Reset previous state (called on game end/new game)
 */
export function resetPreviousState() {
    previousState.players = {};
    previousState.leaderboard = [];
    previousState.initialized = false;
}

// ============================================
// Animation Performance Utilities (Story 18.3)
// ============================================

export var AnimationUtils = (function() {
    var reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    var _prefersReducedMotion = reducedMotionQuery.matches;

    reducedMotionQuery.addEventListener('change', function(e) {
        _prefersReducedMotion = e.matches;
    });

    var _deviceTier = null;

    function getDeviceTier() {
        if (_deviceTier !== null) return _deviceTier;

        var cores = navigator.hardwareConcurrency || 2;
        var memory = navigator.deviceMemory || 4;

        var isIOSSafari = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;

        if (cores <= 2 || memory <= 2) {
            _deviceTier = 'low';
        } else if (cores <= 4 || memory <= 4 || isIOSSafari) {
            _deviceTier = 'medium';
        } else {
            _deviceTier = 'high';
        }

        return _deviceTier;
    }

    getDeviceTier();

    return {
        prefersReducedMotion: function() {
            return _prefersReducedMotion;
        },

        getDeviceTier: getDeviceTier,

        getQualitySettings: function() {
            var tier = getDeviceTier();
            if (_prefersReducedMotion) {
                return {
                    confettiParticles: 0,
                    scoreDuration: 0,
                    leaderboardAnimation: 'none',
                    neonGlow: false,
                    enableAnimations: false
                };
            }
            switch (tier) {
                case 'low':
                    return {
                        confettiParticles: 5,
                        scoreDuration: 0,
                        leaderboardAnimation: 'none',
                        neonGlow: false,
                        enableAnimations: true
                    };
                case 'medium':
                    return {
                        confettiParticles: 10,
                        scoreDuration: 300,
                        leaderboardAnimation: 'simplified',
                        neonGlow: false,
                        enableAnimations: true
                    };
                default:
                    return {
                        confettiParticles: 15,
                        scoreDuration: 500,
                        leaderboardAnimation: 'full',
                        neonGlow: true,
                        enableAnimations: true
                    };
            }
        },

        ifMotionAllowed: function(animationFn, fallbackFn) {
            if (_prefersReducedMotion) {
                if (fallbackFn) fallbackFn();
            } else {
                animationFn();
            }
        },

        withWillChange: function(element, properties, durationMs) {
            if (!element) return;
            element.style.willChange = properties;
            setTimeout(function() {
                if (element && element.style) {
                    element.style.willChange = 'auto';
                }
            }, (durationMs || 500) + 100);
        }
    };
})();

/**
 * Interruptible animation queue for reveal phase (Story 18.3)
 */
export var AnimationQueue = (function() {
    var queue = [];
    var running = false;
    var currentAnimation = null;
    var animationTimeoutId = null;
    var MAX_ANIMATION_DURATION = 2000;

    function processNext() {
        if (animationTimeoutId) {
            clearTimeout(animationTimeoutId);
            animationTimeoutId = null;
        }

        if (queue.length === 0) {
            running = false;
            currentAnimation = null;
            return;
        }
        currentAnimation = queue.shift();

        animationTimeoutId = setTimeout(function() {
            if (currentAnimation && currentAnimation.skipToEnd) {
                currentAnimation.skipToEnd();
            }
            processNext();
        }, MAX_ANIMATION_DURATION);

        currentAnimation.run(function() {
            if (animationTimeoutId) {
                clearTimeout(animationTimeoutId);
                animationTimeoutId = null;
            }
            processNext();
        });
    }

    return {
        add: function(animation) {
            queue.push(animation);
            if (!running) {
                running = true;
                processNext();
            }
        },

        skipAll: function() {
            if (animationTimeoutId) {
                clearTimeout(animationTimeoutId);
                animationTimeoutId = null;
            }
            if (currentAnimation && currentAnimation.skipToEnd) {
                currentAnimation.skipToEnd();
            }
            queue.forEach(function(anim) {
                if (anim.skipToEnd) anim.skipToEnd();
            });
            queue = [];
            running = false;
            currentAnimation = null;
        },

        clear: function() {
            if (animationTimeoutId) {
                clearTimeout(animationTimeoutId);
                animationTimeoutId = null;
            }
            queue = [];
            running = false;
            currentAnimation = null;
        },

        isRunning: function() {
            return running;
        },

        getMaxDuration: function() {
            return MAX_ANIMATION_DURATION;
        }
    };
})();

// ============================================
// Lazy Loading Configuration (Story 18.1)
// ============================================

export var LEADERBOARD_LAZY_CONFIG = {
    VISIBLE_BUFFER: 2,
    ENTRY_HEIGHT: 48,
    MIN_PLAYERS_FOR_LAZY: 10,
    ROOT_MARGIN: '96px 0px',
    DEFAULT_VIEWPORT_HEIGHT: 280
};

export var lazyLeaderboardState = {
    observer: null,
    fullData: [],
    visibleRange: { start: 0, end: 10 },
    listEl: null,
    isLazyEnabled: false
};

/**
 * Initialize IntersectionObserver for lazy leaderboard loading
 * @param {Element} listEl - Leaderboard list element
 */
export function initLeaderboardObserver(listEl) {
    if (!listEl) return;

    if (lazyLeaderboardState.observer && lazyLeaderboardState.listEl !== listEl) {
        lazyLeaderboardState.observer.disconnect();
        lazyLeaderboardState.observer = null;
    }

    if (lazyLeaderboardState.observer) return;

    lazyLeaderboardState.listEl = listEl;

    lazyLeaderboardState.observer = new IntersectionObserver(function(entries) {
        entries.forEach(function(entry) {
            if (!entry.isIntersecting || !lazyLeaderboardState.isLazyEnabled) return;

            var fullData = lazyLeaderboardState.fullData;
            var range = lazyLeaderboardState.visibleRange;
            var buffer = LEADERBOARD_LAZY_CONFIG.VISIBLE_BUFFER;

            if (entry.target.classList.contains('leaderboard-sentinel--top')) {
                if (range.start > 0) {
                    var newStart = Math.max(0, range.start - buffer);
                    lazyLeaderboardState.visibleRange.start = newStart;
                    renderLazyLeaderboardRange();
                }
            } else if (entry.target.classList.contains('leaderboard-sentinel--bottom')) {
                if (range.end < fullData.length) {
                    var newEnd = Math.min(fullData.length, range.end + buffer);
                    lazyLeaderboardState.visibleRange.end = newEnd;
                    renderLazyLeaderboardRange();
                }
            }
        });
    }, {
        root: listEl,
        rootMargin: LEADERBOARD_LAZY_CONFIG.ROOT_MARGIN,
        threshold: 0
    });
}

/**
 * Render the visible range of leaderboard entries with spacers
 */
export function renderLazyLeaderboardRange() {
    var listEl = lazyLeaderboardState.listEl;
    var fullData = lazyLeaderboardState.fullData;
    var range = lazyLeaderboardState.visibleRange;

    if (!listEl || !fullData.length) return;

    var entryHeight = LEADERBOARD_LAZY_CONFIG.ENTRY_HEIGHT;
    var topSpacerHeight = range.start * entryHeight;
    var bottomSpacerHeight = (fullData.length - range.end) * entryHeight;

    var scrollTop = listEl.scrollTop;

    var html = '';

    if (topSpacerHeight > 0) {
        html += '<div class="leaderboard-spacer-top" style="height: ' + topSpacerHeight + 'px;"></div>';
    }

    html += '<div class="leaderboard-sentinel leaderboard-sentinel--top" style="height: 1px;"></div>';

    for (var i = range.start; i < range.end && i < fullData.length; i++) {
        html += renderLeaderboardEntry(fullData[i]);
    }

    html += '<div class="leaderboard-sentinel leaderboard-sentinel--bottom" style="height: 1px;"></div>';

    if (bottomSpacerHeight > 0) {
        html += '<div class="leaderboard-spacer-bottom" style="height: ' + bottomSpacerHeight + 'px;"></div>';
    }

    listEl.innerHTML = html;
    listEl.scrollTop = scrollTop;

    if (lazyLeaderboardState.observer) {
        var sentinels = listEl.querySelectorAll('.leaderboard-sentinel');
        sentinels.forEach(function(sentinel) {
            lazyLeaderboardState.observer.observe(sentinel);
        });
    }
}

/**
 * Render a single leaderboard entry HTML
 * @param {Object} entry - Leaderboard entry data
 * @returns {string} HTML string
 */
export function renderLeaderboardEntry(entry) {
    if (!entry) return '';

    if (entry.separator) {
        return '<div class="leaderboard-separator">...</div>';
    }

    var name = entry.name || 'Unknown';
    var rank = entry.rank || 0;
    var score = entry.score || 0;

    var rankClass = rank <= 3 ? 'is-top-' + rank : '';
    var currentClass = entry.is_current ? 'is-current' : '';

    var animationClass = '';
    if (entry.rank_change > 0 || entry._rankChange === 'up') {
        animationClass = 'leaderboard-entry--climbing leaderboard-entry--slide-up';
    } else if (entry.rank_change < 0 || entry._rankChange === 'down') {
        animationClass = 'leaderboard-entry--falling leaderboard-entry--slide-down';
    }

    var changeIndicator = '';
    if (entry.rank_change > 0) {
        changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
    } else if (entry.rank_change < 0) {
        changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';
    }

    var streakIndicator = '';
    if (entry.streak >= 2) {
        var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
        streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
    }

    var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
    var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';

    var displayScore = entry._displayScore !== undefined ? entry._displayScore : score;

    return '<div class="leaderboard-entry ' + rankClass + ' ' + currentClass + ' ' + animationClass + ' ' + disconnectedClass + '" data-rank="' + rank + '" data-name="' + escapeHtml(name) + '">' +
        '<span class="entry-rank">#' + rank + '</span>' +
        '<span class="entry-name">' + escapeHtml(name) + awayBadge + '</span>' +
        '<span class="entry-meta">' +
            streakIndicator +
            changeIndicator +
        '</span>' +
        '<span class="entry-score" data-prev-score="' + (entry._prevScore || score) + '">' + displayScore + '</span>' +
    '</div>';
}

/**
 * Calculate initial visible range based on viewport and current player position
 * @param {Array} displayList - Processed leaderboard data
 * @param {string} currentPlayerName - Name of current player
 * @returns {Object} Range object with start and end indices
 */
export function calculateInitialVisibleRange(displayList, currentPlayerName) {
    var config = LEADERBOARD_LAZY_CONFIG;
    var viewportHeight = lazyLeaderboardState.listEl
        ? lazyLeaderboardState.listEl.clientHeight || config.DEFAULT_VIEWPORT_HEIGHT
        : config.DEFAULT_VIEWPORT_HEIGHT;
    var viewportEntries = Math.ceil(viewportHeight / config.ENTRY_HEIGHT);
    var buffer = config.VISIBLE_BUFFER;

    var currentIdx = -1;
    for (var i = 0; i < displayList.length; i++) {
        if (displayList[i].name === currentPlayerName) {
            currentIdx = i;
            break;
        }
    }

    var start, end;
    if (currentIdx === -1 || currentIdx < viewportEntries) {
        start = 0;
        end = Math.min(displayList.length, viewportEntries + buffer * 2);
    } else if (currentIdx >= displayList.length - viewportEntries) {
        start = Math.max(0, displayList.length - viewportEntries - buffer);
        end = displayList.length;
    } else {
        start = Math.max(0, currentIdx - Math.floor(viewportEntries / 2) - buffer);
        end = Math.min(displayList.length, currentIdx + Math.ceil(viewportEntries / 2) + buffer);
    }

    return { start: start, end: end };
}

/**
 * Clean up lazy loading observer
 */
export function cleanupLeaderboardObserver() {
    if (lazyLeaderboardState.observer) {
        lazyLeaderboardState.observer.disconnect();
        lazyLeaderboardState.observer = null;
    }
    lazyLeaderboardState.isLazyEnabled = false;
    lazyLeaderboardState.fullData = [];
}

/**
 * Setup resize/orientation change handler for lazy leaderboard (Story 18.1)
 */
export function setupLeaderboardResizeHandler() {
    var resizeTimeout;

    function handleResize() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(function() {
            if (lazyLeaderboardState.isLazyEnabled && lazyLeaderboardState.fullData.length > 0) {
                lazyLeaderboardState.visibleRange = calculateInitialVisibleRange(
                    lazyLeaderboardState.fullData,
                    state.playerName
                );
                renderLazyLeaderboardRange();
            }
        }, 150);
    }

    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);
}

// ============================================
// QR Section - Responsive Collapse (Story 18.8)
// ============================================

export function initQrCollapsible() {
    var qrSection = document.getElementById('qr-share-area');
    if (!qrSection || qrSection.tagName !== 'DETAILS') return;

    var STORAGE_KEY = 'beatify_qr_expanded';
    var MOBILE_BREAKPOINT = 768;

    var savedState = sessionStorage.getItem(STORAGE_KEY);

    if (savedState !== null) {
        qrSection.open = savedState === 'true';
    } else {
        qrSection.open = window.innerWidth >= MOBILE_BREAKPOINT;
    }

    qrSection.addEventListener('toggle', function() {
        sessionStorage.setItem(STORAGE_KEY, qrSection.open.toString());
    });
}

// ============================================
// Lobby Collapsible Sections
// ============================================

export function setupLobbyCollapsible() {
    var collapsibleHeaders = document.querySelectorAll('.lobby-container--compact .section-header-collapsible');

    collapsibleHeaders.forEach(function(header) {
        header.addEventListener('click', function() {
            var section = header.closest('.section-collapsible');
            if (!section) return;

            var isCollapsed = section.classList.contains('collapsed');
            section.classList.toggle('collapsed');
            header.setAttribute('aria-expanded', isCollapsed ? 'true' : 'false');
        });
    });
}

// ============================================
// Virtual List for Player Lists (Story 18.2)
// ============================================

export var VIRTUAL_LIST_CONFIG = {
    ITEM_HEIGHT: 60,
    OVERSCAN: 3,
    THRESHOLD: 15,
    CONTAINER_HEIGHT: 320
};

export var virtualPlayerList = {
    container: null,
    items: [],
    scrollTop: 0,
    isVirtual: false,
    topSpacer: null,
    bottomSpacer: null,
    contentWrapper: null,
    scrollHandler: null,
    resizeHandler: null
};

export function initVirtualPlayerList(container) {
    if (!container) return;

    virtualPlayerList.container = container;

    var ticking = false;
    virtualPlayerList.scrollHandler = function() {
        virtualPlayerList.scrollTop = container.scrollTop;
        if (!ticking) {
            requestAnimationFrame(function() {
                renderVirtualPlayerList();
                ticking = false;
            });
            ticking = true;
        }
    };

    var resizeTimeout;
    virtualPlayerList.resizeHandler = function() {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(function() {
            if (virtualPlayerList.isVirtual) {
                renderVirtualPlayerList();
            }
        }, 100);
    };

    container.addEventListener('scroll', virtualPlayerList.scrollHandler, { passive: true });
    window.addEventListener('resize', virtualPlayerList.resizeHandler);
}

export function setVirtualPlayerListItems(items, renderItemFn) {
    virtualPlayerList.items = items;
    virtualPlayerList.renderItem = renderItemFn;

    var container = virtualPlayerList.container;
    if (!container) return;

    var prevScrollTop = container.scrollTop;
    var wasVirtual = virtualPlayerList.isVirtual;

    if (items.length < VIRTUAL_LIST_CONFIG.THRESHOLD) {
        virtualPlayerList.isVirtual = false;
        container.classList.remove('player-list--virtual');
        renderAllPlayerCards(items, renderItemFn);
    } else {
        virtualPlayerList.isVirtual = true;
        container.classList.add('player-list--virtual');
        setupVirtualContainer();
        renderVirtualPlayerList();
    }

    if (wasVirtual !== virtualPlayerList.isVirtual && prevScrollTop > 0) {
        container.scrollTop = prevScrollTop;
        virtualPlayerList.scrollTop = prevScrollTop;
    }
}

function setupVirtualContainer() {
    var container = virtualPlayerList.container;
    if (!container) return;

    container.innerHTML = '';

    var topSpacer = document.createElement('div');
    topSpacer.className = 'virtual-spacer-top';
    virtualPlayerList.topSpacer = topSpacer;

    var contentWrapper = document.createElement('div');
    contentWrapper.className = 'virtual-content-wrapper';
    virtualPlayerList.contentWrapper = contentWrapper;

    var bottomSpacer = document.createElement('div');
    bottomSpacer.className = 'virtual-spacer-bottom';
    virtualPlayerList.bottomSpacer = bottomSpacer;

    container.appendChild(topSpacer);
    container.appendChild(contentWrapper);
    container.appendChild(bottomSpacer);
}

function renderVirtualPlayerList() {
    var config = VIRTUAL_LIST_CONFIG;
    var items = virtualPlayerList.items;
    var container = virtualPlayerList.container;
    var contentWrapper = virtualPlayerList.contentWrapper;

    if (!container || !contentWrapper || !items.length) return;

    var containerHeight = container.clientHeight || config.CONTAINER_HEIGHT;
    var scrollTop = virtualPlayerList.scrollTop;
    var itemHeight = config.ITEM_HEIGHT;
    var overscan = config.OVERSCAN;

    var startIdx = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan);
    var endIdx = Math.min(
        items.length,
        Math.ceil((scrollTop + containerHeight) / itemHeight) + overscan
    );

    if (virtualPlayerList.topSpacer) {
        virtualPlayerList.topSpacer.style.height = (startIdx * itemHeight) + 'px';
    }
    if (virtualPlayerList.bottomSpacer) {
        virtualPlayerList.bottomSpacer.style.height = ((items.length - endIdx) * itemHeight) + 'px';
    }

    var html = '';
    for (var i = startIdx; i < endIdx; i++) {
        html += virtualPlayerList.renderItem(items[i], i);
    }

    contentWrapper.innerHTML = html;
}

function renderAllPlayerCards(items, renderItemFn) {
    var container = virtualPlayerList.container;
    if (!container) return;

    var html = '';
    for (var i = 0; i < items.length; i++) {
        html += renderItemFn(items[i], i);
    }
    container.innerHTML = html;
}

export function cleanupVirtualPlayerList() {
    var container = virtualPlayerList.container;
    if (container && virtualPlayerList.scrollHandler) {
        container.removeEventListener('scroll', virtualPlayerList.scrollHandler);
    }
    if (virtualPlayerList.resizeHandler) {
        window.removeEventListener('resize', virtualPlayerList.resizeHandler);
    }
    virtualPlayerList.container = null;
    virtualPlayerList.items = [];
    virtualPlayerList.isVirtual = false;
    virtualPlayerList.topSpacer = null;
    virtualPlayerList.bottomSpacer = null;
    virtualPlayerList.contentWrapper = null;
}

// ============================================
// Energy Escalation System (Story 9.9)
// ============================================

/**
 * Set energy level class on body based on game phase
 * @param {string} level - 'calm', 'warmup', or 'party'
 */
export function setEnergyLevel(level) {
    document.body.classList.remove('energy-calm', 'energy-warmup', 'energy-party');
    document.body.classList.add('energy-' + level);
}

// ============================================
// Confetti System (Story 14.5)
// ============================================

var confettiAnimationId = null;
var confettiIntervalId = null;

/**
 * Trigger confetti celebration animation (Story 14.5)
 * Story 18.3: Now device-aware with reduced particle counts on low-end devices
 * @param {string} type - 'exact', 'record', 'winner', or 'perfect'
 */
export function triggerConfetti(type) {
    if (AnimationUtils.prefersReducedMotion()) {
        showStaticCelebration();
        return;
    }

    if (typeof confetti === 'undefined') {
        console.warn('[Confetti] Library not loaded');
        return;
    }

    stopConfetti();

    var quality = AnimationUtils.getQualitySettings();
    var baseParticles = quality.confettiParticles;

    if (baseParticles === 0) {
        showStaticCelebration();
        return;
    }

    var tier = AnimationUtils.getDeviceTier();
    var durationMultiplier = tier === 'low' ? 0.5 : (tier === 'medium' ? 0.75 : 1);

    type = type || 'exact';

    switch (type) {
        case 'exact':
            var exactDuration = Math.round(2000 * durationMultiplier);
            var exactEnd = Date.now() + exactDuration;
            (function exactFrame() {
                confetti({
                    particleCount: baseParticles,
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
            var recordDuration = Math.round(3000 * durationMultiplier);
            var recordEnd = Date.now() + recordDuration;
            (function recordFrame() {
                confetti({
                    particleCount: Math.round(baseParticles * 0.67),
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
            var winnerDuration = Math.round(4000 * durationMultiplier);
            var winnerEnd = Date.now() + winnerDuration;
            (function winnerFrame() {
                confetti({
                    particleCount: Math.round(baseParticles * 0.67),
                    angle: 60,
                    spread: 55,
                    origin: { x: 0 },
                    colors: ['#ff2d6a', '#00f5ff', '#00ff88', '#ffdd00']
                });
                confetti({
                    particleCount: Math.round(baseParticles * 0.67),
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
            var perfectDuration = Math.round(5000 * durationMultiplier);
            var perfectEnd = Date.now() + perfectDuration;

            confettiIntervalId = setInterval(function() {
                confetti({
                    particleCount: baseParticles * 2,
                    spread: 100,
                    origin: { y: 0.6 },
                    colors: ['#FFD700', '#FFA500', '#FFEC8B']
                });
            }, tier === 'low' ? 750 : 500);

            setTimeout(function() {
                if (confettiIntervalId) {
                    clearInterval(confettiIntervalId);
                    confettiIntervalId = null;
                }
            }, perfectDuration);

            (function perfectFrame() {
                confetti({
                    particleCount: Math.round(baseParticles * 0.5),
                    angle: 60,
                    spread: 55,
                    origin: { x: 0 },
                    colors: ['#FFD700', '#ff2d6a', '#00f5ff', '#00ff88']
                });
                confetti({
                    particleCount: Math.round(baseParticles * 0.5),
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
            console.warn('[Confetti] Unknown type:', type);
    }
}

/**
 * Stop any ongoing confetti animations
 */
export function stopConfetti() {
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

/**
 * Show static celebration for reduced motion users (AC5)
 */
// ============================================
// Screen Wake Lock (#622)
// Prevents screen from dimming/locking during gameplay.
// Supported on iOS Safari 16.4+, Chrome, Edge; fails silently elsewhere.
// ============================================

var _wakeLock = null;

export async function requestWakeLock() {
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

export function releaseWakeLock() {
    if (_wakeLock) {
        _wakeLock.release();
        _wakeLock = null;
    }
}

export function showStaticCelebration() {
    var emotionEl = document.getElementById('reveal-emotion');
    if (emotionEl) {
        var existingIcon = emotionEl.querySelector('.celebration-icon');
        if (!existingIcon) {
            var icon = document.createElement('span');
            icon.className = 'celebration-icon';
            icon.textContent = ' 🎉';
            emotionEl.appendChild(icon);
        }
    }
}
