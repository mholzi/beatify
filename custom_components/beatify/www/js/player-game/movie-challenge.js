/**
 * Beatify Player - Game / Movie Challenge (Issue #28)
 * Extracted from player-game.js (#1279 step 6/6). Self-contained: module-level
 * state (movieChallengeComplete, pendingMovieGuess, MOVIE_DEBOUNCE_MS,
 * lastMovieGuessTime) is local to this cluster.
 */

import { state } from '../player-utils.js';

var utils = window.BeatifyUtils || {};

// Movie Challenge state (Issue #28)
var movieChallengeComplete = false;
var pendingMovieGuess = null;
var MOVIE_DEBOUNCE_MS = 500;
var lastMovieGuessTime = 0;

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
export function resetMovieChallengeState() {
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
