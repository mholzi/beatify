/**
 * #3026 — the TV never left the old game.
 *
 * "Start New Game" (admin dismiss) and the REST end-game path broadcast
 * `{type: 'game_ended'}` and nothing else once the game is torn down. A TV
 * opened with no game running gets `{type: 'error', code: 'GAME_NOT_STARTED'}`
 * back for its `get_state`. `handleServerMessage` ignored both, so the TV sat
 * on the old podium, or on the loading spinner. Both now route to the existing
 * `dashboard-no-game` view, and the next game's LOBBY state switches it back.
 *
 * The shipped functions are compiled out of `dashboard.js` and run against
 * stubs (see helpers/js-source.js).
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');
const src = (name) => declaration(DASHBOARD, name, 'dashboard.js');

/**
 * Build the shipped message handler + no-game helper + render coalescer with a
 * synchronous scheduler. `_applyStateRender` is replaced by a stub that records
 * the payload and shows the phase's view, which is all these tests need.
 */
function makeTv() {
    const calls = [];
    const renders = [];
    let queued = null;
    const scope = {
        debug: () => {},
        showView: (view) => calls.push({ fn: 'showView', arg: view }),
        stopCountdown: () => calls.push({ fn: 'stopCountdown' }),
        showFloatingReaction: () => {},
        handleMetadataUpdate: () => {},
        setSongStoppedChip: () => {},
        handleStateUpdate: (data) => scope._scheduleRender(data),
        songStoppedRound: null,
        lastRenderedRound: null,
        _scheduleRender: null,
    };
    const createRenderCoalescer = evaluate(src('createRenderCoalescer'), 'createRenderCoalescer');
    scope._scheduleRender = createRenderCoalescer(
        (data) => {
            renders.push(data);
            calls.push({ fn: 'showView', arg: 'dashboard-' + data.phase.toLowerCase() });
        },
        {
            schedule: (cb) => { queued = cb; },
            isEqual: (a, b) => JSON.stringify(a) === JSON.stringify(b),
        },
    );
    const handle = evaluate(
        [src('showNoGameView'), src('handleServerMessage')],
        'handleServerMessage',
        scope,
    );
    const flush = () => { const cb = queued; queued = null; if (cb) cb(); };
    const lastView = () => calls.filter((c) => c.fn === 'showView').map((c) => c.arg).pop();
    return { handle, flush, calls, renders, lastView };
}

describe('#3026 TV handles the end of a game', () => {
    it('leaves the podium for "No active game" on game_ended', () => {
        const tv = makeTv();
        tv.handle({ type: 'state', phase: 'END', game_id: 'g1' });
        tv.flush();
        expect(tv.lastView()).toBe('dashboard-end');

        tv.handle({ type: 'game_ended' });
        expect(tv.lastView()).toBe('dashboard-no-game');
        expect(tv.calls.map((c) => c.fn)).toContain('stopCountdown');
    });

    it('leaves the spinner for "No active game" when the server has no game', () => {
        const tv = makeTv();
        tv.handle({ type: 'error', code: 'GAME_NOT_STARTED', message: 'No active game' });
        expect(tv.lastView()).toBe('dashboard-no-game');
        expect(tv.calls.map((c) => c.fn)).toContain('stopCountdown');
    });

    it('ignores other error frames', () => {
        const tv = makeTv();
        tv.handle({ type: 'error', code: 'INVALID_ACTION', message: 'nope' });
        expect(tv.calls).toEqual([]);
    });

    it('a state queued before game_ended does not repaint the old game', () => {
        const tv = makeTv();
        tv.handle({ type: 'state', phase: 'END', game_id: 'g1' });
        tv.handle({ type: 'game_ended' });
        tv.flush();
        expect(tv.renders).toEqual([]);
        expect(tv.lastView()).toBe('dashboard-no-game');
    });

    it('switches back when the next game starts', () => {
        const tv = makeTv();
        tv.handle({ type: 'error', code: 'GAME_NOT_STARTED', message: 'No active game' });
        tv.handle({ type: 'state', phase: 'LOBBY', game_id: 'g2' });
        tv.flush();
        expect(tv.lastView()).toBe('dashboard-lobby');
    });

    it('repaints even a state identical to the last painted frame', () => {
        // The coalescer skips a payload equal to what is on screen. After the
        // no-game view took over, "on screen" is no longer that payload.
        const tv = makeTv();
        const lobby = { type: 'state', phase: 'LOBBY', game_id: 'g1' };
        tv.handle(lobby);
        tv.flush();
        tv.handle({ type: 'game_ended' });
        tv.handle(lobby);
        tv.flush();
        expect(tv.renders).toHaveLength(2);
        expect(tv.lastView()).toBe('dashboard-lobby');
    });
});
