/**
 * Beatify Player - Game / Artist Challenge (Story 20.5)
 * Extracted from player-game.js (#1279 step 6/6). Self-contained: module-level
 * state (artistChallengeComplete, pendingArtistGuess, winningArtist,
 * ARTIST_DEBOUNCE_MS, lastArtistGuessTime) is local to this cluster.
 */

import { state } from '../player-utils.js';

var utils = window.BeatifyUtils || {};

// Artist Challenge state (Story 20.5)
var artistChallengeComplete = false;
var pendingArtistGuess = null;
var winningArtist = null;
var ARTIST_DEBOUNCE_MS = 300;
var lastArtistGuessTime = 0;

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
export function resetArtistChallengeState() {
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
