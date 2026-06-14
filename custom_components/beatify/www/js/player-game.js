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

// #1279 step 6/6: self-contained game clusters extracted to ./player-game/.
// player-game.js stays the public face and re-exports their consumer-facing
// functions so player-core.js / player-reveal.js import surfaces are unchanged.
export { startCountdown, stopCountdown } from './player-game/timer.js';
export {
    renderArtistChallenge, handleArtistGuessAck,
    resetArtistChallengeState, renderArtistReveal
} from './player-game/artist-challenge.js';
export {
    renderMovieChallenge, handleMovieGuessAck,
    resetMovieChallengeState, renderMovieReveal
} from './player-game/movie-challenge.js';

// Cross-cluster calls: updateGameView() and resetSubmissionState() (still in
// this file) call into the extracted artist/movie clusters. These are runtime
// (event-driven), not module-init, so the circular import is safe.
import {
    renderArtistChallenge, resetArtistChallengeState
} from './player-game/artist-challenge.js';
import {
    renderMovieChallenge, resetMovieChallengeState
} from './player-game/movie-challenge.js';

var utils = window.BeatifyUtils || {};
var debug = utils.debug || function() {};

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

    // Issue #827: Sudden Death — gate the play UI on whether the current
    // player is eliminated. Must run before syncing the chip row / submission
    // tracker so the eliminated-view album art and locked state are consistent.
    applySuddenDeathState(data);

    // Arcade chip row — hide the wrapper when every child chip is hidden
    syncArcChipRow();

    // Arcade no-bonus filler — shown when neither challenge is active
    syncNoBonusFiller(data);

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

    renderTitleArtistInput(data);
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

    debug('[Metadata] Updated:', song.artist, '-', song.title);
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
/**
 * Toggle the arcade chip row visibility based on whether any chip has content.
 * Chip ids live inside #arc-chip-row and toggle their own .hidden class from
 * elsewhere (difficulty badge, steal indicator, closest-wins badge, intro,
 * last-round). We just hide the wrapper when everyone is hidden to avoid an
 * empty margin eating vertical space.
 */
function syncArcChipRow() {
    var row = document.getElementById('arc-chip-row');
    if (!row) return;
    var childIds = [
        'game-difficulty-badge',
        'steal-indicator',
        'closest-wins-badge',
        'intro-badge',
        'last-round-banner'
    ];
    var anyVisible = childIds.some(function(id) {
        var el = document.getElementById(id);
        return el && !el.classList.contains('hidden');
    });
    row.classList.toggle('hidden', !anyVisible);
}

/**
 * Show the "No bonus this round — nail the year" filler when neither artist
 * nor movie challenge is active. Keeps the submit button from jumping up and
 * makes empty space feel intentional.
 */
function syncNoBonusFiller(data) {
    var filler = document.getElementById('no-bonus-filler');
    if (!filler) return;
    var hasArtist = !!(data && data.artist_challenge && data.artist_challenge.options);
    var hasMovie = !!(data && data.movie_challenge && data.movie_challenge.options);
    // #1180: in Title & Artist mode the "no bonus — nail the year" filler makes
    // no sense (there's no year; the T&I input card is the task). Hide it.
    var taMode = !!(data && data.title_artist_mode);
    filler.classList.toggle('hidden', hasArtist || hasMovie || taMode);
}

// Issue #827: Sudden Death — true when the current player ("me") is eliminated.
// Used to defensively block submissions and drive the eliminated view.
var meEliminated = false;

/**
 * Find the current player ("me") in a players array. Matches the existing
 * convention used everywhere in this file: player.name === state.playerName.
 * @param {Array} players - Array of player objects
 * @returns {Object|null} The current player object, or null
 */
function findMe(players) {
    if (!state.playerName || !players) return null;
    return players.find(function(p) {
        return p.name === state.playerName;
    }) || null;
}

/**
 * Issue #827: Sudden Death — apply elimination state for the current player.
 * When `sudden_death_mode` is on AND the current player is eliminated, hide the
 * normal play UI (slider, year display, bet, submit, challenges) and show the
 * #eliminated-view. Otherwise restore the normal UI and keep the view hidden.
 * Guarded so a non-Sudden-Death game is completely unaffected.
 * @param {Object} data - State data from server
 */
function applySuddenDeathState(data) {
    var eliminatedView = document.getElementById('eliminated-view');
    if (!eliminatedView) return;

    var suddenDeath = !!(data && data.sudden_death_mode);
    var me = findMe(data && data.players);
    var amOut = suddenDeath && !!(me && me.eliminated);

    meEliminated = amOut;

    // Elements that make up the normal active-play UI.
    var playEls = [
        document.getElementById('year-selector-container'),
        document.getElementById('year-display-arc'),
        document.getElementById('bet-toggle'),
        document.getElementById('submit-btn'),
        document.getElementById('title-artist-container'),
        document.getElementById('submitted-banner')
    ];

    if (amOut) {
        // Hide the active-play UI and show the blackout view.
        playEls.forEach(function(el) {
            if (el) el.classList.add('hidden');
        });
        eliminatedView.classList.remove('hidden');

        // Mirror the normal album art into the eliminated orb.
        var albumCover = document.getElementById('album-cover');
        var elimCover = document.getElementById('eliminated-album-cover');
        if (elimCover && albumCover && albumCover.src) {
            elimCover.src = albumCover.src;
        }

        // "Eliminated · Round N" — prefer the round they went out on.
        var subEl = document.getElementById('eliminated-sub');
        if (subEl) {
            var round = (me && me.eliminated_round != null)
                ? me.eliminated_round
                : (data && data.round) || '';
            subEl.textContent = utils.t('game.eliminatedRound', { round: round })
                || ('Eliminated · Round ' + round);
        }
    } else {
        // Restore the normal UI. Only un-hide the year-based play controls when
        // NOT in Title & Artist mode (renderTitleArtistInput owns that toggle);
        // submit-btn is always part of play. Defer to those owners by simply
        // removing the hidden class we added — renderTitleArtistInput runs after
        // this in updateGameView and re-hides the year UI when TA mode is on.
        playEls.forEach(function(el) {
            if (el) el.classList.remove('hidden');
        });
        eliminatedView.classList.add('hidden');

        // submitted-banner visibility is owned by handleSubmitAck/reset — it
        // should stay hidden unless this player has submitted. We removed the
        // hidden class above only to undo a prior elimination; re-hide it here
        // since restoring it is the tracker/ack's job, not ours.
        var banner = document.getElementById('submitted-banner');
        if (banner && !hasSubmitted) banner.classList.add('hidden');
    }
}

function renderSubmissionTracker(players) {
    var tracker = document.getElementById('submission-tracker');
    var container = document.getElementById('submitted-players');
    var countEl = document.getElementById('arc-submission-count');

    if (!tracker || !container) return;

    var playerList = players || [];
    // Issue #827: Sudden Death — eliminated players are out of the round and
    // must not count toward the "submitted / waiting" totals. activeList is the
    // set still in play; counts derive from it.
    var activeList = playerList.filter(function(p) {
        return !p.eliminated;
    });
    var submittedCount = activeList.filter(function(p) {
        return p.submitted;
    }).length;
    var totalCount = activeList.length;

    var allSubmitted = submittedCount === totalCount && totalCount > 0;
    tracker.classList.toggle('all-submitted', allSubmitted);

    // Arcade submission count text: "3 of 4 submitted" / "All in" when everyone's done.
    if (countEl) {
        if (totalCount === 0) {
            countEl.textContent = '';
        } else if (allSubmitted) {
            countEl.textContent = utils.t('game.allSubmitted') || 'All in';
        } else {
            countEl.textContent = utils.t('game.submittedCount', { count: submittedCount, total: totalCount })
                || (submittedCount + ' of ' + totalCount + ' submitted');
        }
    }

    // Update the arcade submitted banner copy (count of remaining players).
    var submittedBanner = document.getElementById('submitted-banner');
    var bannerText = document.getElementById('submitted-banner-text');
    if (submittedBanner && bannerText && !submittedBanner.classList.contains('hidden')) {
        var remaining = Math.max(0, totalCount - submittedCount);
        if (remaining === 0) {
            bannerText.textContent = utils.t('game.lockedInAllSubmitted') || 'Locked in · everyone submitted';
        } else {
            bannerText.textContent = utils.t('game.lockedInWaitingCount', { count: remaining })
                || ('Locked in · waiting for ' + remaining + ' more');
        }
    }

    container.innerHTML = playerList.map(function(player) {
        var initials = getInitials(player.name);
        var isCurrentPlayer = player.name === state.playerName;
        var isDisconnected = player.connected === false;
        var isEliminated = !!player.eliminated;  // Issue #827
        var classes = [
            'player-indicator',
            // Issue #827: eliminated chips never read as "submitted".
            (player.submitted && !isEliminated) ? 'is-submitted' : '',
            isCurrentPlayer ? 'is-current-player' : '',
            isDisconnected ? 'player-indicator--disconnected' : '',
            isEliminated ? 'is-eliminated' : ''
        ].filter(Boolean).join(' ');

        var badges = '';
        // Issue #827: eliminated players show only the "Out · R{round}" badge,
        // not steal/bet badges (they're no longer playing this round).
        if (isEliminated) {
            var round = (player.eliminated_round != null) ? player.eliminated_round : '';
            var outText = utils.t('game.outRound', { round: round }) || ('Out · R' + round);
            badges += '<span class="player-out-badge">' + escapeHtml(outText) + '</span>';
        } else {
            if (player.steal_used) {
                badges += '<span class="player-badge player-badge--steal">🥷</span>';
            }
            if (player.bet) {
                badges += '<span class="player-badge player-badge--bet">🎲</span>';
            }
        }

        // Issue #827: skull replaces the avatar initials for eliminated players.
        var avatarInner = isEliminated
            ? '<span class="eliminated-skull" aria-hidden="true">💀</span>'
            : '<span class="player-initials">' + escapeHtml(initials) + '</span>';

        return '<div class="' + classes + '">' +
            badges +
            '<div class="player-avatar">' +
                avatarInner +
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

// ============================================
// Year Selector & Submission (Story 4.3)
// ============================================

var hasSubmitted = false;
var betActive = false;
var hasStealAvailable = false;

// Title & Artist Mode state (#1180)
var titleArtistMode = false;
var taInputWired = false;

// #854: initYearSelector is called from player-core.js on every PLAYING-phase
// state update (once per round). Without this guard, every round stacks
// another pointerdown listener on each ±1/±5 button → step count grows with
// the round number (round 2 → +2, round 3 → +3, etc).
var yearSelectorInitialized = false;

/**
 * Initialize year selector interaction
 */
export function initYearSelector() {
    if (yearSelectorInitialized) return;  // #854
    var slider = document.getElementById('year-slider');
    var yearDisplay = document.getElementById('selected-year');

    if (!slider || !yearDisplay) return;

    yearSelectorInitialized = true;  // #854 — set only after DOM was found

    slider.addEventListener('input', function() {
        if (meEliminated) return;  // Issue #827: eliminated players can't change the year
        yearDisplay.textContent = this.value;
    });

    // ±1 / ±5 year-step buttons (Issue #662 — orig +/- · Issue #851 — fix double-fire + add ±5)
    function adjustYear(delta) {
        var newVal = parseInt(slider.value, 10) + delta;
        newVal = Math.max(parseInt(slider.min, 10), Math.min(parseInt(slider.max, 10), newVal));
        slider.value = newVal;
        yearDisplay.textContent = newVal;
    }

    /**
     * #851: single pointerdown = exactly one step. Long-press repeat only kicks
     * in after a 500ms hold (longer than a normal tap, so quick taps stay 1×).
     * No separate click handler — synthetic clicks on touch caused 2-4× fire
     * combined with the legacy 200ms-interval-on-pointerdown. Keyboard fallback
     * via keydown (Enter / Space).
     */
    function setupYearButton(btn, delta) {
        if (!btn) return;
        var intervalId = null;
        var longPressTimeoutId = null;

        btn.addEventListener('pointerdown', function(e) {
            if (hasSubmitted || meEliminated) return;  // Issue #827
            e.preventDefault();
            adjustYear(delta);
            longPressTimeoutId = setTimeout(function() {
                intervalId = setInterval(function() { adjustYear(delta); }, 150);
            }, 500);
        });

        function cancel() {
            if (longPressTimeoutId) { clearTimeout(longPressTimeoutId); longPressTimeoutId = null; }
            if (intervalId) { clearInterval(intervalId); intervalId = null; }
        }
        ['pointerup', 'pointerleave', 'pointercancel'].forEach(function(ev) {
            btn.addEventListener(ev, cancel);
        });

        // Keyboard fallback (Space / Enter when the button has focus)
        btn.addEventListener('keydown', function(e) {
            if (hasSubmitted || meEliminated) return;  // Issue #827
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                adjustYear(delta);
            }
        });
    }

    setupYearButton(document.getElementById('year-decrement'), -1);
    setupYearButton(document.getElementById('year-increment'), 1);
    setupYearButton(document.getElementById('year-decrement-5'), -5);
    setupYearButton(document.getElementById('year-increment-5'), 5);

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
        submitBtn.addEventListener('click', function() {
            if (titleArtistMode) {
                handleTitleArtistSubmit();
            } else {
                handleSubmitGuess();
            }
        });
    }

    if (!taInputWired) {
        var titleInput = document.getElementById('ta-title-input');
        var artistInput = document.getElementById('ta-artist-input');
        if (titleInput) {
            titleInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (artistInput) artistInput.focus();
                }
            });
        }
        if (artistInput) {
            artistInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    if (titleArtistMode) handleTitleArtistSubmit();
                }
            });
        }
        taInputWired = true;
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
    if (meEliminated) return;  // Issue #827: eliminated players can't submit

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
    var yearXxl = document.getElementById('year-display-arc');
    var submitBtn = document.getElementById('submit-btn');
    var betToggle = document.getElementById('bet-toggle');
    var submittedBanner = document.getElementById('submitted-banner');

    // Arcade locked state: slider + year turn green and freeze.
    if (yearSelector) {
        yearSelector.classList.add('is-submitted', 'slider-arcade--locked');
    }
    if (yearXxl) {
        yearXxl.classList.add('year-xxl--locked');
    }

    // Submit button stays visible but becomes "Waiting for others" with a pulse dot.
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('submit-arc--waiting');
        submitBtn.innerHTML = '<span>' + escapeHtml(utils.t('game.waitingForOthers') || 'Waiting for others') + '</span>'
            + '<span class="waiting-dot" aria-hidden="true"></span>';
    }

    // Bet toggle stays visible but disabled — can't change after submit.
    if (betToggle) {
        betToggle.disabled = true;
    }

    if (submittedBanner) {
        submittedBanner.classList.remove('hidden');
    }

    // Disable ±1 / ±5 buttons (Issues #662, #851)
    ['year-decrement', 'year-increment', 'year-decrement-5', 'year-increment-5'].forEach(function(id) {
        var b = document.getElementById(id);
        if (b) b.disabled = true;
    });
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
    var yearXxl = document.getElementById('year-display-arc');
    var submitBtn = document.getElementById('submit-btn');
    var slider = document.getElementById('year-slider');
    var betToggle = document.getElementById('bet-toggle');
    var submittedBanner = document.getElementById('submitted-banner');

    if (yearSelector) {
        yearSelector.classList.remove('is-submitted', 'slider-arcade--locked');
    }
    if (yearXxl) {
        yearXxl.classList.remove('year-xxl--locked');
    }

    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('hidden', 'is-loading', 'is-error', 'submit-arc--waiting');
        submitBtn.textContent = utils.t('game.submitGuess');
    }

    if (betToggle) {
        betToggle.disabled = false;
        betToggle.classList.remove('hidden', 'is-active');
    }

    if (submittedBanner) {
        submittedBanner.classList.add('hidden');
    }

    if (slider) {
        slider.value = 1990;
        var yearDisplay = document.getElementById('selected-year');
        if (yearDisplay) yearDisplay.textContent = '1990';
    }

    // Re-enable ±1 / ±5 buttons (Issues #662, #851)
    ['year-decrement', 'year-increment', 'year-decrement-5', 'year-increment-5'].forEach(function(id) {
        var b = document.getElementById(id);
        if (b) b.disabled = false;
    });

    hasStealAvailable = false;
    hideStealUI();

    resetArtistChallengeState();

    resetMovieChallengeState();

    resetTitleArtistState();
}

// ============================================
// Title & Artist Mode (#1180)
// ============================================

/**
 * Render the Title & Artist input section. When title_artist_mode is on we
 * REPLACE the year UI (slider, ±buttons, bet, year XXL) with two free-text
 * inputs and a single submit. The year-based artist/movie challenges never
 * run in this mode (backend won't send them), so nothing else changes.
 * @param {Object} data - State data from server (carries top-level title_artist_mode)
 */
export function renderTitleArtistInput(data) {
    var on = !!(data && data.title_artist_mode);
    titleArtistMode = on;

    var taContainer = document.getElementById('title-artist-container');
    var yearWrap = document.getElementById('year-selector-container');
    var yearXxl = document.getElementById('year-display-arc');
    var betToggle = document.getElementById('bet-toggle');

    if (taContainer) taContainer.classList.toggle('hidden', !on);

    // Hide the year-specific UI when TA mode is on.
    if (yearWrap) yearWrap.classList.toggle('hidden', on);
    if (yearXxl) yearXxl.classList.toggle('hidden', on);
    if (betToggle) betToggle.classList.toggle('hidden', on);  // no betting in v1 TA mode

    if (!on) return;

    // Relabel the submit button (still id=submit-btn, reused). Only while not
    // already submitted/locked, so we don't stomp the "Waiting for others" copy.
    var submitBtn = document.getElementById('submit-btn');
    if (submitBtn && !hasSubmitted) {
        submitBtn.textContent = utils.t('titleArtist.submitGuess') || 'Submit';
    }
}

/**
 * Send the combined title+artist guess. Single submit; an empty field is
 * allowed (scores 0 for that field server-side, status "skipped").
 */
export function handleTitleArtistSubmit() {
    if (hasSubmitted) return;
    if (meEliminated) return;  // Issue #827: eliminated players can't submit

    var titleInput = document.getElementById('ta-title-input');
    var artistInput = document.getElementById('ta-artist-input');
    var submitBtn = document.getElementById('submit-btn');
    if (!titleInput || !artistInput || !submitBtn) return;

    var title = (titleInput.value || '').trim();
    var artist = (artistInput.value || '').trim();

    submitBtn.disabled = true;
    submitBtn.classList.add('is-loading');

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify({
            type: 'title_artist_guess',
            title: title,
            artist: artist
        }));
    } else {
        showSubmitError(utils.t('errors.connectionLost'));
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
    }
}

/**
 * Handle the server's title_artist_guess_ack. Locks the inputs and surfaces
 * the per-field status. handleSubmitAck() (driven from the 'submit_ack' path)
 * handles the generic locked-button styling; this adds the per-field ack copy.
 * @param {Object} data - { title_status, artist_status }
 */
export function handleTitleArtistGuessAck(data) {
    handleSubmitAck();

    var titleInput = document.getElementById('ta-title-input');
    var artistInput = document.getElementById('ta-artist-input');
    if (titleInput) titleInput.disabled = true;
    if (artistInput) artistInput.disabled = true;

    var ackEl = document.getElementById('ta-input-ack');
    if (ackEl) {
        ackEl.textContent = utils.t('titleArtist.submitted') || 'Submitted — see how you did at the reveal!';
        ackEl.classList.remove('hidden');
    }
}

/**
 * Reset Title & Artist input state for a new round.
 */
function resetTitleArtistState() {
    var titleInput = document.getElementById('ta-title-input');
    var artistInput = document.getElementById('ta-artist-input');
    var ackEl = document.getElementById('ta-input-ack');

    if (titleInput) { titleInput.value = ''; titleInput.disabled = false; }
    if (artistInput) { artistInput.value = ''; artistInput.disabled = false; }
    if (ackEl) { ackEl.textContent = ''; ackEl.classList.add('hidden'); }
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
    syncArcChipRow();
}

/**
 * Hide all steal UI elements
 */
function hideStealUI() {
    var stealIndicator = document.getElementById('steal-indicator');
    var stealBtn = document.getElementById('steal-btn');

    if (stealIndicator) stealIndicator.classList.add('hidden');
    if (stealBtn) stealBtn.classList.add('hidden');
    syncArcChipRow();
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

var lastAdminActionAt = 0;
var ADMIN_ACTION_DEBOUNCE_MS = 500;

var songStopped = false;

var currentVolume = 0.5;

/**
 * Debounce admin actions to prevent rapid repeated clicks
 * @returns {boolean} True if action can proceed, false if debounced
 */
function debounceAdminAction() {
    // #880: timestamp-based, self-healing. The old boolean + setTimeout could
    // wedge `true` forever if the timer was lost (background-tab throttling,
    // an exception between set and schedule) — that silently killed every
    // admin button. A pure time comparison can't get stuck.
    var now = Date.now();
    if (now - lastAdminActionAt < ADMIN_ACTION_DEBOUNCE_MS) return false;
    lastAdminActionAt = now;
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
    var endBtn = document.getElementById('end-game-btn');

    // Always reset End button for PLAYING/REVEAL (both valid times to end).
    // Without this, the "ENDING..." label+disabled state from the previous
    // game persists into a rematch and the button stays unclickable (#???).
    if (endBtn && (phase === 'PLAYING' || phase === 'REVEAL')) {
        endBtn.disabled = false;
        endBtn.classList.remove('is-disabled');
        var endLabelEl = endBtn.querySelector('.control-label');
        if (endLabelEl) endLabelEl.textContent = utils.t('admin.end');
    }

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

    var stopBtn = document.getElementById('stop-song-btn');
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        // #880: the WebSocket can briefly be CONNECTING right after an
        // admin->player handoff or a tab-return reconnect. The old code
        // returned with only a console.warn — to the admin the button just
        // looked dead. Flash visible feedback on the label so they know the
        // click registered and to retry once reconnected.
        console.warn('[Beatify] Cannot stop song: WebSocket not connected');
        if (stopBtn) {
            var warnLabel = stopBtn.querySelector('.control-label');
            if (warnLabel) {
                var prevText = warnLabel.textContent;
                warnLabel.textContent = utils.t('errors.CONNECTION_LOST') || 'No connection';
                setTimeout(function() { warnLabel.textContent = prevText; }, 1800);
            }
        }
        return;
    }

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

        // Safety timeout: re-enable after 10s if server never responds (#534)
        setTimeout(function() {
            if (nextRoundPending) {
                resetNextRoundPending();
            }
        }, 10000);
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
