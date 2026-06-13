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

var VOTE_WINDOW_SECONDS = 30;  // mirrors TITLE_ARTIST_VOTE_WINDOW_SECONDS
var _taVoteCountdownTimer = null;

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

    // #1012 follow-up: idle-halt notice — the round ended with zero guesses,
    // playback has stopped, and the game is holding here until "Next round".
    var idleHalt = document.getElementById('reveal-idle-halt');
    if (idleHalt) idleHalt.classList.toggle('hidden', !data.idle_halt);

    // Auto-advance countdown — mirrors the admin sticky-Next countdown (#1048)
    // and the TV dashboard ring (#1185). Players had no way to see how long the
    // reveal stays up before the next round; now they do.
    updateRevealCountdown(data);

    // Issue #442: Show/hide Closest Wins badge during REVEAL
    var closestBadge = document.getElementById('closest-wins-badge');
    if (closestBadge) {
        if (data.closest_wins_mode) {
            closestBadge.classList.remove('hidden');
        } else {
            closestBadge.classList.add('hidden');
        }
    }

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
        // song.album_art may be a stale media-player-proxy URL (token-expired,
        // entity gone, MA-side hiccup). Fallback to the precached no-artwork
        // SVG so the cover slot always renders something — without onerror the
        // .song-strip-cover gradient bleeds through and looks intentional.
        albumCover.onerror = function() {
            albumCover.src = '/beatify/static/img/no-artwork.svg';
        };
        albumCover.src = song.album_art || '/beatify/static/img/no-artwork.svg';
    }

    // Spotlight Stage backdrop: blur the album art behind the top of the
    // reveal. song.album_art can be a stale/expired media-proxy URL, so probe
    // it with an off-DOM Image first — only swap in the art on a successful
    // load, otherwise keep the synthetic gradient fallback (the same reason
    // the cover <img> has an onerror handler above).
    var backdrop = document.getElementById('reveal-backdrop');
    if (backdrop) {
        var art = song.album_art;
        if (art) {
            var probe = new Image();
            probe.onload = function() {
                backdrop.style.backgroundImage = 'url("' + art + '")';
                backdrop.classList.remove('reveal-backdrop--synthetic');
            };
            probe.onerror = function() {
                backdrop.style.backgroundImage = '';
                backdrop.classList.add('reveal-backdrop--synthetic');
            };
            probe.src = art;
        } else {
            backdrop.style.backgroundImage = '';
            backdrop.classList.add('reveal-backdrop--synthetic');
        }
    }

    var correctYear = document.getElementById('correct-year');
    if (correctYear) {
        correctYear.textContent = song.year || '????';
    }

    var titleEl = document.getElementById('song-title');
    var artistEl = document.getElementById('song-artist');
    if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
    if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';

    // New: render the Duel (your guess × gap × correct year) via its own helper
    // below — needs currentPlayer, so we stash song.year and call after the
    // currentPlayer is resolved.

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

    // #1180: in Title & Artist mode there is no year, so the year duel /
    // emotion ("BINGO" + "You said × N years × Actually <year>") and the
    // year chip row don't apply — hide them and let the Title & Artist reveal
    // carry the round result. The mode-agnostic score row stays.
    var taMode = !!(data.title_artist_challenge && data.title_artist_challenge.correct_title);
    var duelEl = document.querySelector('#reveal-view .duel');
    if (duelEl) duelEl.classList.toggle('hidden', taMode);
    if (taMode) {
        var chipRowEl = document.getElementById('reveal-chip-row');
        if (chipRowEl) chipRowEl.classList.add('hidden');
    } else {
        showRevealEmotion(currentPlayer, song.year);
        // Round-reveal v2: duel + chips + score row replace the old personal result + all-guesses cards.
        renderDuel(currentPlayer, song.year);
        renderChipRow(currentPlayer, data);
    }
    renderScoreRow(currentPlayer);

    // Cache context for bottom-sheet renderers that run on demand.
    state.lastRevealContext = {
        player: currentPlayer,
        players: players,
        song: song,
        analytics: data.round_analytics || null,
        difficulty: data.song_difficulty || null,
        closestWinsMode: !!data.closest_wins_mode,
        revealStartedAt: data.reveal_started_at || Date.now(),
    };

    renderArtistReveal(data.artist_challenge || null, state.playerName);
    renderMovieReveal(data.movie_challenge || null, state.playerName);
    renderTitleArtistReveal(data.title_artist_challenge || null, currentPlayer);

    _resetReportBtn();

    // Story 14.5: Check for new record and trigger rainbow confetti (AC2)
    if (data.game_performance && data.game_performance.is_new_record) {
        triggerConfetti('record');
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
// Reveal auto-advance countdown (mirrors admin #1048 / dashboard #1185)
// ============================================

var _revealAdvanceTick = null;

/**
 * Stop and reset the reveal auto-advance countdown. Safe to call any time;
 * called from player-core on every phase that leaves REVEAL.
 */
export function stopRevealCountdown() {
    if (_revealAdvanceTick !== null) {
        clearInterval(_revealAdvanceTick);
        _revealAdvanceTick = null;
    }
    var chip = document.getElementById('player-reveal-countdown');
    if (chip) chip.classList.add('hidden');
}

/**
 * Drive the reveal auto-advance countdown ring on the player's phone.
 * Server sends reveal_auto_advance (seconds, 0 = off) and reveal_started_at
 * (ms epoch); remaining = max(0, started + duration*1000 - now). Hidden when
 * auto-advance is off OR the round is idle-halted (server holds REVEAL).
 */
export function updateRevealCountdown(data) {
    var chip = document.getElementById('player-reveal-countdown');
    var numEl = document.getElementById('player-reveal-countdown-num');
    var fgCircle = chip ? chip.querySelector('.reveal-advance-fg') : null;
    if (!chip || !numEl || !fgCircle) return;

    // Stop any existing tick before re-binding state (no stacking intervals).
    if (_revealAdvanceTick !== null) {
        clearInterval(_revealAdvanceTick);
        _revealAdvanceTick = null;
    }

    var duration = data.reveal_auto_advance || 0;
    var startedAt = data.reveal_started_at || 0;
    var idleHalt = !!data.idle_halt;

    if (duration <= 0 || !startedAt || idleHalt) {
        chip.classList.add('hidden');
        return;
    }

    chip.classList.remove('hidden');
    // SVG circle r=25 -> circumference 2*pi*r ~= 157.08
    var circumference = 157.08;
    fgCircle.style.strokeDasharray = circumference;

    function paint() {
        var remainingMs = Math.max(0, startedAt + duration * 1000 - Date.now());
        var remaining = Math.ceil(remainingMs / 1000);
        numEl.textContent = remaining;
        // Drained progress: ring is full at start, empties as time elapses.
        var pctRemaining = remainingMs / (duration * 1000);
        fgCircle.style.strokeDashoffset = String(circumference * (1 - pctRemaining));
        if (remainingMs <= 0 && _revealAdvanceTick !== null) {
            clearInterval(_revealAdvanceTick);
            _revealAdvanceTick = null;
        }
    }
    paint();
    _revealAdvanceTick = setInterval(paint, 500);
}

/**
 * Render per-player dot-axis (#1178): each player's guess is a colored dot on
 * a horizontal year-axis, with the correct year marked by a vertical cyan
 * line. Replaces the aggregated histogram on the player phone — same backend
 * data (all_guesses), denser per-player view.
 *
 * @param {Array} allGuesses - {name, guess, years_off, round_score}[]
 * @param {number} correctYear - The correct year for the cyan marker
 * @param {string} currentPlayerName - Mark "you" with an extra ring
 * @returns {string} HTML string
 */
function renderPlayerDotAxis(allGuesses, correctYear, currentPlayerName) {
    if (!allGuesses || allGuesses.length === 0) {
        return '<div class="histogram-empty">' + utils.t('analytics.noGuesses') + '</div>';
    }

    var guessYears = allGuesses.map(function(g) { return g.guess; });
    var minBound = Math.min.apply(null, guessYears.concat([correctYear]));
    var maxBound = Math.max.apply(null, guessYears.concat([correctYear]));
    var pad = Math.max(2, Math.floor((maxBound - minBound) * 0.1));
    var axisMin = minBound - pad;
    var axisMax = maxBound + pad;
    var axisRange = Math.max(1, axisMax - axisMin);

    function pct(year) { return ((year - axisMin) / axisRange) * 100; }

    // Cyan correct-year marker.
    var correctPct = pct(correctYear);
    var markerHtml =
        '<div class="dotaxis-marker" style="left:' + correctPct + '%">' +
        '<div class="dotaxis-marker-label">' + correctYear + '</div>' +
        '</div>';

    // 5 evenly spaced axis tick-labels.
    var ticksHtml = '';
    for (var t = 0; t <= 4; t++) {
        var yr = Math.round(axisMin + (axisRange * t / 4));
        var lp = (t * 25);
        ticksHtml +=
            '<div class="dotaxis-tick" style="left:' + lp + '%"></div>' +
            '<div class="dotaxis-tick-label" style="left:' + lp + '%">' + yr + '</div>';
    }

    // Player dots. Color is a deterministic hash of name → c1..c4.
    function colorClass(name) {
        var h = 0;
        for (var i = 0; i < name.length; i++) {
            h = (h * 31 + name.charCodeAt(i)) >>> 0;
        }
        return 'c' + ((h % 4) + 1);
    }

    var dotsHtml = '';
    for (var k = 0; k < allGuesses.length; k++) {
        var g = allGuesses[k];
        var p = pct(g.guess);
        var initial = (g.name || '?').charAt(0).toUpperCase();
        var cls = colorClass(g.name || '');
        var isMe = currentPlayerName && g.name === currentPlayerName;
        var meCls = isMe ? ' dotaxis-dot--me' : '';
        var glowCls = (g.years_off === 0) ? ' dotaxis-dot--correct' : '';
        var score = g.round_score || 0;
        var scoreCls = score > 0 ? 'dotaxis-score--pos' : 'dotaxis-score--zero';
        var scoreText = score > 0 ? '+' + score : '+0';

        dotsHtml +=
            '<div class="dotaxis-dot dotaxis-dot--' + cls + glowCls + meCls + '" ' +
                'style="left:' + p + '%" ' +
                'title="' + escapeHtml(g.name) + ' — ' + g.guess + ' (' + scoreText + ')">' +
            initial +
            '</div>' +
            '<div class="dotaxis-score ' + scoreCls + '" style="left:' + p + '%">' + scoreText + '</div>';
    }

    // Compact legend: name with color-dot, "(DU)" marker for current player.
    var legendItems = allGuesses.slice().sort(function(a, b) {
        return (a.years_off || 0) - (b.years_off || 0);
    });
    var medals = ['🏆', '🥈', '🥉'];
    var legendHtml = '';
    for (var m = 0; m < legendItems.length; m++) {
        var item = legendItems[m];
        var lcls = colorClass(item.name || '');
        var medal = m < 3 ? '<span class="dotaxis-legend-medal">' + medals[m] + '</span>' : '';
        var meMark = (currentPlayerName && item.name === currentPlayerName)
            ? ' <span class="dotaxis-legend-me">' + utils.t('analytics.youMarker') + '</span>' : '';
        legendHtml +=
            '<span class="dotaxis-legend-entry">' +
                medal +
                '<span class="dotaxis-legend-dot dotaxis-dot--' + lcls + '"></span>' +
                escapeHtml(item.name || '?') + meMark +
            '</span>';
    }

    return (
        '<div class="dotaxis-wrap">' +
            '<div class="dotaxis-axis">' +
                ticksHtml +
                '<div class="dotaxis-line"></div>' +
                markerHtml +
                dotsHtml +
            '</div>' +
        '</div>' +
        '<div class="dotaxis-legend">' + legendHtml + '</div>'
    );
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

    // Round-reveal v2: the emotion lives inside the duel (.duel-emotion).
    var isDuel = emotionEl.classList.contains('duel-emotion');
    var isCompact = emotionEl.classList.contains('reveal-emotion-inline') ||
                    document.querySelector('.reveal-container--compact');
    emotionEl.className = isDuel ? 'duel-emotion' : (isCompact ? 'reveal-emotion-inline' : 'reveal-emotion');
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

    // Duel design v2: just the main phrase (e.g. "SO CLOSE!", "WAY OFF!").
    // The gap count in the duel already communicates the "N years off" fact
    // that the old subtitle carried, so the subtitle is intentionally dropped.
    if (isDuel) {
        emotionEl.textContent = emotionText;
        emotionEl.classList.add('duel-emotion--' + emotionType);
    } else {
        var emotionHtml = '<span class="reveal-emotion-text">' + emotionText + '</span>';
        if (subtitle) {
            emotionHtml += '<div class="reveal-emotion-subtitle">' + subtitle + '</div>';
        }
        emotionEl.innerHTML = emotionHtml;
        emotionEl.classList.add('reveal-emotion--' + emotionType);
    }
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
        resultContent.innerHTML = '<div class="result-missed">' + utils.t('reveal.playerNotFound') + '</div>';
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
function renderPlayerResultCards(players, closestWinsMode) {
    var container = document.getElementById('reveal-results-cards');
    if (!container) return;

    if (!players || players.length === 0) {
        container.innerHTML = '';
        return;
    }

    // Issue #442: Determine closest player(s) for highlight
    var bestDiff = null;
    if (closestWinsMode) {
        players.forEach(function(p) {
            if (!p.missed_round && p.years_off != null) {
                if (bestDiff === null || p.years_off < bestDiff) {
                    bestDiff = p.years_off;
                }
            }
        });
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

        // Issue #442: Mark closest player(s) in Closest Wins mode
        var isClosest = closestWinsMode && !isMissed && bestDiff !== null && (player.years_off || 0) === bestDiff;
        var closestClass = isClosest ? ' is-closest-winner' : '';

        var guessDisplay = isMissed ? '—' : (player.guess || 'n/a');
        var yearsOffDisplay = isMissed ? utils.t('reveal.noGuessShort') :
                              yearsOff === 0 ? utils.t('reveal.exact') :
                              utils.t('reveal.shortOff', { years: yearsOff });

        var betIndicator = player.bet ? '<span class="card-bet">🎲</span>' : '';

        var closestBadge = isClosest ? '<span class="closest-winner-badge">🎯</span>' : '';

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

        html += '<div class="result-card ' + scoreClass + closestClass + (isCurrentPlayer ? ' is-current' : '') + '">' +
            '<div class="card-name">' + escapeHtml(player.name) + betIndicator + closestBadge + '</div>' +
            '<div class="card-guess">' + guessDisplay + '</div>' +
            '<div class="card-accuracy">' + yearsOffDisplay + '</div>' +
            stealIndicator +
            '<div class="card-score">+' + roundScore + artistBadge + '</div>' +
        '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
}

// ===========================================================================
// Round-reveal v2: Duel / Chips / Score row / Sheets (DESIGN.md Variant B)
// ===========================================================================

/**
 * Populate the duel — your guess × gap × correct year.
 * @param {Object|null} player - Current player data
 * @param {number|null} correctYear - Server-reported correct year
 */
function renderDuel(player, correctYear) {
    var yourEl = document.getElementById('duel-your-year');
    var gapCountEl = document.getElementById('duel-gap-count');
    var gapUnitEl = document.getElementById('duel-gap-unit');
    if (!yourEl || !gapCountEl || !gapUnitEl) return;

    if (!player || player.missed_round) {
        yourEl.textContent = utils.t('reveal.duel.noGuess') || '—';
        gapCountEl.textContent = '—';
        gapUnitEl.textContent = '';
        return;
    }

    var guess = player.guess;
    yourEl.textContent = (guess != null && guess !== '') ? guess : '—';

    var yearsOff = player.years_off != null ? player.years_off : 0;
    gapCountEl.textContent = String(yearsOff);
    gapUnitEl.textContent = yearsOff === 1
        ? (utils.t('reveal.duel.yearUnit') || 'year')
        : (utils.t('reveal.duel.yearsUnit') || 'years');

    // Color the gap by proximity. Matches the emotion color of the duel header.
    var gapEl = gapCountEl.closest('.duel-gap');
    if (gapEl) {
        gapEl.classList.remove('duel-gap--exact', 'duel-gap--close', 'duel-gap--wrong');
        if (yearsOff === 0) gapEl.classList.add('duel-gap--exact');
        else if (yearsOff <= 5) gapEl.classList.add('duel-gap--close');
        else gapEl.classList.add('duel-gap--wrong');
    }
}

/**
 * Render the conditional chip row (bet outcome, streak). Hidden when empty.
 */
function renderChipRow(player, data) {
    var row = document.getElementById('reveal-chip-row');
    if (!row) return;
    if (!player) { row.classList.add('hidden'); row.innerHTML = ''; return; }

    var chips = [];

    if (player.bet_outcome === 'won') {
        chips.push('<span class="chip chip--bet-won">🎲 ' + escapeHtml(utils.t('reveal.chip.betWon') || 'Bet won · ×2') + '</span>');
    } else if (player.bet_outcome === 'lost') {
        chips.push('<span class="chip chip--bet-lost">🎲 ' + escapeHtml(utils.t('reveal.chip.betLost') || 'Bet lost') + '</span>');
    }

    var streakBonus = player.streak_bonus || 0;
    if (streakBonus > 0 && player.streak) {
        var streakLabel = utils.t('reveal.chip.streakBonus', { count: player.streak, bonus: streakBonus })
            || (player.streak + '-streak · +' + streakBonus);
        chips.push('<span class="chip chip--streak">🔥 ' + escapeHtml(streakLabel) + '</span>');
    }

    if (chips.length === 0) {
        row.classList.add('hidden');
        row.innerHTML = '';
    } else {
        row.classList.remove('hidden');
        row.innerHTML = chips.join('');
    }
}

/**
 * Total round points = round_score + streak_bonus + artist_bonus
 * (bet multiplier is already folded into round_score on the server).
 */
function computeTotalPoints(player) {
    if (!player) return 0;
    var base = player.round_score || 0;
    var streak = player.streak_bonus || 0;
    var artist = player.artist_bonus || 0;
    var movie = player.movie_bonus || 0;
    var intro = player.intro_bonus || 0;
    return base + streak + artist + movie + intro;
}

/**
 * Populate the big score row: "You earned · 1 year off · +120".
 */
function renderScoreRow(player) {
    var ptsEl = document.getElementById('reveal-total-pts');
    var subEl = document.getElementById('score-row-subtitle');
    if (!ptsEl) return;

    var total = computeTotalPoints(player);
    ptsEl.textContent = (total >= 0 ? '+' : '') + total;

    if (subEl) {
        if (!player || player.missed_round) {
            subEl.textContent = utils.t('reveal.noSubmission') || 'No guess submitted';
        } else {
            var yo = player.years_off != null ? player.years_off : 0;
            var key = yo === 0 ? 'reveal.exact'
                    : yo === 1 ? 'reveal.yearOff'
                    : 'reveal.yearsOff';
            subEl.textContent = utils.t(key, { years: yo }) || (yo + ' years off');
        }
    }
}

// ---------- Points breakdown sheet ----------

/**
 * Populate the points-breakdown sheet based on the last-rendered player data.
 */
function renderPointsBreakdown() {
    var el = document.getElementById('points-breakdown-content');
    if (!el) return;
    var ctx = state.lastRevealContext;
    var player = ctx ? ctx.player : null;

    if (!player || player.missed_round) {
        el.innerHTML =
            '<div class="breakdown-empty">' +
                '<div class="breakdown-empty-icon" aria-hidden="true">⏰</div>' +
                '<div class="breakdown-empty-text">' +
                    escapeHtml(utils.t('reveal.breakdown.noSubmission') || utils.t('reveal.noSubmission') || 'No guess submitted') +
                '</div>' +
                '<div class="breakdown-total breakdown-total--zero">' +
                    '<span class="label">' + escapeHtml(utils.t('reveal.breakdown.total') || 'Total this round') + '</span>' +
                    '<span class="value">+0</span>' +
                '</div>' +
            '</div>';
        return;
    }

    var rows = [];
    var yearsOff = player.years_off != null ? player.years_off : 0;
    var base = player.base_score || 0;
    var roundScore = player.round_score || 0;
    var speedMultiplier = player.speed_multiplier || 1.0;
    // Backend computes round_score = int(base × speed) × bet_multiplier. The
    // pre-bet speed addon is what we want to display on the Speed bonus row —
    // otherwise the +addon line silently absorbs the ×2 bet multiplier and the
    // breakdown stops summing to total (e.g. base=5, speed=1.54, bet won → JS
    // showed Speed +9 + ×2 but total=14, not 18). Match Python int() with floor.
    var speedAddon = Math.floor(base * speedMultiplier) - base;

    rows.push({
        emoji: '🎯',
        label: (utils.t('reveal.breakdown.baseScore', { years: yearsOff }) || 'Base score'),
        value: String(base),
        kind: 'neutral'
    });

    if (speedMultiplier > 1.0 && speedAddon > 0) {
        rows.push({
            emoji: '⚡',
            label: (utils.t('reveal.breakdown.speedBonus') || 'Speed bonus') +
                   ' (' + speedMultiplier.toFixed(2) + '×)',
            value: '+' + speedAddon,
            kind: 'positive'
        });
    }

    if (player.streak_bonus && player.streak_bonus > 0) {
        rows.push({
            emoji: '🔥',
            label: utils.t('reveal.breakdown.streakBonus', { count: player.streak }) ||
                   (player.streak + '-streak bonus'),
            value: '+' + player.streak_bonus,
            kind: 'positive'
        });
    }

    if (player.artist_bonus && player.artist_bonus > 0) {
        rows.push({
            emoji: '🎤',
            label: utils.t('reveal.breakdown.artistBonus') || 'Artist challenge',
            value: '+' + player.artist_bonus,
            kind: 'positive'
        });
    }

    if (player.movie_bonus && player.movie_bonus > 0) {
        rows.push({
            emoji: '🎬',
            label: utils.t('reveal.breakdown.movieBonus') || 'Movie challenge',
            value: '+' + player.movie_bonus,
            kind: 'positive'
        });
    }

    if (player.intro_bonus && player.intro_bonus > 0) {
        rows.push({
            emoji: '⚡',
            label: utils.t('reveal.breakdown.introBonus') || 'Intro speed bonus',
            value: '+' + player.intro_bonus,
            kind: 'positive'
        });
    }

    if (player.bet_outcome === 'won') {
        rows.push({
            emoji: '🎲',
            label: utils.t('reveal.breakdown.betMultiplier') || 'Double or Nothing',
            value: '×2',
            kind: 'multiplier'
        });
    } else if (player.bet_outcome === 'lost') {
        rows.push({
            emoji: '🎲',
            label: utils.t('reveal.breakdown.betLost') || 'Bet lost',
            value: '×0',
            kind: 'multiplier'
        });
    }

    var total = computeTotalPoints(player);

    var listHtml = '<div class="breakdown-list">';
    rows.forEach(function(r) {
        listHtml += '<div class="breakdown-row">' +
            '<span class="label">' +
                '<span class="emoji" aria-hidden="true">' + r.emoji + '</span>' +
                '<span>' + escapeHtml(r.label) + '</span>' +
            '</span>' +
            '<span class="value value--' + r.kind + '">' + escapeHtml(r.value) + '</span>' +
        '</div>';
    });
    listHtml += '</div>';

    listHtml += '<div class="breakdown-total">' +
        '<span class="label">' + escapeHtml(utils.t('reveal.breakdown.total') || 'Total this round') + '</span>' +
        '<span class="value">' + (total >= 0 ? '+' : '') + total + '</span>' +
    '</div>';

    el.innerHTML = listHtml;
}

// ---------- Round stats sheet ----------

export function renderRoundStatsSheet() {
    var el = document.getElementById('round-stats-content');
    if (!el) return;
    var ctx = state.lastRevealContext;
    if (!ctx) { el.innerHTML = ''; return; }

    var analytics = ctx.analytics;
    var difficulty = ctx.difficulty;
    var song = ctx.song || {};
    var correctYear = song.year;
    var parts = [];

    // Difficulty banner (stars + "Only N% guess it right")
    if (difficulty) {
        var stars = '';
        var total = 5;
        for (var i = 0; i < total; i++) {
            stars += '<span class="' + (i < difficulty.stars ? 'star-filled' : 'star-empty') + '">★</span>';
        }
        var lbl = utils.t('difficulty.' + difficulty.label) || difficulty.label || '';
        var pct = difficulty.accuracy != null
            ? (utils.t('reveal.stats.onlyPercent', { percent: difficulty.accuracy })
                || 'Only ' + difficulty.accuracy + '% of all players guess it right.')
            : '';
        parts.push(
            '<div class="difficulty-visual">' +
                '<div class="left">' + escapeHtml(lbl) +
                    (pct ? '<div class="sub">' + escapeHtml(pct) + '</div>' : '') +
                '</div>' +
                '<div class="stars">' + stars + '</div>' +
            '</div>'
        );
    }

    // 2x2 stats grid
    if (analytics) {
        var cards = [];
        if (analytics.average_guess != null) {
            var avgDiff = correctYear ? Math.round(analytics.average_guess - correctYear) : null;
            var avgSub = avgDiff != null
                ? (avgDiff === 0 ? (utils.t('analytics.onTarget') || 'On target')
                    : (Math.abs(avgDiff) + ' ' + (utils.t('reveal.duel.yearsUnit') || 'years') + ' ' + (avgDiff > 0 ? 'late' : 'early')))
                : '';
            cards.push(
                '<div class="stats-card">' +
                    '<div class="lbl">' + escapeHtml(utils.t('reveal.stats.avgGuess') || 'Avg guess') + '</div>' +
                    '<div class="val cyan">' + Math.round(analytics.average_guess) + '</div>' +
                    (avgSub ? '<div class="sub">' + escapeHtml(avgSub) + '</div>' : '') +
                '</div>'
            );
        }

        // Closest guess — pull the first entry of all_guesses (sorted by years_off)
        if (analytics.all_guesses && analytics.all_guesses.length > 0) {
            var closest = analytics.all_guesses[0];
            var closestSub = closest.name + ' · ' +
                (closest.years_off === 0 ? (utils.t('reveal.exact') || 'Exact!')
                  : closest.years_off + ' ' + (closest.years_off === 1 ? (utils.t('reveal.duel.yearUnit') || 'year') : (utils.t('reveal.duel.yearsUnit') || 'years')) + ' off');
            cards.push(
                '<div class="stats-card">' +
                    '<div class="lbl">' + escapeHtml(utils.t('reveal.stats.closest') || 'Closest') + '</div>' +
                    '<div class="val success">' + escapeHtml(String(closest.guess)) + '</div>' +
                    '<div class="sub">' + escapeHtml(closestSub) + '</div>' +
                '</div>'
            );
        }

        // Fastest submit (from speed_champion)
        if (analytics.speed_champion && analytics.speed_champion.time != null) {
            cards.push(
                '<div class="stats-card">' +
                    '<div class="lbl">' + escapeHtml(utils.t('reveal.stats.fastest') || 'Fastest') + '</div>' +
                    '<div class="val">' + analytics.speed_champion.time + 's</div>' +
                    '<div class="sub">' + escapeHtml((analytics.speed_champion.names || []).join(', ')) + '</div>' +
                '</div>'
            );
        }

        // Played before (from song_difficulty.times_played)
        if (difficulty && difficulty.times_played != null) {
            var playedSub = utils.t('reveal.stats.playedBeforeSub') || 'across all Beatify games';
            cards.push(
                '<div class="stats-card">' +
                    '<div class="lbl">' + escapeHtml(utils.t('reveal.stats.playedBefore') || 'Played before') + '</div>' +
                    '<div class="val">' + difficulty.times_played + '×</div>' +
                    '<div class="sub">' + escapeHtml(playedSub) + '</div>' +
                '</div>'
            );
        }

        if (cards.length > 0) {
            parts.push('<div class="stats-grid">' + cards.join('') + '</div>');
        }
    }

    // #1178: per-player dot-axis — each player as a dot on a year-axis with
    // their score bubble. Lives here in the round-stats sheet (the live reveal-v2
    // analytics surface); it was first (mis)wired into renderRoundAnalytics(),
    // which the v3.2.0 Duel reveal redesign had already retired (#1184 regression,
    // since deleted).
    if (analytics && analytics.all_guesses && analytics.all_guesses.length > 0) {
        parts.push(
            '<div class="card-section">' +
                '<div class="section-header">' +
                    '<span class="icon" aria-hidden="true">🎯</span>' +
                    '<span>' + escapeHtml(utils.t('analytics.guessAxis') || 'Where everyone guessed') + '</span>' +
                '</div>' +
                renderPlayerDotAxis(analytics.all_guesses, correctYear, state.playerName) +
            '</div>'
        );
    }

    // Furthest off this round
    if (analytics && analytics.furthest_players && analytics.furthest_players.length > 0 && analytics.all_guesses && analytics.all_guesses.length > 0) {
        var furthest = analytics.all_guesses[analytics.all_guesses.length - 1];
        if (furthest && furthest.years_off > 0) {
            var furthestRows = analytics.furthest_players.map(function(n) {
                return '<div class="furthest-row">' +
                    '<span class="name">' + escapeHtml(n) + '</span>' +
                    '<span class="off">' + furthest.years_off + ' ' +
                        (furthest.years_off === 1 ? (utils.t('reveal.duel.yearUnit') || 'yr')
                            : (utils.t('reveal.duel.yearsUnit') || 'yrs')) +
                    ' off</span>' +
                '</div>';
            }).join('');
            parts.push(
                '<div class="card-section" style="margin-bottom:0">' +
                    '<div class="section-header">' +
                        '<span class="icon" aria-hidden="true">🙈</span>' +
                        '<span>' + escapeHtml(utils.t('reveal.stats.furthestOff') || 'Furthest off this round') + '</span>' +
                    '</div>' +
                    '<div class="furthest-list">' + furthestRows + '</div>' +
                '</div>'
            );
        }
    }

    if (parts.length === 0) {
        parts.push('<p class="stats-empty">' + escapeHtml(utils.t('reveal.stats.empty') || 'No stats for this round yet.') + '</p>');
    }

    el.innerHTML = parts.join('');
}

// ---------- Sheet open/close wiring ----------

function openSheet(id, populate) {
    var sheet = document.getElementById(id);
    if (!sheet) return;
    if (typeof populate === 'function') populate();
    sheet.classList.remove('hidden');
    // Trap focus lightly: move focus to the close button if present
    var closeBtn = sheet.querySelector('.sheet-close');
    if (closeBtn) closeBtn.focus();
}

function closeSheet(id) {
    var sheet = document.getElementById(id);
    if (!sheet) return;
    sheet.classList.add('hidden');
}

/**
 * Wire the two reveal-view bottom sheets (points breakdown + round stats).
 * Called once from player-core's initAll via setupRevealControls.
 */
export function setupRevealSheets() {
    var ptsBtn = document.getElementById('points-breakdown-btn');
    if (ptsBtn) {
        ptsBtn.addEventListener('click', function() {
            openSheet('points-breakdown-sheet', renderPointsBreakdown);
        });
    }
    var statsBtn = document.getElementById('round-stats-btn');
    if (statsBtn) {
        statsBtn.addEventListener('click', function() {
            openSheet('round-stats-sheet', renderRoundStatsSheet);
        });
    }

    // Close buttons + tap-outside (dim area)
    document.querySelectorAll('[data-sheet-close]').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            closeSheet(btn.getAttribute('data-sheet-close'));
            e.stopPropagation();
        });
    });
    document.querySelectorAll('.sheet-backdrop').forEach(function(backdrop) {
        var dim = backdrop.querySelector('.sheet-dim');
        if (dim) {
            dim.addEventListener('click', function() { closeSheet(backdrop.id); });
        }
    });

    // Escape-to-close
    document.addEventListener('keydown', function(e) {
        if (e.key !== 'Escape') return;
        ['points-breakdown-sheet', 'round-stats-sheet'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el && !el.classList.contains('hidden')) closeSheet(id);
        });
    });
}

// ============================================
// Report wrong data (Issue #911)
// ============================================

function _resetReportBtn() {
    var btn = document.getElementById('reveal-report-btn');
    if (!btn) return;
    btn.textContent = utils.t('reveal.reportBtn') || '🚩 Wrong year?';
    btn.disabled = false;
}

/**
 * Wire the "Report wrong year" button on the reveal screen (#911).
 * Called once from player-core's initAll.
 */
export function setupRevealReportBtn() {
    var btn = document.getElementById('reveal-report-btn');
    if (!btn) return;
    btn.addEventListener('click', function() {
        var ctx = state.lastRevealContext;
        if (!ctx || !ctx.song) return;
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;

        state.ws.send(JSON.stringify({
            type: 'report_data',
            artist: ctx.song.artist || '',
            title: ctx.song.title || '',
            year: ctx.song.year || null,
        }));

        btn.textContent = utils.t('reveal.reportBtnDone') || '✓ Reported — thanks!';
        btn.disabled = true;
    });
}

// ============================================
// Title & Artist Reveal + Voting (#1180)
// ============================================

/**
 * Build the status pill HTML for a per-field result.
 * @param {string} status - exact|fuzzy|near_miss|near_miss_accepted|skipped
 * @returns {string} HTML
 */
function _taStatusPill(status) {
    var cls = 'ta-pill ta-pill--' + (status || 'skipped').replace(/_/g, '-');
    var label;
    switch (status) {
        case 'exact': label = utils.t('titleArtist.statusExact') || 'Correct'; break;
        case 'fuzzy': label = utils.t('titleArtist.statusFuzzy') || 'Close enough'; break;
        case 'near_miss_accepted': label = utils.t('titleArtist.statusAccepted') || 'Accepted'; break;
        case 'near_miss': label = utils.t('titleArtist.statusNearMiss') || 'Near miss'; break;
        case 'wrong': label = utils.t('titleArtist.statusWrong') || 'Wrong'; break;
        default: label = utils.t('titleArtist.statusSkipped') || 'Skipped';
    }
    return '<span class="' + cls + '">' + escapeHtml(label) + '</span>';
}

/**
 * Classify the current player's own Title & Artist result into an emotional
 * verdict for the reveal banner (#1180). Honest about pending votes: while the
 * window is open and a field is still a near-miss, it shows "awaiting the
 * verdict" rather than calling a miss the room might still accept.
 * @param {Object|null} own - the player's own results entry
 * @param {boolean} votingOpen - whether the community vote is still open
 * @returns {{tier:string,text:string}|null}
 */
function _taOwnVerdict(own, votingOpen) {
    if (!own) return null;
    var GOT = { exact: 1, fuzzy: 1, near_miss_accepted: 1 };
    var ts = own.title_status;
    var as = own.artist_status;
    if (votingOpen && (ts === 'near_miss' || as === 'near_miss')) {
        return { tier: 'pending', text: utils.t('titleArtist.verdictPending') || 'Awaiting the room’s verdict…' };
    }
    var got = (GOT[ts] ? 1 : 0) + (GOT[as] ? 1 : 0);
    if (got === 2) return { tier: 'win', text: utils.t('titleArtist.verdictWin') || 'Nailed it!' };
    if (got === 1) return { tier: 'partial', text: utils.t('titleArtist.verdictPartial') || 'Got one!' };
    return { tier: 'miss', text: utils.t('titleArtist.verdictMiss') || 'Not this time' };
}

/**
 * Render one resolved near-miss verdict card for the post-voting "decided"
 * view: avatar, who · field, the guess, the final 👍/👎 tally, and a verdict
 * badge (green ✓ +points when accepted, red ✗ when rejected). (#1180, #1243)
 * @param {Object} o - a near_miss_outcomes entry
 * @param {function} fieldLabel - maps "title"/"artist" to a localized label
 */
function _taOutcomeCard(o, fieldLabel) {
    var accepted = !!o.accepted;
    var initial = ((o.player || '?').trim().charAt(0) || '?').toUpperCase();
    var verdict = accepted
        ? '✓ +' + (o.points || 0)
        : '✗';
    return '<div class="ta-outcome-card ta-outcome-card--' + (accepted ? 'accepted' : 'rejected') + '">' +
        '<span class="ta-outcome-avatar" aria-hidden="true">' + escapeHtml(initial) + '</span>' +
        '<div class="ta-outcome-main">' +
            '<div class="ta-outcome-who">' + escapeHtml(o.player) +
                ' <span class="ta-outcome-field">· ' + escapeHtml(fieldLabel(o.field)) + '</span></div>' +
            '<div class="ta-outcome-guess">“' + escapeHtml(o.guess || '—') + '”</div>' +
            '<div class="ta-outcome-tally">👍 ' + (o.votes_yes || 0) + ' · 👎 ' + (o.votes_no || 0) + '</div>' +
        '</div>' +
        '<span class="ta-outcome-verdict ta-outcome-verdict--' + (accepted ? 'accepted' : 'rejected') + '">' +
            verdict + '</span>' +
    '</div>';
}

/**
 * Render the Title & Artist reveal: the truth, the current player's own
 * per-field result, the 👍/👎 voting cards for OTHER players' near-misses
 * (a player never votes on their own), and — for the host — Accept/Reject
 * override buttons. Drives a display-only 30s countdown off voting_open.
 *
 * @param {Object|null} ta - data.title_artist_challenge (REVEAL shape) or null
 * @param {Object|null} currentPlayer - resolved current player object
 */
export function renderTitleArtistReveal(ta, currentPlayer) {
    var section = document.getElementById('ta-reveal-section');
    if (!section) return;

    if (!ta || !ta.correct_title) {
        section.classList.add('hidden');
        _stopTaVoteCountdown();
        return;
    }
    section.classList.remove('hidden');

    // Remember this player's own 👍/👎 per near-miss so the "voted" state
    // survives the innerHTML rebuild on every state broadcast. The server only
    // sends aggregate tallies, not who voted — but our own vote is known
    // locally. Reset the memory whenever a new song is revealed.
    if (state._taRevealTruth !== ta.correct_title) {
        state._taRevealTruth = ta.correct_title;
        state.taMyVotes = {};
    }
    state.taMyVotes = state.taMyVotes || {};

    // 1) Truth
    var truthEl = document.getElementById('ta-reveal-truth');
    if (truthEl) {
        truthEl.innerHTML =
            '<span class="ta-truth-title">' + escapeHtml(ta.correct_title) + '</span>' +
            '<span class="ta-truth-sep" aria-hidden="true">—</span>' +
            '<span class="ta-truth-artist">' + escapeHtml(ta.correct_artist || '') + '</span>';
    }

    // 2) Own per-field result
    var ownEl = document.getElementById('ta-reveal-own');
    var results = ta.results || [];
    var own = null;
    for (var i = 0; i < results.length; i++) {
        if (results[i].player === state.playerName) { own = results[i]; break; }
    }
    if (ownEl) {
        if (own) {
            var verdict = _taOwnVerdict(own, !!ta.voting_open);
            var verdictHtml = verdict
                ? '<div class="ta-verdict ta-verdict--' + verdict.tier + '">' +
                    escapeHtml(verdict.text) + '</div>'
                : '';
            ownEl.innerHTML =
                verdictHtml +
                '<div class="ta-own-row">' +
                    '<span class="ta-own-label">' + escapeHtml(utils.t('titleArtist.yourTitle') || 'Your title') + '</span>' +
                    '<span class="ta-own-guess">' + escapeHtml(own.title || '—') + '</span>' +
                    _taStatusPill(own.title_status) +
                '</div>' +
                '<div class="ta-own-row">' +
                    '<span class="ta-own-label">' + escapeHtml(utils.t('titleArtist.yourArtist') || 'Your artist') + '</span>' +
                    '<span class="ta-own-guess">' + escapeHtml(own.artist || '—') + '</span>' +
                    _taStatusPill(own.artist_status) +
                '</div>';
        } else {
            ownEl.innerHTML = '<div class="ta-own-row ta-own-row--none">' +
                escapeHtml(utils.t('titleArtist.noGuess') || 'No guess this round') + '</div>';
        }
    }

    // 3) Voting cards (while open) or resolved outcomes (once decided)
    var votingWrap = document.getElementById('ta-voting');
    var cardsEl = document.getElementById('ta-voting-cards');
    var titleEl = document.getElementById('ta-voting-title');
    var countdownEl = document.getElementById('ta-voting-countdown');
    var nearMisses = ta.near_misses || [];
    var outcomes = ta.near_miss_outcomes || [];
    var votingOpen = !!ta.voting_open;
    var isHost = !!(currentPlayer && currentPlayer.is_admin);

    if (!votingWrap || !cardsEl) { _stopTaVoteCountdown(); return; }

    var fieldLabel = function(field) {
        return field === 'artist'
            ? (utils.t('titleArtist.artistLabel') || 'Artist')
            : (utils.t('titleArtist.titleLabel') || 'Song title');
    };

    // Voting closed + verdicts available → the resolution moment: each near-miss
    // shown as accepted ✓ +points / rejected ✗, with its final tally.
    if (!votingOpen && outcomes.length > 0) {
        _stopTaVoteCountdown();
        votingWrap.classList.remove('hidden');
        if (titleEl) {
            titleEl.textContent = utils.t('titleArtist.closeCallsDecided') || 'Close calls — decided';
        }
        if (countdownEl) { countdownEl.textContent = ''; countdownEl.classList.add('hidden'); }
        cardsEl.innerHTML = outcomes.map(function(o) { return _taOutcomeCard(o, fieldLabel); }).join('');
        return;
    }

    if (nearMisses.length === 0) {
        votingWrap.classList.add('hidden');
        cardsEl.innerHTML = '';
        _stopTaVoteCountdown();
        return;
    }

    votingWrap.classList.remove('hidden');
    // Reset header to the live-vote state (a prior round may have set "decided").
    if (titleEl) {
        titleEl.textContent = utils.t('titleArtist.voteHeader') || 'Close calls — vote 👍/👎';
    }
    if (countdownEl) { countdownEl.classList.remove('hidden'); }

    var html = '';
    nearMisses.forEach(function(nm) {
        // The owner of the near-miss never votes on it.
        var isOwn = nm.player === state.playerName;
        var yes = nm.votes_yes || 0;
        var no = nm.votes_no || 0;
        // Crowd Court tally bars: split the track by share of votes cast.
        var total = yes + no;
        var yesPct = total ? Math.round((yes / total) * 100) : 0;
        var noPct = total ? 100 - yesPct : 0;
        var initial = ((nm.player || '?').trim().charAt(0) || '?').toUpperCase();

        html += '<div class="ta-vote-card' + (isOwn ? ' ta-vote-card--mine' : '') +
            '" data-nearmiss-id="' + escapeHtml(nm.id) + '">' +
            '<div class="ta-vote-card-head">' +
                '<span class="ta-vote-avatar" aria-hidden="true">' + escapeHtml(initial) + '</span>' +
                '<span class="ta-vote-who">' + escapeHtml(nm.player) + '</span>' +
                '<span class="ta-vote-field">' + escapeHtml(fieldLabel(nm.field)) + '</span>' +
            '</div>' +
            '<div class="ta-vote-guess">“' + escapeHtml(nm.guess || '—') + '”</div>' +
            '<div class="ta-vote-tally">' +
                '<div class="ta-tally-row">' +
                    '<span class="ta-tally-yes">👍 ' + yes + '</span>' +
                    '<span class="ta-tally-track"><span class="ta-tally-fill ta-tally-fill--yes" style="width:' + yesPct + '%"></span></span>' +
                '</div>' +
                '<div class="ta-tally-row">' +
                    '<span class="ta-tally-no">👎 ' + no + '</span>' +
                    '<span class="ta-tally-track"><span class="ta-tally-fill ta-tally-fill--no" style="width:' + noPct + '%"></span></span>' +
                '</div>' +
            '</div>';

        if (isOwn) {
            html += '<div class="ta-vote-own-note">' +
                escapeHtml(utils.t('titleArtist.yourCloseCall') || 'Your close call — others decide') + '</div>';
        } else if (votingOpen) {
            // Restore this player's choice across re-renders: chosen button
            // stays lit, the other dims, and a caption confirms (re-voting is
            // allowed, so both buttons remain tappable).
            var myVote = state.taMyVotes[nm.id];
            var hasVoted = (myVote === true || myVote === false);
            html += '<div class="ta-vote-actions' + (hasVoted ? ' ta-vote-actions--voted' : '') + '">' +
                '<button type="button" class="ta-vote-btn ta-vote-btn--yes' + (myVote === true ? ' is-chosen' : '') + '" ' +
                    'data-nearmiss-id="' + escapeHtml(nm.id) + '" data-accept="1">👍</button>' +
                '<button type="button" class="ta-vote-btn ta-vote-btn--no' + (myVote === false ? ' is-chosen' : '') + '" ' +
                    'data-nearmiss-id="' + escapeHtml(nm.id) + '" data-accept="0">👎</button>' +
            '</div>';
            if (hasVoted) {
                html += '<div class="ta-voted-caption">' +
                    escapeHtml(utils.t('titleArtist.youVoted') || 'You voted') + ' ' +
                    (myVote ? '👍' : '👎') + ' · ' +
                    escapeHtml(utils.t('titleArtist.tapToChange') || 'tap to change') + '</div>';
            }
        }

        // Host override row (always shown to host while voting is open).
        if (isHost && votingOpen) {
            html += '<div class="ta-override-actions">' +
                '<span class="ta-override-label">' + escapeHtml(utils.t('titleArtist.hostOverride') || 'Host decides') + '</span>' +
                '<button type="button" class="ta-override-btn ta-override-btn--accept" ' +
                    'data-nearmiss-id="' + escapeHtml(nm.id) + '" data-accept="1" ' +
                    'data-i18n="titleArtist.accept">Accept</button>' +
                '<button type="button" class="ta-override-btn ta-override-btn--reject" ' +
                    'data-nearmiss-id="' + escapeHtml(nm.id) + '" data-accept="0" ' +
                    'data-i18n="titleArtist.reject">Reject</button>' +
            '</div>';
        }

        html += '</div>';
    });
    cardsEl.innerHTML = html;

    // 4) Countdown — ticks from the server's authoritative vote_seconds_remaining.
    if (votingOpen) {
        _startTaVoteCountdown(ta);
    } else {
        _stopTaVoteCountdown();
        var cd = document.getElementById('ta-voting-countdown');
        if (cd) {
            cd.textContent = utils.t('titleArtist.voteClosed') || 'Voting closed';
            cd.removeAttribute('aria-label');
            cd.classList.add('ta-voting-countdown--closed');
        }
    }
}

/**
 * Start the voting countdown from the server's authoritative
 * ``vote_seconds_remaining`` (re-synced on every broadcast), ticking down
 * locally between broadcasts. Anchoring to a server-computed remaining instead
 * of comparing a server epoch to the client clock avoids clock-skew drift.
 * Falls back to VOTE_WINDOW_SECONDS only if the field is absent.
 * @param {Object} ta - title_artist_challenge dict
 */
function _startTaVoteCountdown(ta) {
    _stopTaVoteCountdown();
    var cd = document.getElementById('ta-voting-countdown');
    if (!cd) return;

    var serverRemaining = (ta && typeof ta.vote_seconds_remaining === 'number')
        ? ta.vote_seconds_remaining
        : VOTE_WINDOW_SECONDS;
    // Anchor to the client's own clock from the moment we received the server's
    // remaining — purely relative, so no cross-machine epoch comparison.
    var endAt = Date.now() + serverRemaining * 1000;

    function paint() {
        var remaining = Math.max(0, Math.ceil((endAt - Date.now()) / 1000));
        // Crowd Court ring: bare number inside the circle, with a conic arc that
        // drains as the window closes. aria-label keeps the full phrase for SR.
        cd.textContent = String(remaining);
        cd.setAttribute('aria-label', utils.t('titleArtist.voteCountdown', { seconds: remaining })
            || (remaining + 's'));
        cd.style.setProperty('--ta-vote-progress',
            (remaining / VOTE_WINDOW_SECONDS * 360) + 'deg');
        cd.classList.remove('ta-voting-countdown--closed');
        if (remaining <= 0) {
            _stopTaVoteCountdown();
        }
    }
    paint();
    _taVoteCountdownTimer = setInterval(paint, 500);
}

function _stopTaVoteCountdown() {
    if (_taVoteCountdownTimer) {
        clearInterval(_taVoteCountdownTimer);
        _taVoteCountdownTimer = null;
    }
}

/**
 * Wire vote and host-override clicks via event delegation on #ta-voting-cards.
 * Called once from player-core's initAll. Buttons re-render from each state
 * broadcast, so delegation survives the innerHTML rebuilds.
 */
export function setupTitleArtistVoting() {
    var cardsEl = document.getElementById('ta-voting-cards');
    if (!cardsEl) return;

    cardsEl.addEventListener('click', function(e) {
        var voteBtn = e.target.closest('.ta-vote-btn');
        var overrideBtn = e.target.closest('.ta-override-btn');

        if (voteBtn) {
            var voteId = voteBtn.getAttribute('data-nearmiss-id');
            var voteAccept = voteBtn.getAttribute('data-accept') === '1';
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                state.ws.send(JSON.stringify({
                    type: 'title_artist_vote',
                    nearmiss_id: voteId,
                    accept: voteAccept
                }));
            }
            // Remember the choice so it persists through the next re-render.
            state.taMyVotes = state.taMyVotes || {};
            state.taMyVotes[voteId] = voteAccept;
            // Optimistic feedback: light the chosen button + dim the other now;
            // tally and caption fill in on the next broadcast.
            var card = voteBtn.closest('.ta-vote-card');
            if (card) {
                var actions = card.querySelector('.ta-vote-actions');
                if (actions) actions.classList.add('ta-vote-actions--voted');
                card.querySelectorAll('.ta-vote-btn').forEach(function(b) {
                    b.classList.remove('is-chosen');
                });
                voteBtn.classList.add('is-chosen');
            }
            return;
        }

        if (overrideBtn) {
            var ovId = overrideBtn.getAttribute('data-nearmiss-id');
            var ovAccept = overrideBtn.getAttribute('data-accept') === '1';
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                state.ws.send(JSON.stringify({
                    type: 'title_artist_override',
                    nearmiss_id: ovId,
                    accept: ovAccept
                }));
            }
            var ovCard = overrideBtn.closest('.ta-vote-card');
            if (ovCard) {
                ovCard.querySelectorAll('.ta-override-btn').forEach(function(b) {
                    b.classList.remove('is-chosen');
                });
                overrideBtn.classList.add('is-chosen');
            }
        }
    });
}
