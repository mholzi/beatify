/**
 * Beatify Player - Reveal Module
 * Reveal phase: animations, round analytics display, reactions
 */

import {
    state, escapeHtml,
    prefersReducedMotion, animateValue, animateScoreChange, showPointsPopup,
    previousState, isPreviousStateInitialized, isStreakMilestone,
    AnimationUtils,
    triggerConfetti, stopConfetti
} from './player-utils.js';

import { updateLeaderboard, renderArtistReveal, renderMovieReveal } from './player-game.js';

var utils = window.BeatifyUtils || {};

// ============================================
// Reveal View (Story 4.6)
// ============================================

/**
 * Update reveal view with round results
 * @param {Object} data - State data from server
 */
export function updateRevealView(data) {
    var song = data.song || {};
    var players = data.players || [];

    var roundEl = document.getElementById('reveal-round');
    var totalEl = document.getElementById('reveal-total');
    if (roundEl) roundEl.textContent = data.round || 1;
    if (totalEl) totalEl.textContent = data.total_rounds || 10;

    // Issue #23: Show/hide intro round badge during REVEAL
    var introBadge = document.getElementById('intro-badge');
    if (introBadge) {
        if (data.is_intro_round) {
            introBadge.classList.remove('hidden');
            introBadge.classList.add('intro-badge--stopped');
            var badgeText = introBadge.querySelector('[data-i18n]');
            if (badgeText) {
                badgeText.setAttribute('data-i18n', 'game.introStopped');
                badgeText.textContent = utils.t('game.introStopped') || 'Intro complete!';
            }
        } else {
            introBadge.classList.add('hidden');
        }
    }

    var albumCover = document.getElementById('reveal-album-cover');
    if (albumCover) {
        albumCover.src = song.album_art || '/beatify/static/img/no-artwork.svg';
    }

    var correctYear = document.getElementById('correct-year');
    if (correctYear) {
        correctYear.textContent = song.year || '????';
    }

    var titleEl = document.getElementById('song-title');
    var artistEl = document.getElementById('song-artist');
    if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
    if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';

    // Update fun fact and rich song info (Story 14.3, 16.1, 16.3)
    var funFactContainer = document.getElementById('fun-fact-container');
    var funFactText = document.getElementById('fun-fact');
    var funFactHeader = funFactContainer ? funFactContainer.querySelector('.fun-fact-header') : null;

    var localizedFunFact = utils.getLocalizedSongField(song, 'fun_fact');

    if (funFactText) {
        funFactText.textContent = localizedFunFact || '';
    }

    if (funFactHeader) {
        funFactHeader.style.display = localizedFunFact ? 'flex' : 'none';
    }

    renderRichSongInfo(song);

    renderSongDifficulty(data.song_difficulty);

    if (funFactContainer) {
        var richInfo = document.getElementById('song-rich-info');
        var hasRichInfo = richInfo && richInfo.innerHTML.trim() !== '';
        var hasFunFact = localizedFunFact && localizedFunFact.trim() !== '';
        funFactContainer.classList.toggle('hidden', !hasFunFact && !hasRichInfo);
    }

    var currentPlayer = null;
    for (var i = 0; i < players.length; i++) {
        if (players[i].name === state.playerName) {
            currentPlayer = players[i];
            break;
        }
    }

    showRevealEmotion(currentPlayer, song.year);
    renderPersonalResult(currentPlayer, song.year);

    if (data.artist_challenge) {
        renderArtistReveal(data.artist_challenge, state.playerName);
    }

    if (data.movie_challenge) {
        renderMovieReveal(data.movie_challenge, state.playerName);
    }

    // Story 14.5: Check for new record and trigger rainbow confetti (AC2)
    if (data.game_performance && data.game_performance.is_new_record) {
        triggerConfetti('record');
    }

    renderPlayerResultCards(players);

    if (data.round_analytics) {
        renderRoundAnalytics(data.round_analytics, song.year);
    }

    if (data.leaderboard) {
        updateLeaderboard(data, 'reveal-leaderboard-list', true);
    }

    // Show admin controls if admin
    var adminControls = document.getElementById('reveal-admin-controls');
    var nextRoundBtn = document.getElementById('next-round-btn');
    if (adminControls && currentPlayer && currentPlayer.is_admin) {
        adminControls.classList.remove('hidden');

        if (nextRoundBtn) {
            if (data.last_round) {
                nextRoundBtn.textContent = utils.t('leaderboard.finalResults');
                nextRoundBtn.classList.add('is-final');
            } else {
                nextRoundBtn.textContent = utils.t('admin.nextRound');
                nextRoundBtn.classList.remove('is-final');
            }
            nextRoundBtn.disabled = false;
        }
    } else if (adminControls) {
        adminControls.classList.add('hidden');
    }
}

// ============================================
// Round Analytics (Story 13.3)
// ============================================

/**
 * Render round analytics section (Story 13.3)
 * @param {Object} analytics - Round analytics data from server
 * @param {number} correctYear - The correct year for comparison
 */
function renderRoundAnalytics(analytics, correctYear) {
    var section = document.getElementById('round-analytics');
    var container = document.getElementById('round-analytics-content');
    if (!section || !container || !analytics) {
        if (section) section.classList.add('hidden');
        return;
    }

    if (analytics.total_submitted === 0) {
        container.innerHTML = '<div class="analytics-empty">' + utils.t('analytics.noSubmissions') + '</div>';
        section.classList.remove('hidden');
        return;
    }

    var avgComparison = '';
    if (analytics.average_guess !== null && correctYear) {
        var diff = Math.round(analytics.average_guess - correctYear);
        if (diff === 0) {
            avgComparison = utils.t('analytics.onTarget');
        } else if (diff > 0) {
            avgComparison = utils.t('analytics.yearsLate', { years: diff });
        } else {
            avgComparison = utils.t('analytics.yearsEarly', { years: Math.abs(diff) });
        }
    }

    var histogramHtml = renderHistogram(analytics.all_guesses, correctYear);

    var achievementsHtml = '';

    if (analytics.exact_match_players && analytics.exact_match_players.length > 0) {
        achievementsHtml += '<div class="achievement-item">' +
            '<span class="achievement-emoji">&#127919;</span>' +
            '<span class="achievement-label">' + utils.t('analytics.exactMatches') + ':</span>' +
            '<span class="achievement-names">' + analytics.exact_match_players.map(escapeHtml).join(', ') + '</span>' +
            '</div>';
    }

    if (analytics.speed_champion && analytics.speed_champion.names) {
        var names = analytics.speed_champion.names.map(escapeHtml).join(', ');
        achievementsHtml += '<div class="achievement-item">' +
            '<span class="achievement-emoji">&#9889;</span>' +
            '<span class="achievement-label">' + utils.t('analytics.speedChampion') + ':</span>' +
            '<span class="achievement-names">' + names + '</span>' +
            '<span class="achievement-value">(' + analytics.speed_champion.time + 's)</span>' +
            '</div>';
    }

    if (analytics.furthest_players && analytics.furthest_players.length > 0 && analytics.all_guesses && analytics.all_guesses.length > 0) {
        var furthestOff = analytics.all_guesses[analytics.all_guesses.length - 1].years_off;
        if (furthestOff > 0) {
            achievementsHtml += '<div class="achievement-item">' +
                '<span class="achievement-emoji">&#128517;</span>' +
                '<span class="achievement-label">' + utils.t('analytics.furthestGuess') + ':</span>' +
                '<span class="achievement-names">' + analytics.furthest_players.map(escapeHtml).join(', ') + '</span>' +
                '<span class="achievement-value">(' + furthestOff + ' years)</span>' +
                '</div>';
        }
    }

    var avgDisplay = analytics.average_guess !== null ? Math.round(analytics.average_guess) : '?';
    container.innerHTML =
        '<div class="analytics-stats-row">' +
        '<div class="stat-primary">' +
        '<span class="stat-label">' + utils.t('analytics.averageGuess') + '</span>' +
        '<span class="stat-value">' + avgDisplay + '</span>' +
        '</div>' +
        '<div class="stat-secondary">' +
        '<span class="stat-value">' + analytics.accuracy_percentage + '%</span>' +
        '<span class="stat-label">' + utils.t('analytics.accuracy', { percent: '' }).replace('%', '') + '</span>' +
        '</div>' +
        '</div>' +
        '<div class="stat-comparison-line">' + avgComparison + '</div>' +
        '<div class="analytics-histogram">' +
        '<h4 class="histogram-title">' + utils.t('analytics.histogram') + '</h4>' +
        histogramHtml +
        '</div>' +
        (achievementsHtml ? '<div class="analytics-achievements">' + achievementsHtml + '</div>' : '');

    section.classList.remove('hidden');
}

/**
 * Render histogram with 7 dynamic year bins based on actual guesses
 * @param {Array} allGuesses - Array of {name, guess, years_off} sorted by years_off
 * @param {number} correctYear - The correct year for highlighting
 * @returns {string} HTML string for histogram
 */
function renderHistogram(allGuesses, correctYear) {
    var NUM_BINS = 7;

    if (!allGuesses || allGuesses.length === 0) {
        return '<div class="histogram-empty">' + utils.t('analytics.noGuesses') + '</div>';
    }

    var guesses = allGuesses.map(function(g) { return g.guess; });
    var minGuess = Math.min.apply(null, guesses);
    var maxGuess = Math.max.apply(null, guesses);
    var range = maxGuess - minGuess;

    var yearsPerBin = Math.max(1, Math.ceil(range / NUM_BINS));

    var totalYears = yearsPerBin * NUM_BINS;
    var extraYears = totalYears - range - 1;
    var startYear = minGuess - Math.floor(extraYears / 2);

    var bins = [];
    for (var i = 0; i < NUM_BINS; i++) {
        var binStart = startYear + (i * yearsPerBin);
        var binEnd = binStart + yearsPerBin - 1;
        bins.push({
            start: binStart,
            end: binEnd,
            count: 0,
            containsCorrect: correctYear >= binStart && correctYear <= binEnd
        });
    }

    for (var j = 0; j < guesses.length; j++) {
        var guess = guesses[j];
        for (var k = 0; k < bins.length; k++) {
            if (guess >= bins[k].start && guess <= bins[k].end) {
                bins[k].count++;
                break;
            }
        }
    }

    var maxCount = 1;
    for (var m = 0; m < bins.length; m++) {
        if (bins[m].count > maxCount) maxCount = bins[m].count;
    }

    var barsHtml = '';
    for (var n = 0; n < bins.length; n++) {
        var bin = bins[n];
        var heightPercent = (bin.count / maxCount) * 100;
        var delay = n * 0.05;

        var barClass = 'histogram-bar' + (bin.containsCorrect ? ' is-correct' : '');
        var barHeight = bin.count > 0 ? Math.max(heightPercent, 10) : 0;
        var countHtml = bin.count > 0 ? '<span class="bar-count">' + bin.count + '</span>' : '';

        var label = yearsPerBin === 1 ? String(bin.start) : bin.start + '-' + String(bin.end).slice(-2);

        barsHtml += '<div class="histogram-bar-wrapper" style="animation-delay: ' + delay + 's">' +
            '<div class="' + barClass + '" style="height: ' + barHeight + '%">' +
            countHtml +
            '</div>' +
            '<span class="histogram-label">' + label + '</span>' +
            '</div>';
    }

    return '<div class="histogram-bars">' + barsHtml + '</div>';
}

// ============================================
// Song Difficulty (Story 15.1)
// ============================================

/**
 * Render song difficulty rating (Story 15.1)
 * @param {Object|null} difficulty - Difficulty data with stars, label, accuracy, times_played
 */
function renderSongDifficulty(difficulty) {
    var el = document.getElementById('song-difficulty');
    if (!el) return;

    if (!difficulty) {
        el.classList.add('hidden');
        return;
    }

    var stars = '';
    for (var i = 0; i < difficulty.stars; i++) {
        stars += '<span class="star">&#9733;</span>';
    }

    el.innerHTML =
        '<div class="difficulty-stars difficulty-' + difficulty.stars + '">' + stars + '</div>' +
        '<span class="difficulty-label">' + utils.t('difficulty.' + difficulty.label) + '</span>' +
        '<span class="difficulty-accuracy">' + difficulty.accuracy + '% ' + utils.t('difficulty.accuracy') + '</span>';

    el.classList.remove('hidden');
}

// ============================================
// Rich Song Info (Story 14.3)
// ============================================

/**
 * Render rich song info (chart position, certifications, awards)
 * @param {Object} song - Song data with optional chart_info, certifications, awards
 */
function renderRichSongInfo(song) {
    var container = document.getElementById('song-rich-info');
    if (!container) return;

    var badges = [];

    var chartBadges = renderChartBadges(song.chart_info || {});
    if (chartBadges.length > 0) badges = badges.concat(chartBadges);

    var certBadges = renderCertificationBadges(song.certifications || []);
    if (certBadges.length > 0) badges = badges.concat(certBadges);

    var localizedAwards = utils.getLocalizedSongField(song, 'awards') || [];
    var awardBadges = renderAwardBadges(localizedAwards);
    if (awardBadges.length > 0) badges = badges.concat(awardBadges);

    if (badges.length > 0) {
        container.innerHTML = '<div class="song-badges-row">' + badges.join('') + '</div>';
    } else {
        container.innerHTML = '';
    }
}

/**
 * Render chart info as badges
 * @param {Object} chartInfo - Chart info data
 * @returns {Array} Array of badge HTML strings
 */
function renderChartBadges(chartInfo) {
    if (!chartInfo) return [];

    var badges = [];

    if (chartInfo.billboard_peak && chartInfo.billboard_peak > 0) {
        var weeksText = chartInfo.weeks_on_chart
            ? ' <span class="chart-weeks">· ' + chartInfo.weeks_on_chart + ' ' + utils.t('reveal.weeksShort') + '</span>'
            : '';
        badges.push(
            '<span class="song-badge song-badge--chart">' +
            '<span class="song-badge-icon">📊</span>' +
            '#' + chartInfo.billboard_peak + ' ' + utils.t('reveal.chartBillboard') + weeksText +
            '</span>'
        );
    }

    if (chartInfo.german_peak && chartInfo.german_peak > 0 && !chartInfo.billboard_peak) {
        badges.push(
            '<span class="song-badge song-badge--chart">' +
            '<span class="song-badge-icon">📊</span>' +
            '#' + chartInfo.german_peak + ' ' + utils.t('reveal.chartGerman') +
            '</span>'
        );
    }

    if (chartInfo.uk_peak && chartInfo.uk_peak > 0 && !chartInfo.billboard_peak) {
        badges.push(
            '<span class="song-badge song-badge--chart">' +
            '<span class="song-badge-icon">📊</span>' +
            '#' + chartInfo.uk_peak + ' ' + utils.t('reveal.chartUK') +
            '</span>'
        );
    }

    return badges;
}

/**
 * Render certifications as badges
 * @param {Array} certifications - Array of certification strings
 * @returns {Array} Array of badge HTML strings
 */
function renderCertificationBadges(certifications) {
    if (!certifications || certifications.length === 0) return [];

    var badges = [];
    for (var i = 0; i < certifications.length; i++) {
        var cert = certifications[i];
        var badgeClass = getCertificationBadgeClass(cert);
        var icon = getCertificationIcon(cert);
        badges.push(
            '<span class="song-badge ' + badgeClass + '">' +
            '<span class="song-badge-icon">' + icon + '</span>' +
            escapeHtml(cert) +
            '</span>'
        );
    }
    return badges;
}

/**
 * Get CSS class for certification type
 */
function getCertificationBadgeClass(cert) {
    var certLower = cert.toLowerCase();
    if (certLower.indexOf('diamond') !== -1) return 'song-badge--diamond';
    if (certLower.indexOf('platinum') !== -1) return 'song-badge--platinum';
    if (certLower.indexOf('gold') !== -1) return 'song-badge--gold';
    return 'song-badge--platinum';
}

/**
 * Get icon for certification type
 */
function getCertificationIcon(cert) {
    var certLower = cert.toLowerCase();
    if (certLower.indexOf('diamond') !== -1) return '💎';
    if (certLower.indexOf('platinum') !== -1) return '💿';
    if (certLower.indexOf('gold') !== -1) return '🥇';
    return '💿';
}

/**
 * Render awards as badges (max 3)
 * @param {Array} awards - Array of award strings
 * @returns {Array} Array of badge HTML strings
 */
function renderAwardBadges(awards) {
    if (!awards || awards.length === 0) return [];

    var badges = [];
    var displayAwards = awards.slice(0, 3);

    for (var i = 0; i < displayAwards.length; i++) {
        var award = displayAwards[i];
        var badgeClass = getAwardBadgeClass(award);
        var icon = getAwardIcon(award);
        badges.push(
            '<span class="song-badge ' + badgeClass + '">' +
            '<span class="song-badge-icon">' + icon + '</span>' +
            escapeHtml(award) +
            '</span>'
        );
    }

    if (awards.length > 3) {
        badges.push('<span class="song-badges-more">+' + (awards.length - 3) + ' more</span>');
    }

    return badges;
}

/**
 * Get CSS class for award type
 */
function getAwardBadgeClass(award) {
    var awardLower = award.toLowerCase();
    if (awardLower.indexOf('grammy') !== -1) return 'song-badge--grammy';
    if (awardLower.indexOf('eurovision') !== -1) return 'song-badge--eurovision';
    if (awardLower.indexOf('oscar') !== -1 || awardLower.indexOf('academy award') !== -1) return 'song-badge--oscar';
    if (awardLower.indexOf('hall of fame') !== -1) return 'song-badge--halloffame';
    return 'song-badge--award';
}

/**
 * Get icon for award type
 */
function getAwardIcon(award) {
    var awardLower = award.toLowerCase();
    if (awardLower.indexOf('eurovision') !== -1) return '🎤';
    if (awardLower.indexOf('grammy') !== -1) return '🏆';
    if (awardLower.indexOf('hall of fame') !== -1) return '⭐';
    return '🏆';
}

// ============================================
// Emotion Display (Story 9.4)
// ============================================

/**
 * Show celebration-first emotion before data (Story 9.4)
 * @param {Object} player - Current player data
 * @param {number} correctYear - The correct year
 */
function showRevealEmotion(player, correctYear) {
    var emotionEl = document.getElementById('reveal-emotion');
    var personalResult = document.getElementById('personal-result');
    if (!emotionEl) return;

    var isCompact = emotionEl.classList.contains('reveal-emotion-inline') ||
                    document.querySelector('.reveal-container--compact');
    emotionEl.className = isCompact ? 'reveal-emotion-inline' : 'reveal-emotion';
    emotionEl.innerHTML = '';
    emotionEl.classList.add('hidden');

    if (personalResult) {
        personalResult.classList.remove('is-delayed');
    }

    stopConfetti();

    var emotions = utils.t('reveal.emotions');

    function randomFrom(arr) {
        return arr[Math.floor(Math.random() * arr.length)];
    }

    function getOffByText(years) {
        if (years === 1) {
            return utils.t('reveal.offByYear');
        }
        return utils.t('reveal.offByYears', { years: years });
    }

    var emotionType = 'missed';
    var emotionText = randomFrom(emotions.missed);
    var subtitle = randomFrom(emotions.missedSub);

    if (player && !player.missed_round) {
        var yearsOff = player.years_off || 0;

        if (yearsOff === 0) {
            emotionType = 'exact';
            emotionText = randomFrom(emotions.exact);
            subtitle = randomFrom(emotions.exactSub);
        } else if (yearsOff <= 2) {
            emotionType = 'close';
            emotionText = randomFrom(emotions.close);
            subtitle = randomFrom(emotions.closeSub) + ' ' + getOffByText(yearsOff);
        } else if (yearsOff <= 5) {
            emotionType = 'close';
            emotionText = randomFrom(emotions.close);
            subtitle = getOffByText(yearsOff);
        } else {
            emotionType = 'wrong';
            emotionText = randomFrom(emotions.wrong);
            subtitle = randomFrom(emotions.wrongSub) + ' ' + getOffByText(yearsOff);
        }
    } else if (player && player.missed_round) {
        emotionType = 'missed';
        emotionText = randomFrom(emotions.missed);
        subtitle = randomFrom(emotions.missedSub);
    }

    var emotionHtml = '<span class="reveal-emotion-text">' + emotionText + '</span>';
    if (subtitle) {
        emotionHtml += '<div class="reveal-emotion-subtitle">' + subtitle + '</div>';
    }
    emotionEl.innerHTML = emotionHtml;

    emotionEl.classList.add('reveal-emotion--' + emotionType);
    emotionEl.classList.remove('hidden');

    if (emotionType === 'exact') {
        triggerConfetti();
    }

    if (personalResult && emotionType !== 'missed') {
        personalResult.classList.add('is-delayed');
    }
}

// ============================================
// Personal Result (Story 4.6)
// ============================================

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
        var missedHtml =
            '<div class="result-missed-container">' +
                '<div class="result-missed-icon">⏰</div>' +
                '<div class="result-missed-text">' + utils.t('reveal.noSubmission') + '</div>' +
            '</div>';

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
    var yearsOffText = yearsOff === 0 ? utils.t('reveal.exact') :
                       yearsOff === 1 ? utils.t('reveal.yearOff', { years: 1 }) :
                       utils.t('reveal.yearsOff', { years: yearsOff });

    var resultClass = yearsOff === 0 ? 'is-exact' :
                      yearsOff <= 3 ? 'is-close' : 'is-far';

    var speedMultiplier = player.speed_multiplier || 1.0;
    var baseScore = player.base_score || 0;
    var hasSpeedBonus = speedMultiplier > 1.0;

    var streakBonus = player.streak_bonus || 0;

    var artistBonus = player.artist_bonus || 0;

    var scoreBreakdown = '';
    if (hasSpeedBonus && baseScore > 0) {
        scoreBreakdown =
            '<div class="result-row">' +
                '<span class="result-label">' + utils.t('reveal.baseScore') + '</span>' +
                '<span class="result-value">' + baseScore + ' pts</span>' +
            '</div>' +
            '<div class="result-row">' +
                '<span class="result-label">' + utils.t('reveal.speedBonus') + '</span>' +
                '<span class="result-value is-bonus">' + speedMultiplier.toFixed(2) + 'x</span>' +
            '</div>';
    }

    var betOutcomeHtml = '';
    if (player.bet_outcome === 'won') {
        betOutcomeHtml =
            '<div class="result-row bet-won-row">' +
                '<span class="result-label">🎲 ' + utils.t('reveal.betWon').replace('! 2x points', '') + '</span>' +
                '<span class="result-value is-bet-won">2x</span>' +
            '</div>';
    } else if (player.bet_outcome === 'lost') {
        betOutcomeHtml =
            '<div class="result-row bet-lost-row">' +
                '<span class="result-label">🎲 ' + utils.t('reveal.betLost') + '</span>' +
                '<span class="result-value is-bet-lost">-</span>' +
            '</div>';
    }

    var streakBonusHtml = '';
    if (streakBonus > 0) {
        streakBonusHtml =
            '<div class="result-row streak-bonus-row">' +
                '<span class="result-label">' + player.streak + '-streak bonus!</span>' +
                '<span class="result-value is-streak">+' + streakBonus + ' pts</span>' +
            '</div>';
    }

    var artistBonusHtml = '';
    if (artistBonus > 0) {
        artistBonusHtml =
            '<div class="result-row artist-bonus-row">' +
                '<span class="result-label">🎤 ' + (utils.t('artistChallenge.artistBonus') || 'Artist Bonus') + '</span>' +
                '<span class="result-value">+' + artistBonus + ' pts</span>' +
            '</div>';
    }

    var totalScore = player.round_score + streakBonus + artistBonus;
    var hasBonuses = streakBonus > 0 || artistBonus > 0;

    var isBigScore = player.round_score >= 20;
    var prevPlayer = previousState.players[player.name];
    var prevScore = prevPlayer ? prevPlayer.score : (player.score - totalScore);
    var prevStreak = prevPlayer ? prevPlayer.streak : 0;
    var streakMilestone = isStreakMilestone(prevStreak, player.streak || 0);

    resultContent.innerHTML =
        '<div class="result-row">' +
            '<span class="result-label">' + utils.t('reveal.yourGuess') + '</span>' +
            '<span class="result-value">' + (player.guess || 'n/a') + '</span>' +
        '</div>' +
        '<div class="result-row">' +
            '<span class="result-label">' + utils.t('reveal.correctYear') + '</span>' +
            '<span class="result-value">' + correctYear + '</span>' +
        '</div>' +
        '<div class="result-row">' +
            '<span class="result-label">' + utils.t('reveal.accuracy') + '</span>' +
            '<span class="result-value ' + resultClass + '">' + yearsOffText + '</span>' +
        '</div>' +
        scoreBreakdown +
        betOutcomeHtml +
        '<div class="result-score" id="personal-result-score">+<span class="score-value">0</span> pts</div>' +
        streakBonusHtml +
        artistBonusHtml +
        (hasBonuses ? '<div class="result-total">' + utils.t('reveal.total') + ': +<span class="total-value">0</span> pts</div>' : '');

    var scoreValueEl = resultContent.querySelector('.score-value');
    if (scoreValueEl) {
        animateScoreChange(scoreValueEl, 0, player.round_score, {
            betWon: player.bet_outcome === 'won',
            betLost: player.bet_outcome === 'lost',
            streakMilestone: streakMilestone,
            isBigScore: isBigScore
        });

        if (player.bet_outcome === 'won' && player.round_score > 0) {
            setTimeout(function() {
                var scoreEl = document.getElementById('personal-result-score');
                if (scoreEl) {
                    showPointsPopup(scoreEl, player.round_score, { isBetWin: true });
                }
            }, 200);
        }
    }

    var totalValueEl = resultContent.querySelector('.total-value');
    if (totalValueEl && hasBonuses) {
        setTimeout(function() {
            animateValue(totalValueEl, 0, totalScore, 600);
        }, 300);

        if (streakMilestone) {
            setTimeout(function() {
                var totalEl = resultContent.querySelector('.result-total');
                if (totalEl) {
                    var milestoneBonus = {3: 20, 5: 50, 10: 100}[streakMilestone] || 0;
                    showPointsPopup(totalEl, milestoneBonus, {
                        isStreak: true,
                        text: '+' + milestoneBonus + ' ' + streakMilestone + '-Streak!'
                    });
                }
            }, 500);
        }
    }
}

// ============================================
// Player Result Cards (Story 9.10)
// ============================================

/**
 * Render player result cards on reveal (Story 9.10)
 * @param {Array} players - All players from state
 */
function renderPlayerResultCards(players) {
    var container = document.getElementById('reveal-results-cards');
    if (!container) return;

    if (!players || players.length === 0) {
        container.innerHTML = '';
        return;
    }

    var sorted = players.slice().sort(function(a, b) {
        return (b.round_score || 0) - (a.round_score || 0);
    });

    var html = '<div class="results-cards-scroll">';

    sorted.forEach(function(player) {
        var isCurrentPlayer = player.name === state.playerName;
        var isMissed = player.missed_round === true;
        var yearsOff = player.years_off || 0;
        var roundScore = player.round_score || 0;

        var scoreClass = isMissed ? 'is-score-zero' :
                         roundScore >= 10 ? 'is-score-high' :
                         roundScore >= 1 ? 'is-score-medium' : 'is-score-zero';

        var guessDisplay = isMissed ? '—' : (player.guess || 'n/a');
        var yearsOffDisplay = isMissed ? utils.t('reveal.noGuessShort') :
                              yearsOff === 0 ? utils.t('reveal.exact') :
                              utils.t('reveal.shortOff', { years: yearsOff });

        var betIndicator = player.bet ? '<span class="card-bet">🎲</span>' : '';

        var artistBadge = '';
        if (player.artist_bonus && player.artist_bonus > 0) {
            artistBadge = '<span class="player-card-artist-badge">🎤 +' + player.artist_bonus + '</span>';
        }

        var stealIndicator = '';
        if (player.stole_from) {
            stealIndicator = '<div class="steal-badge"><span class="steal-badge-icon">🥷</span>' +
                utils.t('steal.stolenFrom', { name: escapeHtml(player.stole_from) }) + '</div>';
        } else if (player.was_stolen_by && player.was_stolen_by.length > 0) {
            var stealerNames = player.was_stolen_by.map(escapeHtml).join(', ');
            stealIndicator = '<div class="steal-badge steal-badge-victim"><span class="steal-badge-icon">🎯</span>' +
                utils.t('steal.stolenBy', { name: stealerNames }) + '</div>';
        }

        html += '<div class="result-card ' + scoreClass + (isCurrentPlayer ? ' is-current' : '') + '">' +
            '<div class="card-name">' + escapeHtml(player.name) + betIndicator + '</div>' +
            '<div class="card-guess">' + guessDisplay + '</div>' +
            '<div class="card-accuracy">' + yearsOffDisplay + '</div>' +
            stealIndicator +
            '<div class="card-score">+' + roundScore + artistBadge + '</div>' +
        '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
}
