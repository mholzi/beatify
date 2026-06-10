/**
 * Beatify Admin — pure spectator-view render helpers (#1279 Schritt 4/6).
 *
 * Step 4 begins the View-Section split. The fully self-contained, data-in /
 * DOM-out render helpers of the admin **playing/reveal spectator screens** are
 * the only part of admin.js that lifts out without touching the densely-shared
 * setup state (selectedPlaylists / selectedMediaPlayer / selectedProvider / the
 * bonus flags) — see the PR body for why the four setup-sections themselves
 * (media-players, music-service, playlists, game-settings) are deferred to a
 * post-step-5 follow-up rather than forced here without runtime coverage.
 *
 * Every function here takes all of its inputs as parameters and writes only to
 * the DOM by element id — no module-level mutable state, no admin-private
 * closures, no cross-references between them. That makes them genuinely pure
 * and unit-testable (see __tests__/admin-render-helpers.test.js).
 *
 * Shared dependencies (`BeatifyUtils.escapeHtml`, `BeatifyI18n.t`) are read off
 * `window`/`globalThis` at call time exactly as the rest of the admin code
 * does. `escapeHtml()` below resolves the live `window.BeatifyUtils.escapeHtml`
 * (the same one admin.js's `utils` alias points at) with a defensive identity
 * fallback so a missing util never throws during render.
 *
 * admin.js imports these and keeps thin `window.X = X` compat shims for the two
 * that were implicitly global before (`renderAdminLeaderboard`,
 * `renderAdminResultCards`) — see the shim block in admin.js.
 */

// Resolve escapeHtml the way admin.js's `utils` alias does (window.BeatifyUtils),
// with an identity fallback so render never throws if the util is missing.
function escapeHtml(value) {
    const g = (typeof window !== 'undefined' ? window : globalThis);
    const u = g && g.BeatifyUtils;
    if (u && typeof u.escapeHtml === 'function') return u.escapeHtml(value);
    return value == null ? '' : String(value);
}

// Resolve BeatifyI18n.t with a fallback that returns the key (callers always
// supply their own `|| 'literal'` fallback after the call, matching admin.js).
function t(key, params) {
    const g = (typeof window !== 'undefined' ? window : globalThis);
    const i18n = g && g.BeatifyI18n;
    if (i18n && typeof i18n.t === 'function') return i18n.t(key, params);
    return key;
}

/**
 * Render the submitted-player dot row on the admin PLAYING screen.
 * @param {Array<{name?:string, submitted?:boolean, connected?:boolean, steal_used?:boolean, bet?:boolean}>} players
 */
export function renderAdminSubmissionDots(players) {
    var container = document.getElementById('admin-submitted-players');
    if (!container || !players) return;

    container.innerHTML = players.map(function(p) {
        var initials = (p.name || '?').split(/\s+/).map(function(w) { return w[0]; }).join('').substring(0, 2).toUpperCase();
        var classes = [
            'player-indicator',
            p.submitted ? 'is-submitted' : '',
            p.connected === false ? 'player-indicator--disconnected' : ''
        ].filter(Boolean).join(' ');
        var badges = '';
        if (p.steal_used) badges += '<span class="player-badge player-badge--steal">🥷</span>';
        if (p.bet) badges += '<span class="player-badge player-badge--bet">🎲</span>';
        return '<div class="' + classes + '">' + badges +
            '<div class="player-avatar"><span class="player-initials">' + escapeHtml(initials) + '</span></div>' +
            '<span class="player-name">' + escapeHtml(p.name) + '</span></div>';
    }).join('');
}

/**
 * Render an admin leaderboard list into one or both spectator containers.
 * @param {Array<{rank:number, name:string, score:number, connected?:boolean, streak?:number, rank_change?:number}>} leaderboard
 * @param {string} [containerId] - render into this id only; else both playing+reveal lists
 */
export function renderAdminLeaderboard(leaderboard, containerId) {
    var targets = containerId ? [containerId] : ['admin-playing-leaderboard-list', 'admin-reveal-leaderboard'];
    if (!leaderboard) return;

    var html = '';
    leaderboard.forEach(function(entry) {
        var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
        var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
        var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';
        var streakIndicator = '';
        if (entry.streak >= 2) {
            var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
            streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
        }
        var changeIndicator = '';
        if (entry.rank_change > 0) changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
        else if (entry.rank_change < 0) changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';

        html += '<div class="leaderboard-entry ' + rankClass + ' ' + disconnectedClass + '">' +
            '<span class="entry-rank">#' + entry.rank + '</span>' +
            '<span class="entry-name">' + escapeHtml(entry.name) + awayBadge + '</span>' +
            '<span class="entry-meta">' + streakIndicator + changeIndicator + '</span>' +
            '<span class="entry-score">' + entry.score + '</span>' +
        '</div>';
    });

    targets.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.innerHTML = html;
    });

    // Update summary badges
    if (leaderboard.length > 0) {
        ['admin-playing-leaderboard-summary', 'admin-reveal-leaderboard-summary'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.textContent = leaderboard[0].name + ' — ' + leaderboard[0].score;
        });
    }
}

/**
 * Render player-style result cards for reveal (matches player-reveal.js renderPlayerResultCards).
 */
export function renderAdminResultCards(players, closestWinsMode, correctYear) {
    var container = document.getElementById('admin-reveal-guesses');
    if (!container) return;
    if (!players || players.length === 0) { container.innerHTML = ''; return; }

    var bestDiff = null;
    if (closestWinsMode) {
        players.forEach(function(p) {
            if (!p.missed_round && p.years_off != null) {
                if (bestDiff === null || p.years_off < bestDiff) bestDiff = p.years_off;
            }
        });
    }

    var sorted = players.slice().sort(function(a, b) { return (b.round_score || 0) - (a.round_score || 0); });
    var html = '<div class="results-cards-scroll">';

    sorted.forEach(function(p) {
        var isMissed = p.missed_round === true;
        var yearsOff = p.years_off || 0;
        var roundScore = p.round_score || 0;
        var scoreClass = isMissed ? 'is-score-zero' : roundScore >= 10 ? 'is-score-high' : roundScore >= 1 ? 'is-score-medium' : 'is-score-zero';
        var isClosest = closestWinsMode && !isMissed && bestDiff !== null && yearsOff === bestDiff;
        var closestClass = isClosest ? ' is-closest-winner' : '';
        var guessDisplay = isMissed ? '—' : (p.guess || 'n/a');
        var yearsOffDisplay = isMissed ? t('reveal.noGuessShort') || 'Missed' :
            yearsOff === 0 ? t('reveal.exact') || 'Exact!' :
            (t('reveal.shortOff', { years: yearsOff }) || yearsOff + ' off');
        var betIndicator = p.bet ? '<span class="card-bet">🎲</span>' : '';
        var closestBadge = isClosest ? '<span class="closest-winner-badge">🎯</span>' : '';
        var artistBadge = p.artist_bonus > 0 ? '<span class="player-card-artist-badge">🎤 +' + p.artist_bonus + '</span>' : '';

        html += '<div class="result-card ' + scoreClass + closestClass + '">' +
            '<div class="card-name">' + escapeHtml(p.name) + betIndicator + closestBadge + '</div>' +
            '<div class="card-guess">' + guessDisplay + '</div>' +
            '<div class="card-accuracy">' + yearsOffDisplay + '</div>' +
            '<div class="card-score">+' + roundScore + artistBadge + '</div>' +
        '</div>';
    });

    html += '</div>';
    container.innerHTML = html;
}

/**
 * Render read-only challenge options (artist/movie) for admin spectator view.
 */
export function renderAdminChallengeOptions(containerId, options) {
    var container = document.getElementById(containerId);
    if (!container || !options) return;

    container.innerHTML = options.map(function(opt) {
        var label = typeof opt === 'string' ? opt : (opt.label || opt.name || opt);
        return '<div class="artist-option artist-option--readonly">' +
            escapeHtml(label) + '</div>';
    }).join('');
}

/**
 * Map a provider key to its localized display name (pause-recovery banner).
 * Returns '' for unknown/empty providers.
 */
export function _providerDisplayName(provider) {
    if (!provider) return '';
    var keyMap = {
        spotify: 'admin.pauseRecovery.providerSpotify',
        apple_music: 'admin.pauseRecovery.providerAppleMusic',
        youtube_music: 'admin.pauseRecovery.providerYouTubeMusic',
        tidal: 'admin.pauseRecovery.providerTidal',
        deezer: 'admin.pauseRecovery.providerDeezer'
    };
    var fallbackMap = {
        spotify: 'Spotify',
        apple_music: 'Apple Music',
        youtube_music: 'YouTube Music',
        tidal: 'Tidal',
        deezer: 'Deezer'
    };
    var key = keyMap[provider];
    if (!key) return '';
    return t(key) || fallbackMap[provider] || '';
}
