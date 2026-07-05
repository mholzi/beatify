/**
 * #1715: in-flight guard for in-game admin controls (Next/Skip/Stop/Volume).
 *
 * Regression net for the double-click bug: a host double-tapping "Next" during
 * a laggy transition sent `next_round` twice and skipped a whole round. The
 * guard must swallow the second tap until either the next WS state broadcast
 * (releaseAll) or the safety timeout re-enables the control.
 *
 * The guard is pure + injectable (doc / setTimeout / clearTimeout), so these
 * tests run against a fake DOM registry and a fake clock — no jsdom needed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createControlGuard } from '../admin/control-guard.js';

function makeDoc() {
    const buttons = {};
    return {
        _add(id) { buttons[id] = { id, disabled: false }; return buttons[id]; },
        getElementById(id) { return buttons[id] || null; },
    };
}

describe('createControlGuard (#1715)', () => {
    let doc, guard, timers;

    beforeEach(() => {
        doc = makeDoc();
        timers = [];
        guard = createControlGuard({
            doc,
            setTimeout: (fn, ms) => { const t = { fn, ms }; timers.push(t); return t; },
            clearTimeout: (t) => { timers = timers.filter((x) => x !== t); },
        });
    });

    it('sends once and disables the button on first tap', () => {
        doc._add('admin-next-round');
        const send = vi.fn(() => true);

        const accepted = guard.run('next_round', ['admin-next-round'], send, 4000);

        expect(accepted).toBe(true);
        expect(send).toHaveBeenCalledTimes(1);
        expect(doc.getElementById('admin-next-round').disabled).toBe(true);
    });

    it('swallows a double-tap while in flight (does NOT skip a round)', () => {
        doc._add('admin-next-round');
        const send = vi.fn(() => true);

        guard.run('next_round', ['admin-next-round'], send, 4000);
        const second = guard.run('next_round', ['admin-next-round'], send, 4000);

        expect(second).toBe(false);
        expect(send).toHaveBeenCalledTimes(1); // second tap never reached the wire
    });

    it('re-enables + accepts again after a WS state broadcast (releaseAll)', () => {
        doc._add('admin-next-round');
        const send = vi.fn(() => true);

        guard.run('next_round', ['admin-next-round'], send, 4000);
        guard.releaseAll(); // simulates handleAdminStateUpdate()

        expect(doc.getElementById('admin-next-round').disabled).toBe(false);
        expect(guard._activeKeys()).toEqual([]);

        const again = guard.run('next_round', ['admin-next-round'], send, 4000);
        expect(again).toBe(true);
        expect(send).toHaveBeenCalledTimes(2);
    });

    it('re-enables via the safety timeout when no broadcast arrives', () => {
        doc._add('admin-stop-song');
        const send = vi.fn(() => true);

        guard.run('stop_song', ['admin-stop-song'], send, 4000);
        expect(doc.getElementById('admin-stop-song').disabled).toBe(true);

        // fire the scheduled safety timeout
        expect(timers).toHaveLength(1);
        timers[0].fn();

        expect(doc.getElementById('admin-stop-song').disabled).toBe(false);
        expect(guard._activeKeys()).toEqual([]);
    });

    it('does NOT engage the guard when the send fails (WS down)', () => {
        doc._add('admin-next-round');
        const send = vi.fn(() => false); // sendAdminCommand returned false

        const accepted = guard.run('next_round', ['admin-next-round'], send, 4000);

        expect(accepted).toBe(false);
        expect(doc.getElementById('admin-next-round').disabled).toBe(false); // stays live
        expect(guard._activeKeys()).toEqual([]);
    });

    it('disables every button that shares a guard key (Next + Skip)', () => {
        doc._add('admin-next-round');
        doc._add('admin-skip-round');
        const send = vi.fn(() => true);

        guard.run('next_round', ['admin-next-round', 'admin-skip-round'], send, 4000);

        expect(doc.getElementById('admin-next-round').disabled).toBe(true);
        expect(doc.getElementById('admin-skip-round').disabled).toBe(true);

        // a tap on the sibling Skip button (same key) is also swallowed
        const second = guard.run('next_round', ['admin-next-round', 'admin-skip-round'], send, 4000);
        expect(second).toBe(false);
        expect(send).toHaveBeenCalledTimes(1);
    });

    it('keeps independent controls (volume up/down) on separate keys', () => {
        doc._add('admin-vol-up');
        doc._add('admin-vol-down');
        const send = vi.fn(() => true);

        guard.run('vol_up', ['admin-vol-up'], send, 300);
        const downAccepted = guard.run('vol_down', ['admin-vol-down'], send, 300);

        expect(downAccepted).toBe(true); // different key → not blocked by vol_up
        expect(send).toHaveBeenCalledTimes(2);
        expect(guard._activeKeys().sort()).toEqual(['vol_down', 'vol_up']);
    });
});
