/**
 * Beatify Admin — in-flight guard for in-game controls (#1715).
 *
 * The in-game Next / Skip / Stop / Volume controls each fired
 * `sendAdminCommand` with no disable/in-flight flag, while start
 * (`adminState._startInFlight`) and rematch (`rematchInProgress`) are guarded.
 * A host double-tapping "Next" during a laggy transition sent `next_round`
 * twice and silently skipped a whole round with no undo.
 *
 * This owns a tiny guard registry: on a tap the command is sent once, the
 * associated buttons are disabled, and they re-enable on the next WS state
 * broadcast (`releaseAll`, wired into handleAdminStateUpdate) or a safety
 * timeout — mirroring the existing start/rematch guards.
 *
 * Pure + injectable (`doc`, `setTimeout`, `clearTimeout`) so it unit-tests
 * without a real DOM or wall-clock.
 */

/**
 * @param {object} [opts]
 * @param {Document} [opts.doc]            defaults to the global document
 * @param {function} [opts.setTimeout]     defaults to global setTimeout
 * @param {function} [opts.clearTimeout]   defaults to global clearTimeout
 */
export function createControlGuard(opts) {
    opts = opts || {};
    const doc = opts.doc || document;
    const setTimer = opts.setTimeout || setTimeout;
    const clearTimer = opts.clearTimeout || clearTimeout;
    const guards = Object.create(null); // guardKey -> { buttonIds, timer }

    function setDisabled(buttonIds, disabled) {
        buttonIds.forEach(function (id) {
            const btn = doc.getElementById(id);
            if (btn) btn.disabled = disabled;
        });
    }

    /** Release a single guard: clear its timer + re-enable its buttons. */
    function release(guardKey) {
        const g = guards[guardKey];
        if (!g) return;
        clearTimer(g.timer);
        setDisabled(g.buttonIds, false);
        delete guards[guardKey];
    }

    /** Release every active guard (called on each WS state broadcast). */
    function releaseAll() {
        Object.keys(guards).forEach(release);
    }

    /**
     * Attempt a guarded control tap.
     * @param {string}   guardKey  logical action key (shared buttons share a key)
     * @param {string[]} buttonIds element ids to disable while in flight
     * @param {function():boolean} send  performs the send; returns true iff it
     *        actually went out (WS open). A false return keeps the controls live.
     * @param {number}   timeoutMs safety re-enable window
     * @returns {boolean} true if the tap was accepted + sent, false if swallowed
     */
    function run(guardKey, buttonIds, send, timeoutMs) {
        if (guards[guardKey]) return false; // already in flight — swallow the double-tap
        const sent = send();
        if (!sent) return false; // WS down: nothing sent (error shown), keep controls enabled
        setDisabled(buttonIds, true);
        guards[guardKey] = {
            buttonIds: buttonIds,
            timer: setTimer(function () { release(guardKey); }, timeoutMs)
        };
        return true;
    }

    return {
        run: run,
        release: release,
        releaseAll: releaseAll,
        /** Test-only: inspect active guard keys. */
        _activeKeys: function () { return Object.keys(guards); }
    };
}
