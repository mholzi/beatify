/**
 * Unit tests for createRenderCoalescer (admin/util.js) — the #1584 fix for
 * "Throttle / diff the full re-render on every WS broadcast".
 *
 * The admin view rebuilt leaderboard + result cards + reveal inside
 * handleAdminStateUpdate on EVERY `state` broadcast. createRenderCoalescer
 * wraps that heavy render so a burst collapses into one paint per frame, the
 * LATEST payload of the burst is always the one rendered (the final state is
 * never dropped), and a byte-identical payload is skipped entirely.
 *
 * The scheduler is injected (a manual frame queue) so the tests are
 * deterministic and don't depend on requestAnimationFrame timing.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import {
    createRenderCoalescer,
    adminStateEqual,
    ADMIN_STATE_VOLATILE_KEYS,
} from '../admin/util.js';

// A manual frame scheduler: schedule() queues the callback; frame() runs all
// callbacks queued so far (one animation frame).
function makeFrameScheduler() {
    let queue = [];
    return {
        schedule: (cb) => { queue.push(cb); return queue.length; },
        frame: () => {
            const run = queue;
            queue = [];
            run.forEach((cb) => cb());
        },
        pending: () => queue.length,
    };
}

describe('createRenderCoalescer', () => {
    let calls;
    let render;
    let sched;

    beforeEach(() => {
        calls = [];
        render = (data) => calls.push(data);
        sched = makeFrameScheduler();
    });

    it('coalesces a burst into a single render on the next frame', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        push({ phase: 'PLAYING', round: 1 });
        push({ phase: 'PLAYING', round: 2 });
        push({ phase: 'PLAYING', round: 3 });

        // Nothing rendered yet — the burst is still queued for one frame.
        expect(calls).toHaveLength(0);
        expect(sched.pending()).toBe(1); // only ONE flush scheduled for the burst

        sched.frame();

        // Exactly one render, and it is the LATEST payload (final state wins).
        expect(calls).toHaveLength(1);
        expect(calls[0]).toEqual({ phase: 'PLAYING', round: 3 });
    });

    it('always renders the final state of a burst (never drops the last update)', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        // Simulate several separate bursts across frames.
        push({ round: 1 });
        push({ round: 2 });
        sched.frame();
        push({ round: 3 });
        push({ round: 4 });
        push({ round: 5 });
        sched.frame();

        // One render per frame, each the last payload pushed before that frame.
        expect(calls).toEqual([{ round: 2 }, { round: 5 }]);
    });

    it('schedules a fresh frame for an update that arrives after a flush', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        push({ round: 1 });
        sched.frame();
        expect(calls).toEqual([{ round: 1 }]);

        // A later, distinct broadcast must paint on its own frame.
        push({ round: 2 });
        expect(sched.pending()).toBe(1);
        sched.frame();
        expect(calls).toEqual([{ round: 1 }, { round: 2 }]);
    });

    it('skips the repaint when the payload is unchanged (dirty-check)', () => {
        const isEqual = (a, b) => JSON.stringify(a) === JSON.stringify(b);
        const push = createRenderCoalescer(render, { schedule: sched.schedule, isEqual });

        push({ phase: 'REVEAL', scores: [1, 2, 3] });
        sched.frame();
        expect(calls).toHaveLength(1);

        // Identical content (fresh object, same bytes) → no new frame, no render.
        push({ phase: 'REVEAL', scores: [1, 2, 3] });
        expect(sched.pending()).toBe(0);
        sched.frame();
        expect(calls).toHaveLength(1);

        // A genuine change DOES render.
        push({ phase: 'REVEAL', scores: [1, 2, 4] });
        sched.frame();
        expect(calls).toHaveLength(2);
        expect(calls[1]).toEqual({ phase: 'REVEAL', scores: [1, 2, 4] });
    });

    it('without isEqual, an identical payload still repaints (no diff configured)', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        push({ a: 1 });
        sched.frame();
        push({ a: 1 });
        sched.frame();

        expect(calls).toHaveLength(2);
    });

    it('flush() renders a pending payload synchronously', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        push({ round: 7 });
        expect(calls).toHaveLength(0);

        push.flush();
        expect(calls).toEqual([{ round: 7 }]);

        // The already-run frame becomes a no-op (nothing left pending).
        sched.frame();
        expect(calls).toHaveLength(1);
    });

    it('cancel() drops a pending render without painting', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule });

        push({ round: 9 });
        push.cancel();
        sched.frame();

        expect(calls).toHaveLength(0);
    });
});

// #1659: the admin dirty-check must ignore the server's volatile timestamp keys
// so a broadcast that ticks only `deadline` / `reveal_started_at` (both in the
// server's _now() units, consumed by client-side countdown timers, not the DOM
// render) still dirty-skips instead of forcing a wasted full repaint.
describe('adminStateEqual (#1659 volatile-key projection)', () => {
    let calls;
    let render;
    let sched;

    beforeEach(() => {
        calls = [];
        render = (data) => calls.push(data);
        sched = makeFrameScheduler();
    });

    it('lists the server timestamp keys as volatile', () => {
        expect(ADMIN_STATE_VOLATILE_KEYS).toContain('deadline');
        expect(ADMIN_STATE_VOLATILE_KEYS).toContain('reveal_started_at');
    });

    it('treats two payloads that differ ONLY in volatile fields as equal (PLAYING deadline)', () => {
        const a = { phase: 'PLAYING', round: 3, song: { title: 'x' }, deadline: 1000.0 };
        const b = { phase: 'PLAYING', round: 3, song: { title: 'x' }, deadline: 1234.5 };
        expect(adminStateEqual(a, b)).toBe(true);
    });

    it('treats two payloads that differ ONLY in reveal_started_at as equal (REVEAL)', () => {
        const a = { phase: 'REVEAL', round: 2, reveal_started_at: 1700000000000 };
        const b = { phase: 'REVEAL', round: 2, reveal_started_at: 1700000009999 };
        expect(adminStateEqual(a, b)).toBe(true);
    });

    it('treats a payload with a real change as UNEQUAL even when volatile fields match', () => {
        const a = { phase: 'PLAYING', round: 3, song: { title: 'x' }, deadline: 1000 };
        const b = { phase: 'PLAYING', round: 4, song: { title: 'x' }, deadline: 1000 };
        expect(adminStateEqual(a, b)).toBe(false);
    });

    it('treats a real change AND a volatile change together as UNEQUAL', () => {
        const a = { phase: 'PLAYING', round: 3, deadline: 1000 };
        const b = { phase: 'PLAYING', round: 4, deadline: 2000 };
        expect(adminStateEqual(a, b)).toBe(false);
    });

    it('is a no-op projection when neither payload carries a volatile key (LOBBY)', () => {
        expect(adminStateEqual({ phase: 'LOBBY', join_url: 'u' }, { phase: 'LOBBY', join_url: 'u' })).toBe(true);
        expect(adminStateEqual({ phase: 'LOBBY', join_url: 'u' }, { phase: 'LOBBY', join_url: 'v' })).toBe(false);
    });

    it('does not mutate the input payloads', () => {
        const a = { phase: 'PLAYING', round: 1, deadline: 500 };
        const b = { phase: 'PLAYING', round: 1, deadline: 900 };
        adminStateEqual(a, b);
        expect(a).toHaveProperty('deadline', 500);
        expect(b).toHaveProperty('deadline', 900);
    });

    it('drives the coalescer dirty-skip: a deadline-only tick does not repaint', () => {
        const push = createRenderCoalescer(render, { schedule: sched.schedule, isEqual: adminStateEqual });

        push({ phase: 'PLAYING', round: 1, deadline: 1000 });
        sched.frame();
        expect(calls).toHaveLength(1);

        // Same logical state, deadline re-stamped → skip (no frame, no render).
        push({ phase: 'PLAYING', round: 1, deadline: 1500 });
        expect(sched.pending()).toBe(0);
        sched.frame();
        expect(calls).toHaveLength(1);

        // A genuine round change DOES repaint.
        push({ phase: 'PLAYING', round: 2, deadline: 1500 });
        sched.frame();
        expect(calls).toHaveLength(2);
    });
});
