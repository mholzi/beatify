/**
 * #2617 — the TV froze instead of showing the Paused screen.
 *
 * `dashboard.js` dispatches on the game phase inside one function whose
 * parameter is named `data`. Five of the six branches passed it on; the
 * PAUSED branch passed `state`, which exists nowhere in scope. The file
 * declares `'use strict'`, so reading an undeclared identifier throws a
 * ReferenceError — and it threw BEFORE `showView('dashboard-paused')`, which
 * is why the screen never switched and the TV sat on the previous round with
 * a frozen timer. The whole pause mechanism shipped in 4.4.2 (#2544, #2549,
 * #2551, #2552) was invisible in the room because of it, and the message from
 * #2569 was never displayed.
 *
 * #2701: this used to be two regexes over `dashboard.js` plus one over
 * `dashboard.min.js`. The dispatcher is run for real now — compiled out of the
 * shipped file in strict mode, exactly as the browser compiles it — so the
 * ReferenceError reproduces instead of being described. That also removes the
 * minified assertion: `npm run build:check` already rebuilds every bundle and
 * fails on any drift from its source, so a test grepping terser's output only
 * duplicated that guarantee while breaking whenever terser changes its mind.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');

/** Every phase the dispatcher must handle, with the renderer it belongs to. */
const PHASES = [
    ['LOBBY', 'renderLobbyView', 'dashboard-lobby'],
    ['PLAYING', 'renderPlayingView', 'dashboard-playing'],
    ['REVEAL', 'renderRevealView', 'dashboard-reveal'],
    ['END', 'renderEndView', 'dashboard-end'],
    ['PAUSED', 'renderPausedView', 'dashboard-paused'],
];

/**
 * Run the shipped phase dispatcher for one payload.
 *
 * Every renderer, `showView` and the countdown are stubs that record what they
 * were handed. Nothing else is provided on purpose: an identifier the
 * dispatcher reads and this scope does not name throws a ReferenceError, which
 * is #2617 itself.
 */
function dispatch(data) {
    const calls = [];
    const scope = {
        utils: { hydrateLeaderboard: (lb) => lb },
        showView: (view) => calls.push({ fn: 'showView', arg: view }),
        stopCountdown: () => calls.push({ fn: 'stopCountdown' }),
        debug: () => calls.push({ fn: 'debug' }),
    };
    for (const [, renderer] of PHASES) {
        scope[renderer] = (arg) => calls.push({ fn: renderer, arg });
    }
    evaluate(
        declaration(DASHBOARD, '_applyStateRender', 'dashboard.js'),
        '_applyStateRender',
        scope,
    )(data);
    return calls;
}

describe('#2617 dashboard phase dispatch', () => {
    it('shows the Paused screen and renders it', () => {
        // The bug in one line: before the fix this call threw a ReferenceError
        // on `state` and neither entry below was ever reached.
        const calls = dispatch({ phase: 'PAUSED', game_id: 'g1', pause_reason: 'speaker' });
        expect(calls.map((c) => c.fn)).toContain('renderPausedView');
        expect(calls).toContainEqual({ fn: 'showView', arg: 'dashboard-paused' });
    });

    it('hands the paused renderer the payload, with the pause reason intact', () => {
        const data = { phase: 'PAUSED', game_id: 'g1', pause_reason: 'media_player_error' };
        const call = dispatch(data).find((c) => c.fn === 'renderPausedView');
        // #2552 reads `pause_reason` off this object; an empty stand-in would
        // put "the host disconnected" on a speaker failure.
        expect(call.arg.pause_reason).toBe('media_player_error');
    });

    it.each(PHASES)('routes %s to %s and shows %s', (phase, renderer, view) => {
        const calls = dispatch({ phase, game_id: 'g1' });
        expect(calls.map((c) => c.fn)).toContain(renderer);
        expect(calls).toContainEqual({ fn: 'showView', arg: view });
    });

    it('gives every phase renderer the same payload', () => {
        // Rename-proof by construction: it does not care what the parameter is
        // called, only that no branch drifts off it onto something else.
        for (const [phase, renderer] of PHASES) {
            const data = { phase, game_id: 'g1', marker: phase };
            const call = dispatch(data).find((c) => c.fn === renderer);
            expect(call, `${phase} rendered nothing`).toBeTruthy();
            expect(call.arg.marker, `${phase} was handed a different object`).toBe(phase);
        }
    });

    it('leaves an unknown phase to the default branch without throwing', () => {
        const calls = dispatch({ phase: 'TELEPORTING', game_id: 'g1' });
        expect(calls.map((c) => c.fn)).toEqual(['debug']);
    });
});
