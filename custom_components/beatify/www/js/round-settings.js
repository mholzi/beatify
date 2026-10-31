/**
 * Beatify — the host changes timer and difficulty between two rounds (#2586).
 *
 * Variant B of the design gate: one row above "Next Round" names what the next
 * round will run with, and a tap opens a bottom sheet. A chip tap applies at
 * once (the action goes out, the state broadcast repaints); there is no draft
 * and no save button, the same way the Sudden Death toggle works.
 *
 * The reveal's auto-advance countdown keeps running while the sheet is open, and
 * the sheet closes when the phase leaves REVEAL. Holding the room up for the
 * host was the rejected alternative. The countdown itself sits at the top of a
 * long reveal, or on a control bar the sheet covers, so the sheet's own Next
 * Round button carries the seconds.
 *
 * Both host surfaces import this: `admin.js` on the admin browser and
 * `player-reveal.js` on the phone of a host who plays along. Same markup in
 * admin.html and player.html, so the two cannot drift apart.
 */

import {
    DIFFICULTY_LABELS,
    ROUND_TIMER_OPTIONS,
    difficultyHint,
} from './game-constants.js';

/** `t(key, fallback, params)` over BeatifyUtils.t, as difficultyHint wants it. */
function _t(key, fallback, params) {
    var utils = (typeof window !== 'undefined' && window.BeatifyUtils) || {};
    var out = utils.t ? utils.t(key, params) : null;
    if (out && out !== key) return out;
    return String(fallback).replace(/\{(\w+)\}/g, function (match, name) {
        return params && params[name] !== undefined ? params[name] : match;
    });
}

function _difficultyLabel(level) {
    var label = DIFFICULTY_LABELS[level];
    return label ? _t(label.key, label.fallback) : level;
}

/**
 * The closed row's text, e.g. `⏱ 45s · Normal`. Title & Artist has no
 * difficulty to name, so it reads `⏱ 45s`.
 */
export function roundSettingsRowText(settings, titleArtistMode) {
    var timer = '⏱ ' + settings.round_duration + 's';
    if (titleArtistMode) return timer;
    return timer + ' · ' + _difficultyLabel(settings.difficulty);
}

/** The action a chip tap sends. */
export function roundSettingsAction(field, value) {
    var action = { type: 'admin', action: 'set_round_settings' };
    action[field] = value;
    return action;
}

/**
 * Whole seconds until the reveal auto-advances, from the same three fields the
 * admin's Next button and the phone's ring read. Null when nothing is counting:
 * auto-advance off, or the server holding the reveal (`idle_halt`).
 */
export function revealSecondsLeft(data, now) {
    var advance = (data && data.reveal_auto_advance) || 0;
    var startedAt = data && data.reveal_started_at;
    if (advance <= 0 || !startedAt || data.idle_halt) return null;
    return Math.max(0, Math.ceil((startedAt + advance * 1000 - now) / 1000));
}

var _doc = null;
var _returnFocus = null;
var _lastData = null;
var _countTick = null;

function _paintCount() {
    var count = _doc.getElementById('round-settings-next-count');
    if (!count) return null;
    var seconds = revealSecondsLeft(_lastData, Date.now());
    count.classList.toggle('hidden', seconds === null);
    count.textContent = seconds === null ? '' : String(seconds);
    return seconds;
}

function _stopCount() {
    if (_countTick !== null) {
        clearInterval(_countTick);
        _countTick = null;
    }
}

/** Ticks only while the sheet is open, and stops at 0, as on the admin's button. */
function _syncCount() {
    _stopCount();
    if (!_isOpen()) return;
    var seconds = _paintCount();
    if (!seconds) return;
    _countTick = setInterval(function () {
        if (!_paintCount()) _stopCount();
    }, 500);
}

function _sheet() {
    return _doc ? _doc.getElementById('round-settings-sheet') : null;
}

function _isOpen() {
    var sheet = _sheet();
    return !!sheet && !sheet.classList.contains('hidden');
}

function _chip(doc, label, onTap) {
    var chip = doc.createElement('button');
    chip.type = 'button';
    chip.className = 'chip round-settings-chip';
    chip.setAttribute('aria-pressed', 'false');
    chip.textContent = label;
    chip.addEventListener('click', onTap);
    return chip;
}

function _paintChip(chip, active) {
    chip.classList.toggle('chip--active', active);
    chip.setAttribute('aria-pressed', active ? 'true' : 'false');
}

function _onSheetKeydown(e) {
    if (e.key === 'Escape' || e.key === 'Esc') {
        e.preventDefault();
        closeRoundSettings();
        return;
    }
    if (e.key !== 'Tab') return;
    var sheet = _sheet();
    var focusable = Array.prototype.filter.call(
        sheet.querySelectorAll('button'),
        function (el) { return !el.disabled && el.offsetParent !== null; }
    );
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (e.shiftKey && _doc.activeElement === first) {
        e.preventDefault();
        last.focus();
    } else if (!e.shiftKey && _doc.activeElement === last) {
        e.preventDefault();
        first.focus();
    }
}

function _openSheet() {
    var sheet = _sheet();
    if (!sheet) return;
    _returnFocus = _doc.activeElement;
    sheet.classList.remove('hidden');
    var target = sheet.querySelector('.round-settings-chip.chip--active')
        || sheet.querySelector('.round-settings-chip');
    if (target) target.focus();
    _syncCount();
}

/** Close the sheet if it is open. Safe to call from any phase, on any page. */
export function closeRoundSettings() {
    _stopCount();
    if (!_isOpen()) return;
    _sheet().classList.add('hidden');
    if (_returnFocus && _returnFocus.focus && _returnFocus.isConnected) {
        _returnFocus.focus();
    }
    _returnFocus = null;
}

/**
 * Wire the row and the sheet once.
 *
 * @param {Object} opts
 * @param {Document} opts.doc
 * @param {function(Object): void} opts.send - sends an admin action
 * @param {string} opts.nextButtonId - the surface's own Next Round button; the
 *   one in the sheet clicks it, so its guards stay in one place
 */
export function setupRoundSettings(opts) {
    var doc = opts.doc;
    var row = doc.getElementById('round-settings-row');
    var sheet = doc.getElementById('round-settings-sheet');
    if (!row || !sheet) return;
    _doc = doc;

    row.addEventListener('click', _openSheet);
    sheet.addEventListener('keydown', _onSheetKeydown);
    var backdrop = sheet.querySelector('.modal-backdrop');
    if (backdrop) backdrop.addEventListener('click', closeRoundSettings);

    var timerGroup = doc.getElementById('round-settings-timer');
    ROUND_TIMER_OPTIONS.forEach(function (seconds) {
        var chip = _chip(doc, seconds + 's', function () {
            opts.send(roundSettingsAction('timer', seconds));
        });
        chip.dataset.value = String(seconds);
        timerGroup.appendChild(chip);
    });

    var difficultyGroup = doc.getElementById('round-settings-difficulty');
    Object.keys(DIFFICULTY_LABELS).forEach(function (level) {
        var chip = _chip(doc, _difficultyLabel(level), function () {
            opts.send(roundSettingsAction('difficulty', level));
        });
        chip.dataset.value = level;
        chip.setAttribute('data-i18n', DIFFICULTY_LABELS[level].key);
        difficultyGroup.appendChild(chip);
    });

    var next = doc.getElementById('round-settings-next');
    if (next) {
        next.addEventListener('click', function () {
            closeRoundSettings();
            var target = doc.getElementById(opts.nextButtonId);
            if (target) target.click();
        });
    }
}

/**
 * Paint the row and the sheet from a REVEAL state.
 *
 * `next_round_settings` is host-only and null on the last reveal, which has no
 * next round. `visible` is the second lock on the phone, as with the encore.
 */
export function renderRoundSettings(data, visible) {
    var doc = _doc;
    if (!doc) return;
    _lastData = data;
    var row = doc.getElementById('round-settings-row');
    var settings = visible && data ? data.next_round_settings : null;
    row.classList.toggle('hidden', !settings);
    if (!settings) {
        closeRoundSettings();
        return;
    }

    var titleArtist = !!data.title_artist_mode;
    doc.getElementById('round-settings-row-text').textContent =
        roundSettingsRowText(settings, titleArtist);

    doc.querySelectorAll('#round-settings-timer .round-settings-chip').forEach(function (chip) {
        _paintChip(chip, chip.dataset.value === String(settings.round_duration));
    });
    doc.querySelectorAll('#round-settings-difficulty .round-settings-chip').forEach(function (chip) {
        _paintChip(chip, chip.dataset.value === settings.difficulty);
        chip.textContent = _difficultyLabel(chip.dataset.value);
    });
    doc.getElementById('round-settings-difficulty-block').classList.toggle('hidden', titleArtist);
    doc.getElementById('round-settings-hint').textContent =
        titleArtist ? '' : difficultyHint(settings.difficulty, _t);
    doc.getElementById('round-settings-foot').textContent = _t(
        'admin.roundSettingsFoot',
        'Applies from round {round}. Scores so far stay.',
        { round: (data.round || 0) + 1 }
    );
    _syncCount();
}
