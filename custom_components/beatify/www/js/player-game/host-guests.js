/**
 * Beatify Player - Host guest list (#3304)
 *
 * The host running a party from their phone could not take out a guest who
 * wandered off, nor bring back one they had sat out — the controls (#2746)
 * lived on the admin page only, so every round kept waiting on a phone nobody
 * held.
 *
 * The design gate picked variant B: one "Guests" row in the host drawer with a
 * count line, and a full-height screen behind it. The screen is grouped by what
 * the host has to do, not by score:
 *
 *   - Not connected — first, with a visible "Sit out" button. This is the case
 *     the issue is about, so it is not hidden behind a menu.
 *   - In the game   — a quiet ⋮ per row, like the admin leaderboard. The host's
 *     own row has no control: the server refuses to remove the host anyway.
 *   - Sitting out   — "Bring back", one tap, no confirmation.
 *
 * Sitting a guest out goes through a bottom sheet that reuses the admin page's
 * sentence (admin.sitOutBody): it names the guest and says the points stay.
 * Both actions go to the server actions the admin page already uses
 * (`kick_player`, `reinstate_player`); every rule — host cannot be removed,
 * no return mid-round, none once Sudden Death has cut — stays server-side.
 *
 * Kept out of player-game.js on purpose: the drawer only calls in.
 */

import { state, escapeHtml, createModalFocusTrap } from '../player-utils.js';
import { showToast } from '../notify.js';

var SCREEN_ID = 'host-guests';
var SHEET_ID = 'host-guests-sheet';
var ROW_ID = 'host-drawer-guests';

var _open = false;
var _lastData = null;
var _pendingName = null;
var _sheetTrap = null;

function tr(key, params, fallback) {
    var utils = (typeof window !== 'undefined' && window.BeatifyUtils) || {};
    var s = typeof utils.t === 'function' ? utils.t(key, params) : '';
    if (!s || s === key) return fallback || key;
    return s;
}

function byScore(a, b) {
    var d = (b.player.score || 0) - (a.player.score || 0);
    if (d) return d;
    return String(a.player.name).localeCompare(String(b.player.name));
}

/**
 * Sort the players into the three groups of the guests screen.
 *
 * Each entry carries the one action its row offers:
 *   'sit-out'   — visible button (not connected) or ⋮ (in the game)
 *   'reinstate' — "Bring back"
 *   null        — no control at all
 *
 * No control for the host (the server refuses), for a Sudden Death casualty
 * (eliminated is final by design) and for a sat-out guest whose return is
 * already parked for the next round or who may not return because Sudden Death
 * has started cutting — the same rule as `rejoin_allowed` on the server, so the
 * host is not offered a tap the server would refuse.
 *
 * @param {Array<Object>} players - `players` from the state broadcast
 * @param {{suddenDeathMode?: boolean}} [opts]
 * @returns {{away: Array, playing: Array, satOut: Array}}
 */
export function guestGroups(players, opts) {
    var list = players || [];
    var sdCutting = !!(opts && opts.suddenDeathMode)
        && list.some(function(p) { return p.eliminated; });
    var away = [];
    var playing = [];
    var satOut = [];

    list.forEach(function(p) {
        if (p.is_admin) {
            playing.push({ player: p, action: null, host: true });
        } else if (p.eliminated) {
            playing.push({ player: p, action: null, eliminated: true });
        } else if (p.sat_out_by_host) {
            var pending = !!p.rejoin_requested;
            satOut.push({
                player: p,
                action: (pending || sdCutting) ? null : 'reinstate',
                pending: pending
            });
        } else if (!p.connected) {
            away.push({ player: p, action: 'sit-out', away: true });
        } else {
            playing.push({ player: p, action: 'sit-out', quiet: true });
        }
    });

    away.sort(byScore);
    satOut.sort(byScore);
    playing.sort(function(a, b) {
        if (a.host !== b.host) return a.host ? -1 : 1;
        return byScore(a, b);
    });
    return { away: away, playing: playing, satOut: satOut };
}

/**
 * The drawer row's count line: "1 not connected · 1 sitting out".
 * With nothing to do it says how many are in the game instead.
 */
export function guestsSummary(groups) {
    var parts = [];
    if (groups.away.length) {
        parts.push(tr('admin.guestsAway', { count: groups.away.length },
            groups.away.length + ' not connected'));
    }
    if (groups.satOut.length) {
        var n = groups.satOut.length;
        parts.push(tr(n === 1 ? 'admin.guestsSatOutOne' : 'admin.guestsSatOut',
            { count: n }, n + ' sitting out'));
    }
    if (!parts.length) {
        parts.push(tr('admin.guestsAllIn', { count: groups.playing.length },
            groups.playing.length + ' in the game'));
    }
    return parts.join(' · ');
}

function groupsFor(data) {
    return guestGroups(data && data.players, {
        suddenDeathMode: !!(data && data.sudden_death_mode)
    });
}

// ============================================
// Drawer row
// ============================================

/**
 * Render the "Guests" row into the host drawer, and keep an open guests screen
 * current. Called from renderHostDrawer on every broadcast.
 *
 * Host-only: for anyone else the row is removed and the screen closed.
 */
export function renderHostGuests(data) {
    var body = document.getElementById('host-drawer-body');
    var row = document.getElementById(ROW_ID);

    if (!state.isAdmin || !data) {
        if (row && row.remove) row.remove();
        hideHostGuests();
        return;
    }
    if (!body) return;
    _lastData = data;

    if (!row) {
        row = document.createElement('button');
        row.id = ROW_ID;
        row.type = 'button';
        row.className = 'host-drawer__row';
        row.addEventListener('click', openGuestsScreen);
        body.appendChild(row);
    }

    var groups = groupsFor(data);
    row.innerHTML =
        '<span class="host-drawer__row-icon">👥</span>' +
        '<span class="host-drawer__row-text">' +
            '<span class="host-drawer__row-title">' +
                escapeHtml(tr('admin.guestsRowTitle', null, 'Guests')) + '</span>' +
            '<span class="host-drawer__row-sub">' +
                (groups.away.length ? '<span class="host-guests__away-dot"></span>' : '') +
                escapeHtml(guestsSummary(groups)) + '</span>' +
        '</span>' +
        '<span class="host-drawer__chevron" aria-hidden="true">›</span>';

    if (_open) renderGuestsScreen();
}

// ============================================
// Guests screen
// ============================================

function rowHtml(entry) {
    var p = entry.player;
    var name = escapeHtml(p.name);
    var label = '';
    if (entry.away) label += '<span class="host-guests__away-dot"></span>';
    label += name;
    if (entry.host) {
        label += ' <span class="host-guests__host">' +
            escapeHtml(tr('admin.guestsHost', null, 'Host')) + '</span>';
    }
    if (entry.eliminated) {
        label += ' <span class="host-guests__badge">💀 ' +
            escapeHtml(tr('game.eliminated', null, 'Eliminated')) + '</span>';
    }
    if (entry.pending) {
        label += ' <span class="host-guests__badge">' +
            escapeHtml(tr('player.rejoinPending', null, 'Back in for the next round')) + '</span>';
    }

    var action;
    if (entry.action === 'reinstate') {
        action = '<button type="button" class="host-guests__btn host-guests__btn--back"' +
            ' data-guest-action="reinstate" data-player="' + name + '">' +
            escapeHtml(tr('admin.bringBack', null, 'Bring back')) + '</button>';
    } else if (entry.action === 'sit-out' && entry.quiet) {
        action = '<button type="button" class="host-guests__more"' +
            ' data-guest-action="sit-out" data-player="' + name + '"' +
            ' aria-label="' + escapeHtml(tr('admin.sitOutAria', { name: p.name }, 'Sit ' + p.name + ' out')) + '">⋮</button>';
    } else if (entry.action === 'sit-out') {
        action = '<button type="button" class="host-guests__btn host-guests__btn--warn"' +
            ' data-guest-action="sit-out" data-player="' + name + '">' +
            escapeHtml(tr('admin.sitOutConfirm', null, 'Sit out')) + '</button>';
    } else {
        action = '<span class="host-guests__spacer"></span>';
    }

    var cls = 'host-guests__row' + (entry.player.sat_out_by_host ? ' is-out' : '');
    return '<div class="' + cls + '">' +
        '<span class="host-guests__name">' + label + '</span>' +
        '<span class="host-guests__score">' + escapeHtml(String(p.score || 0)) + '</span>' +
        action + '</div>';
}

function sectionHtml(key, fallback, entries, extraClass) {
    if (!entries.length) return '';
    return '<div class="host-guests__sec' + (extraClass ? ' ' + extraClass : '') + '">' +
        escapeHtml(tr(key, null, fallback)) + ' · ' + entries.length + '</div>' +
        entries.map(rowHtml).join('');
}

/** The screen's markup for the given state. Exported for the tests. */
export function guestsScreenHtml(data) {
    var groups = groupsFor(data);
    return '<div class="host-guests__head">' +
            '<button type="button" class="host-guests__back" data-guests-back="1">‹ ' +
                escapeHtml(tr('admin.drawerTitle', null, 'Game flow')) + '</button>' +
            '<h2 class="host-guests__title" id="host-guests-title">' +
                escapeHtml(tr('admin.guestsRowTitle', null, 'Guests')) + '</h2>' +
        '</div>' +
        '<div class="host-guests__body">' +
            sectionHtml('admin.guestsSectionAway', 'Not connected', groups.away, 'is-away') +
            sectionHtml('admin.guestsSectionPlaying', 'In the game', groups.playing) +
            sectionHtml('admin.guestsSectionSatOut', 'Sitting out', groups.satOut) +
        '</div>' +
        '<div class="host-guests__foot">' +
            escapeHtml(tr('admin.guestsFooter', null,
                'Guests who sit out keep their points and can tap “I\'m back” themselves.')) +
        '</div>';
}

function onScreenClick(e) {
    var target = e && e.target;
    if (!target || !target.closest) return;
    if (target.closest('[data-guests-back]')) {
        closeGuestsScreen();
        return;
    }
    var btn = target.closest('[data-guest-action]');
    if (!btn) return;
    var name = btn.getAttribute('data-player');
    if (!name) return;
    if (btn.getAttribute('data-guest-action') === 'reinstate') {
        reinstateGuest(name);
    } else {
        requestSitOut(name);
    }
}

function renderGuestsScreen() {
    var screen = document.getElementById(SCREEN_ID);
    if (!screen) {
        screen = document.createElement('div');
        screen.id = SCREEN_ID;
        screen.className = 'host-guests';
        screen.setAttribute('role', 'dialog');
        screen.setAttribute('aria-modal', 'true');
        screen.setAttribute('aria-labelledby', 'host-guests-title');
        screen.addEventListener('click', onScreenClick);
        document.body.appendChild(screen);
    }
    screen.innerHTML = guestsScreenHtml(_lastData);
    screen.classList.remove('hidden');
}

export function openGuestsScreen() {
    if (!state.isAdmin || !_lastData) return;
    _open = true;
    renderGuestsScreen();
}

export function closeGuestsScreen() {
    _open = false;
    cancelSitOut();
    var screen = document.getElementById(SCREEN_ID);
    if (screen) screen.classList.add('hidden');
}

/** Close everything this module opened. Called when the drawer goes away. */
export function hideHostGuests() {
    closeGuestsScreen();
}

export function isGuestsScreenOpen() {
    return _open;
}

// ============================================
// Actions
// ============================================

function sendAdmin(payload) {
    var open = typeof WebSocket !== 'undefined' ? WebSocket.OPEN : 1;
    if (!state.ws || state.ws.readyState !== open) {
        showToast(tr('errors.CONNECTION_LOST', null, 'Connection lost'));
        return false;
    }
    state.ws.send(JSON.stringify(payload));
    return true;
}

/** Letting someone back in is not the tap that needs a guard: no sheet. */
export function reinstateGuest(name) {
    if (!state.isAdmin || !name) return;
    sendAdmin({ type: 'admin', action: 'reinstate_player', player_name: name });
}

/** Open the confirm sheet. Nothing is sent until the host confirms. */
export function requestSitOut(name) {
    if (!state.isAdmin || !name) return;
    _pendingName = name;

    var players = (_lastData && _lastData.players) || [];
    var entry = players.find(function(p) { return p.name === name; });

    var sheet = document.getElementById(SHEET_ID);
    if (!sheet) {
        sheet = document.createElement('div');
        sheet.id = SHEET_ID;
        sheet.className = 'modal host-guests-sheet';
        sheet.setAttribute('role', 'dialog');
        sheet.setAttribute('aria-modal', 'true');
        sheet.setAttribute('aria-labelledby', 'host-guests-sheet-title');
        sheet.addEventListener('click', function(e) {
            var t = e && e.target;
            var hit = t && t.closest ? t.closest('[data-sheet-action]') : null;
            if (!hit) return;
            if (hit.getAttribute('data-sheet-action') === 'confirm') confirmSitOut();
            else cancelSitOut();
        });
        document.body.appendChild(sheet);
    }
    sheet.innerHTML =
        '<div class="modal-backdrop" data-sheet-action="cancel"></div>' +
        '<div class="modal-content host-guests-sheet__card">' +
            '<span class="host-guests-sheet__handle"></span>' +
            '<h2 id="host-guests-sheet-title">' +
                escapeHtml(tr('admin.sitOutTitle', null, 'Sit this guest out?')) + '</h2>' +
            '<p>' + escapeHtml(tr('admin.sitOutBody',
                { name: name, score: entry ? (entry.score || 0) : 0 },
                name + ' stops playing this game. Their points stay.')) + '</p>' +
            '<button type="button" class="btn btn-primary host-guests-sheet__btn" data-sheet-action="confirm">' +
                escapeHtml(tr('admin.sitOutConfirm', null, 'Sit out')) + '</button>' +
            '<button type="button" class="btn btn-secondary host-guests-sheet__btn" data-sheet-action="cancel">' +
                escapeHtml(tr('common.cancel', null, 'Cancel')) + '</button>' +
        '</div>';
    sheet.classList.remove('hidden');

    _sheetTrap = createModalFocusTrap(sheet);
    var cancelBtn = sheet.querySelector ? sheet.querySelector('[data-sheet-action="cancel"].btn') : null;
    _sheetTrap.activate({ initialFocus: cancelBtn, onEscape: cancelSitOut });
}

function closeSheet() {
    _pendingName = null;
    if (_sheetTrap) {
        _sheetTrap.deactivate();
        _sheetTrap = null;
    }
    var sheet = document.getElementById(SHEET_ID);
    if (sheet) sheet.classList.add('hidden');
}

export function confirmSitOut() {
    var name = _pendingName;
    closeSheet();
    if (!name || !state.isAdmin) return;
    sendAdmin({ type: 'admin', action: 'kick_player', player_name: name });
}

export function cancelSitOut() {
    closeSheet();
}
