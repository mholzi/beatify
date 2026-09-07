/**
 * Beatify — "End round N" host card (#2646).
 *
 * The host taps Next in round 5 because the song turned out to be a cover, or
 * because Music Assistant played twenty seconds of silence. Until this module
 * existed that tap went straight to `end_round()`: everyone who had not
 * answered counted as wrong, their streaks reset, and in Sudden Death one of
 * them was eliminated — knocked out of the game by a broken recording, with no
 * warning that it was about to happen.
 *
 * Design variant C ("the question comes after"), plus the reason chips from
 * variant D. Next stays ONE button. Pressed *while the round is still running*
 * — the suspicious case — it asks once, and names the consequences with the
 * server's real numbers before they happen:
 *
 *     End round 5
 *     22 seconds left · 3 of 8 have answered
 *     [ Score it as usual   5 players count as wrong · 4 streaks break · Tom is eliminated ]
 *     [ Do not score it     No points, no broken streaks, nobody is eliminated ]
 *       Why? (optional)  · cover · silence · wrong year · wrong title ·
 *     [ Let it keep playing ]
 *
 * After the timer has expired it does NOT ask: the round is over anyway, and
 * the host who taps Next then is just moving the party along.
 *
 * The numbers arrive on the PLAYING broadcast as `admin_round_end_preview`
 * (see `GameState.preview_round_end`). When the server cannot name the player
 * Sudden Death would cut — which happens only once everybody has answered, the
 * case where ending early costs nobody their guess — the card says what
 * happens without saying to whom.
 *
 * Pure except for `openRoundEndChoice`, which needs a document. Both host
 * surfaces (`admin.js` on the admin browser, `player-game.js` on the phone)
 * import from here so the wording and the ask/no-ask rule cannot drift apart
 * between them, and so the whole decision is unit-testable without a DOM.
 */

import { VOID_ROUND_REASONS } from './game-constants.js';

/**
 * i18n key + English fallback per reason chip. Literal keys so
 * `tests/unit/test_i18n_keys_exist_2507.py` can see them without a
 * DYNAMIC_PREFIXES entry, and keyed by the same strings `const.py` accepts —
 * an unknown chip is silently dropped server-side, which would look like the
 * reason simply never being recorded.
 */
export const VOID_REASON_LABELS = {
    cover: { key: 'admin.voidReasonCover', fallback: 'Cover version' },
    silence: { key: 'admin.voidReasonSilence', fallback: 'Silence' },
    wrong_year: { key: 'admin.voidReasonWrongYear', fallback: 'Wrong year' },
    wrong_title: { key: 'admin.voidReasonWrongTitle', fallback: 'Wrong title' },
};

// ---------------------------------------------------------------------------
// "Is the round still running?" — the ask / do-not-ask boundary
// ---------------------------------------------------------------------------

// The last PLAYING broadcast, anchored to the client clock at the moment it
// arrived. The server re-sends `seconds_remaining` on every broadcast (#1662)
// but broadcasts are event-driven, so between two of them the value goes stale
// by exactly the wall time that has passed — which is what the anchor
// subtracts. Module-level, like the countdown's own anchor in
// player-game/timer.js, so neither host surface has to keep a copy of the last
// state around just to answer "is the round still running".
var _round = null;

/**
 * Record the running round from a state broadcast. Call on every state update,
 * in every phase — anything that is not a live PLAYING round clears the anchor.
 *
 * @param {Object} data - a state payload
 * @param {number} [nowMs] - injectable clock for tests
 */
export function noteRoundState(data, nowMs) {
    var now = typeof nowMs === 'number' ? nowMs : Date.now();
    if (!data || data.phase !== 'PLAYING' || typeof data.seconds_remaining !== 'number') {
        _round = null;
        return;
    }
    _round = {
        seconds: Math.max(0, data.seconds_remaining),
        at: now,
        round: data.round || 0,
        preview: data.admin_round_end_preview || null,
    };
}

/** Forget the anchor (round ended, game ended, socket dropped). */
export function resetRoundState() {
    _round = null;
}

/** The last PLAYING broadcast's `admin_round_end_preview`, or null. */
export function currentPreview() {
    return _round ? _round.preview : null;
}

/** The running round's number, or 0. */
export function currentRoundNumber() {
    return _round ? _round.round : 0;
}

/**
 * Seconds left in the running round, or null when no round is running.
 *
 * @param {number} [nowMs] - injectable clock for tests
 * @returns {number|null}
 */
export function secondsLeftNow(nowMs) {
    if (!_round) return null;
    var now = typeof nowMs === 'number' ? nowMs : Date.now();
    return Math.max(0, _round.seconds - (now - _round.at) / 1000);
}

/**
 * Whether tapping Next right now should ask first.
 *
 * True only while a PLAYING round's timer has not run out. A round that
 * reached its deadline is over on its own terms — asking there would put a
 * three-choice card in front of the host every single round, which is the cost
 * the design weighed and rejected. Reaching REVEAL clears the anchor, so the
 * reveal screen's own Next button never asks either.
 *
 * @param {number} [nowMs] - injectable clock for tests
 */
export function shouldAskBeforeEnding(nowMs) {
    var left = secondsLeftNow(nowMs);
    return left !== null && left > 0;
}

// ---------------------------------------------------------------------------
// The words on the card
// ---------------------------------------------------------------------------

/**
 * The card's subtitle: how long is left and how many people have answered.
 *
 * @param {Object} preview - `admin_round_end_preview` from the broadcast
 * @param {number|null} secondsLeft
 * @param {function(string, string, Object=): string} t - key, fallback, params
 */
export function subtitleFor(preview, secondsLeft, t) {
    var p = preview || {};
    var parts = [];
    if (typeof secondsLeft === 'number' && secondsLeft > 0) {
        parts.push(t('admin.roundEndSecondsLeft', '{n} seconds left', {
            n: Math.round(secondsLeft),
        }));
    }
    if (typeof p.player_count === 'number' && p.player_count > 0) {
        parts.push(t('admin.roundEndAnswered', '{n} of {total} have answered', {
            n: p.submitted_count || 0,
            total: p.player_count,
        }));
    }
    return parts.join(' · ');
}

/**
 * The "Score it as usual" subtitle — what scoring the round would actually do.
 *
 * Built from real numbers where the server can supply them. The fallback the
 * design asked for ("Streaks break, and in Sudden Death somebody is
 * eliminated") is used only for the part that is genuinely unknown: the name
 * of the player who would go out. It is never used to paper over a missing
 * preview with a sentence that might not be true — with no preview at all the
 * card says nothing rather than something wrong.
 *
 * @param {Object} preview - `admin_round_end_preview` from the broadcast
 * @param {function(string, string, Object=): string} t - key, fallback, params
 * @returns {string} possibly empty
 */
export function scoreConsequence(preview, t) {
    var p = preview || {};
    var parts = [];
    if (p.counting_wrong > 0) {
        parts.push(t('admin.roundEndCountWrong', '{n} players count as wrong', {
            n: p.counting_wrong,
        }));
    }
    if (p.streaks_breaking > 0) {
        parts.push(t('admin.roundEndStreaksBreak', '{n} streaks break', {
            n: p.streaks_breaking,
        }));
    }
    if (p.eliminated) {
        parts.push(t('admin.roundEndEliminated', '{name} is eliminated', {
            name: p.eliminated,
        }));
    } else if (p.elimination_possible) {
        // The honest weaker sentence: Sudden Death will cut somebody, but who
        // depends on the scoring pass and nobody has been named.
        parts.push(t(
            'admin.roundEndEliminatedUnknown',
            'in Sudden Death somebody is eliminated',
        ));
    }
    return parts.join(' · ');
}

// ---------------------------------------------------------------------------
// The card itself
// ---------------------------------------------------------------------------

/**
 * Fill in and show the three-choice card, and hand back the host's answer.
 *
 * @param {Object} opts
 * @param {Document} opts.doc
 * @param {Object} [opts.preview] - `admin_round_end_preview`; defaults to the
 *   one on the last PLAYING broadcast
 * @param {number} [opts.round] - round number for the heading; same default
 * @param {number|null} [opts.secondsLeft] - same default
 * @param {function(string, string, Object=): string} opts.t
 * @param {function(Element): Object} [opts.focusTrap] - createModalFocusTrap
 * @returns {Promise<{choice: string, reason: (string|null)}>} choice is
 *   'score', 'void' or 'keep'; 'keep' is also what a backdrop tap or Escape
 *   resolves to, because doing nothing is the safe answer here.
 */
var _closeOpenCard = null;

/**
 * Dismiss an open card as "let it keep playing", if one is open.
 *
 * The safe answer, so this is what Escape and the backdrop resolve to. Exported
 * for the admin browser, whose Escape handling lives in one shared registry
 * (`admin/modal-escape.js`) that needs a stable function to register once.
 */
export function closeRoundEndChoice() {
    if (_closeOpenCard) _closeOpenCard();
}

export function openRoundEndChoice(opts) {
    var doc = opts.doc;
    var t = opts.t;
    var preview = opts.preview !== undefined ? opts.preview : currentPreview();
    var round = opts.round || currentRoundNumber();
    var secondsLeft = opts.secondsLeft !== undefined ? opts.secondsLeft : secondsLeftNow();
    var modal = doc.getElementById('round-end-modal');
    return new Promise(function (resolve) {
        if (!modal) {
            // No markup (an old cached page): fall back to the behaviour that
            // shipped before this module — score the round, as Next always did.
            resolve({ choice: 'score', reason: null });
            return;
        }

        var titleEl = doc.getElementById('round-end-title');
        var subEl = doc.getElementById('round-end-sub');
        var scoreSubEl = doc.getElementById('round-end-score-sub');
        var scoreBtn = doc.getElementById('round-end-score');
        var voidBtn = doc.getElementById('round-end-void');
        var keepBtn = doc.getElementById('round-end-keep');
        var chipWrap = doc.getElementById('round-end-reasons');
        var backdrop = modal.querySelector('.modal-backdrop');

        if (titleEl) {
            titleEl.textContent = t('admin.roundEndTitle', 'End round {n}', {
                n: round || (preview && preview.round) || 0,
            });
        }
        if (subEl) subEl.textContent = subtitleFor(preview, secondsLeft, t);
        if (scoreSubEl) {
            var consequence = scoreConsequence(preview, t);
            scoreSubEl.textContent = consequence;
            scoreSubEl.hidden = !consequence;
        }

        var reason = null;
        var chips = renderReasonChips(doc, chipWrap, t, function (picked) {
            reason = picked;
        });

        var trap = opts.focusTrap ? opts.focusTrap(modal) : null;
        _closeOpenCard = function () { finish('keep'); };
        modal.classList.remove('hidden');
        if (trap) {
            // "Let it keep playing" is the safe default: the host may have hit
            // Next by accident, and every other choice ends the round.
            trap.activate({ initialFocus: keepBtn, onEscape: function () { finish('keep'); } });
        }

        function finish(choice) {
            _closeOpenCard = null;
            modal.classList.add('hidden');
            if (scoreBtn) scoreBtn.removeEventListener('click', onScore);
            if (voidBtn) voidBtn.removeEventListener('click', onVoid);
            if (keepBtn) keepBtn.removeEventListener('click', onKeep);
            if (backdrop) backdrop.removeEventListener('click', onKeep);
            chips.forEach(function (c) { c.el.removeEventListener('click', c.handler); });
            if (trap) trap.deactivate();
            resolve({ choice: choice, reason: choice === 'void' ? reason : null });
        }

        function onScore() { finish('score'); }
        function onVoid() { finish('void'); }
        function onKeep() { finish('keep'); }

        if (scoreBtn) scoreBtn.addEventListener('click', onScore);
        if (voidBtn) voidBtn.addEventListener('click', onVoid);
        if (keepBtn) keepBtn.addEventListener('click', onKeep);
        if (backdrop) backdrop.addEventListener('click', onKeep);
    });
}

/**
 * Paint the optional reason chips and wire single-select toggling.
 *
 * Rendered from `VOID_ROUND_REASONS` rather than written out in the markup, so
 * the chips on screen are the values `const.py` accepts — a chip the server
 * does not know is dropped there, and the report would silently be empty.
 *
 * @param {Document} doc
 * @param {Element|null} wrap
 * @param {function(string, string, Object=): string} t
 * @param {function(string|null): void} onPick
 * @returns {Array<{el: Element, handler: function}>}
 */
export function renderReasonChips(doc, wrap, t, onPick) {
    if (!wrap) return [];
    wrap.textContent = '';
    var made = [];
    VOID_ROUND_REASONS.forEach(function (reason) {
        var label = VOID_REASON_LABELS[reason];
        var btn = doc.createElement('button');
        btn.type = 'button';
        btn.className = 'round-end-chip';
        btn.setAttribute('aria-pressed', 'false');
        btn.dataset.reason = reason;
        btn.textContent = label ? t(label.key, label.fallback) : reason;
        var handler = function () {
            // Single-select, and tapping the selected chip clears it — the row
            // is optional and there has to be a way back out of it.
            var wasOn = btn.getAttribute('aria-pressed') === 'true';
            made.forEach(function (m) { m.el.setAttribute('aria-pressed', 'false'); });
            btn.setAttribute('aria-pressed', wasOn ? 'false' : 'true');
            onPick(wasOn ? null : reason);
        };
        btn.addEventListener('click', handler);
        wrap.appendChild(btn);
        made.push({ el: btn, handler: handler });
    });
    return made;
}

/**
 * Show or hide a "this round does not count" banner on a reveal screen.
 *
 * One helper for the phone and the admin browser; `dashboard.js` is a classic
 * script outside the module graph and carries its own copy.
 *
 * @param {Document} doc
 * @param {string} bannerId
 * @param {Object} data - REVEAL state payload (reads `round_voided`)
 */
export function renderVoidedBanner(doc, bannerId, data) {
    var banner = doc.getElementById(bannerId);
    if (!banner) return;
    banner.classList.toggle('hidden', !(data && data.round_voided));
}
