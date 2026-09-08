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

import { PROVIDERS_BY_ID } from '../../providers.generated.js';

// #2718: `t()` below returns the KEY on a miss, and a key is truthy, so the
// `t(...) || 'literal'` shape used by the older helpers can never reach its
// fallback (the #1402-B8 defect, re-found by #2582). `tr()` from admin/util.js
// is the corrected form — key-aware and interpolating — so the newer helpers
// take it rather than repeat the broken idiom.
import { tr } from '../util.js';

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
        // Issue #827: eliminated players are out of the round — never count as
        // submitted, render dimmed with a skull instead of submit state.
        var classes = [
            'player-indicator',
            (!p.eliminated && p.submitted) ? 'is-submitted' : '',
            p.eliminated ? 'is-eliminated' : '',
            p.connected === false ? 'player-indicator--disconnected' : ''
        ].filter(Boolean).join(' ');
        var badges = '';
        if (!p.eliminated && p.steal_used) badges += '<span class="player-badge player-badge--steal">🥷</span>';
        if (!p.eliminated && p.bet) badges += '<span class="player-badge player-badge--bet">🎲</span>';
        var avatarInner = p.eliminated
            ? '<span class="eliminated-skull">💀</span>'
            : '<span class="player-initials">' + escapeHtml(initials) + '</span>';
        return '<div class="' + classes + '">' + badges +
            '<div class="player-avatar">' + avatarInner + '</div>' +
            '<span class="player-name">' + escapeHtml(p.name) + '</span></div>';
    }).join('');
}

/**
 * Render an admin leaderboard list into one or both spectator containers.
 * @param {Array<{rank:number, name:string, score:number, connected?:boolean, streak?:number, rank_change?:number}>} leaderboard
 * @param {string} [containerId] - render into this id only; else both playing+reveal lists
 */
export function renderAdminLeaderboard(leaderboard, containerId, withHostControls) {
    var targets = containerId ? [containerId] : ['admin-playing-leaderboard-list', 'admin-reveal-leaderboard'];
    if (!leaderboard) return;

    var html = '';
    leaderboard.forEach(function(entry) {
        var rankClass = entry.rank <= 3 ? 'is-top-' + entry.rank : '';
        var disconnectedClass = entry.connected === false ? 'leaderboard-entry--disconnected' : '';
        // Issue #827: dim eliminated players + skull-prefix their name.
        var eliminatedClass = entry.eliminated ? 'is-eliminated' : '';
        var skullPrefix = entry.eliminated ? '💀 ' : '';
        var awayBadge = entry.connected === false ? '<span class="away-badge">(away)</span>' : '';
        // #2746: taken out by the host. No skull — nobody was eliminated,
        // somebody left — and the rank and score stay exactly where they were.
        var satOut = !!entry.sat_out_by_host;
        var satOutClass = satOut ? 'is-sat-out' : '';
        var satOutBadge = satOut
            ? '<span class="sat-out-badge">' + escapeHtml(tr('game.satOut', 'sat out')) + '</span>'
            : '';
        var streakIndicator = '';
        if (entry.streak >= 2) {
            var hotClass = entry.streak >= 5 ? 'streak-indicator--hot' : '';
            streakIndicator = '<span class="streak-indicator ' + hotClass + '">🔥' + entry.streak + '</span>';
        }
        var changeIndicator = '';
        if (entry.rank_change > 0) changeIndicator = '<span class="rank-up">▲' + entry.rank_change + '</span>';
        else if (entry.rank_change < 0) changeIndicator = '<span class="rank-down">▼' + Math.abs(entry.rank_change) + '</span>';

        // #2746: the host's own rows carry the control that takes a guest out
        // of the running game. Rendered only when this leaderboard is the
        // host's (`withHostControls`), never on a guest phone or the TV —
        // option B makes every guest row removable, not every screen.
        var control = '';
        if (withHostControls && !entry.is_admin) {
            control = satOut
                ? '<button type="button" class="entry-host-action" data-action="reinstate"'
                    + ' data-player="' + escapeHtml(entry.name) + '">'
                    + escapeHtml(tr('admin.bringBack', 'Bring back')) + '</button>'
                : '<button type="button" class="entry-host-action" data-action="sit-out"'
                    + ' data-player="' + escapeHtml(entry.name) + '"'
                    + ' aria-label="' + escapeHtml(tr('admin.sitOutAria', 'Sit {name} out', { name: entry.name })) + '">⋮</button>';
        }

        html += '<div class="leaderboard-entry ' + rankClass + ' ' + disconnectedClass + ' ' + eliminatedClass + ' ' + satOutClass + '">' +
            '<span class="entry-rank">#' + entry.rank + '</span>' +
            '<span class="entry-name">' + skullPrefix + escapeHtml(entry.name) + awayBadge + satOutBadge + '</span>' +
            '<span class="entry-meta">' + streakIndicator + changeIndicator + '</span>' +
            '<span class="entry-score">' + entry.score + '</span>' +
            control +
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
    // #2713: the i18n key and the English fallback both come from the registry
    // instead of two parallel maps here. A provider with no `pauseRecoveryKey`
    // has no translated name yet, so the banner omits it — the behaviour
    // Crate Digger, Amazon Music and ytmusic_free have always had.
    var spec = PROVIDERS_BY_ID[provider];
    if (!spec || !spec.pauseRecoveryKey) return '';
    return t(spec.pauseRecoveryKey) || spec.label || '';
}

/**
 * #2718 — who is present, who is away, and how long they have been away.
 *
 * The lobby's answer to "someone scanned, typed a name and walked off". The
 * server has been able to remove such a guest since #659; PR #1613 deleted the
 * only UI that ever asked it to, and the tile grid that replaced the flat
 * lobby showed names and nothing else.
 *
 * Design gate (05.09.2026) picked **variant C** over the greyed-tile-with-a-×
 * that was built first:
 *
 * - The grid keeps one meaning — *who is playing*. Away guests leave it, so a
 *   removable element never sits next to an untouchable one, and the misplaced
 *   tap at a party is designed out rather than caught by a modal.
 * - Away guests gather in a list below it, one row each, with **the duration**.
 *   That is the whole point of the variant, not decoration: four minutes away
 *   is the bathroom, twelve minutes away is gone. Every other shape told the
 *   host only "not currently connected" and then asked for a decision that
 *   cannot be made from that.
 * - The button carries the **word** "Remove", not a `×` glyph to interpret.
 *
 * There is deliberately **no grace period**: a guest appears in the list the
 * moment `connected` goes false. The duration *is* the grace period, judged by
 * a human standing in the room — a machine one on top would duplicate that
 * judgement and delay exactly the case the feature exists for.
 *
 * Kept pure (players in, HTML out) so every state is unit-testable;
 * `BeatifyHome.renderPlayers` does the DOM write and the click wiring.
 */

// Name, display label and initial, resolved the same way for a tile and for an
// away row so the two never disagree about who a player is.
function _playerLabel(p) {
    var raw = String(p.name == null ? (p.id == null ? '?' : p.id) : p.name).trim();
    return {
        label: raw || 'Guest',
        initial: (raw.charAt(0) || '?').toUpperCase(),
    };
}

// Explicit `=== false`: a payload without the field (an older server, a REST
// poll mid-upgrade) must not paint every guest as gone.
function _isAway(p) {
    return p.connected === false;
}

// The guests the away list is about — and exactly the ones
// `admin_kick_player` will act on. The server refuses a connected player and
// refuses the admin, so offering a Remove button for either could only ever
// fail. An away HOST keeps their tile in the grid instead: the information is
// useful, the action is not available.
function _removableAway(players) {
    return (players || []).filter(function(p) { return _isAway(p) && !p.is_admin; });
}

/**
 * Format an away duration for one row.
 *
 * `seconds` is server-computed (`away_seconds`, from `PlayerRegistry`), never
 * derived from `Date.now()` here — a browser-side timer would restart at every
 * host reload and report "just now" for a guest who left before dinner.
 *
 * Rounds down, so "4 min" means at least four minutes have passed. Null or
 * missing yields '' — the row then shows no duration at all rather than a
 * fabricated zero, because a wrong number is worse than a missing one when the
 * number is the thing the host acts on.
 *
 * @param {number|null|undefined} seconds
 * @returns {string}
 */
export function formatAwayDuration(seconds) {
    if (typeof seconds !== 'number' || !isFinite(seconds) || seconds < 0) return '';
    if (seconds < 60) return tr('lobby.awayJustNow', 'just now');
    if (seconds < 3600) {
        return tr('lobby.awayMinutes', '{count} min', { count: Math.floor(seconds / 60) });
    }
    return tr('lobby.awayHours', '{count} h', { count: Math.floor(seconds / 3600) });
}

/**
 * The tile grid — **present players only** (#2718 variant C).
 *
 * An away guest is no longer a greyed tile here; they moved to
 * `buildHomeAwayList` below. The host stays whatever their connection is
 * doing, marked away when it drops, because their tile is not removable and
 * dropping it would make the host's own phone look like it had left the party.
 *
 * Because away guests are filtered out before the colour cycle runs, the
 * remaining guests take contiguous colours instead of leaving a gap where an
 * absent guest used to sit.
 *
 * @param {Array<{name?:string, id?:string, is_admin?:boolean, connected?:boolean, onboarded?:boolean}>} players
 * @returns {string} HTML for the tiles inside `#home-players`
 */
export function buildHomePlayerTiles(players) {
    var guestVariants = ['c1', 'c2', 'c3', 'c4'];
    var guestIdx = 0;
    return (players || []).filter(function(p) {
        return p.is_admin || !_isAway(p);
    }).map(function(p) {
        var isHost = !!p.is_admin;
        var isAway = _isAway(p);
        var isLearning = !isHost && p.onboarded === false;
        var variant = isHost ? 'host' : guestVariants[guestIdx++ % guestVariants.length];
        var names = _playerLabel(p);
        var crown = isHost
            ? '<span class="home-player-tile-crown" aria-hidden="true">👑</span>'
            : '';
        var tour = isLearning
            ? '<span class="home-player-tile-tour" aria-hidden="true">TOUR</span>'
            : '';
        var away = isAway
            ? '<span class="home-player-tile-away">' + escapeHtml(tr('lobby.away', 'away')) + '</span>'
            : '';
        var cls = ['home-player-tile', 'home-player-tile--' + variant];
        if (isLearning) cls.push('home-player-tile--learning');
        if (isAway) cls.push('home-player-tile--away');
        return '<div class="' + cls.join(' ') + '">'
            + '<span class="home-player-tile-initial">' + escapeHtml(names.initial) + '</span>'
            + '<span class="home-player-tile-name">' + escapeHtml(names.label) + '</span>'
            + crown + tour + away
            + '</div>';
    }).join('');
}

/**
 * The count line above the grid (#2718 variant C).
 *
 * Rendered **only while somebody is away**, which is exactly when the grid
 * stops telling the whole story — that is variant C's one real cost ("the
 * guest count is no longer in one place"), and this is the line that pays it.
 * With nobody away the grid IS the count, and the host's screen is short
 * enough without a row that repeats it.
 *
 * @param {Array<Object>} players
 * @returns {string} HTML, or '' when nobody is away
 */
export function buildHomePlayerCount(players) {
    var list = players || [];
    var away = _removableAway(list);
    if (!away.length) return '';
    var total = list.length;
    var here = list.filter(function(p) { return !_isAway(p); }).length;
    var totalText = total === 1
        ? tr('admin.home.guestCountOne', '1 guest')
        : tr('admin.home.guestCount', '{count} guests', { count: total });
    var hereText = tr('admin.home.guestsHere', '{count} here', { count: here });
    return '<p class="home-players-count">'
        + escapeHtml(totalText) + ' · ' + escapeHtml(hereText)
        + '</p>';
}

/**
 * The away list below the grid (#2718 variant C).
 *
 * One row per away guest: initial chip, name, how long they have been gone,
 * and a Remove button that carries the word rather than a glyph. Empty string
 * when nobody is away, so the lobby looks exactly as it did before.
 *
 * The button only opens the confirm card — `BeatifyHome.renderPlayers` wires
 * the click to `confirmKickPlayer`, and only the confirm sends `kick_player`.
 *
 * @param {Array<{name?:string, id?:string, is_admin?:boolean, connected?:boolean, away_seconds?:number}>} players
 * @returns {string} HTML, or '' when nobody is away
 */
export function buildHomeAwayList(players) {
    var away = _removableAway(players);
    if (!away.length) return '';
    var rows = away.map(function(p) {
        var names = _playerLabel(p);
        var since = formatAwayDuration(p.away_seconds);
        var sinceCell = since
            ? '<span class="home-away-since">' + escapeHtml(since) + '</span>'
            : '';
        var aria = tr('admin.kickPlayerAria', 'Remove {name} from the lobby', { name: names.label });
        return '<li class="home-away-row">'
            + '<span class="home-away-initial" aria-hidden="true">' + escapeHtml(names.initial) + '</span>'
            + '<span class="home-away-name">' + escapeHtml(names.label) + '</span>'
            + sinceCell
            + '<button type="button" class="home-away-remove"'
            + ' data-player="' + escapeHtml(names.label) + '"'
            + ' aria-label="' + escapeHtml(aria) + '">'
            + escapeHtml(tr('admin.kickPlayerRemove', 'Remove'))
            + '</button>'
            + '</li>';
    }).join('');
    return '<section class="home-away">'
        + '<h3 class="home-away-heading">' + escapeHtml(tr('lobby.awayHeading', 'Away')) + '</h3>'
        + '<ul class="home-away-rows">' + rows + '</ul>'
        + '</section>';
}
