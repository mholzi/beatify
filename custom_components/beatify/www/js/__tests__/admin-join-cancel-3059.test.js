/**
 * #3059: Cancel on the admin join modal must also cancel the pending
 * "join once the socket opens" wait. Before, the interval was a local nobody
 * could clear, so the host was joined anyway when the socket reconnected.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { startJoinWait, cancelJoinWait } from '../admin/join-wait.js';

let open;
let visible;
let onReady;
let onTimeout;

function arm() {
    startJoinWait({ isOpen: () => open, isModalVisible: () => visible, onReady, onTimeout });
}

beforeEach(() => {
    vi.useFakeTimers();
    open = false;
    visible = true;
    onReady = vi.fn();
    onTimeout = vi.fn();
});

afterEach(() => {
    cancelJoinWait();
    vi.useRealTimers();
});

describe('join wait (#3059)', () => {
    it('joins once the socket opens while the modal is shown', () => {
        arm();
        vi.advanceTimersByTime(500);
        open = true;
        vi.advanceTimersByTime(200);
        expect(onReady).toHaveBeenCalledTimes(1);
    });

    it('does not join after cancelJoinWait (Cancel / backdrop / Escape)', () => {
        arm();
        vi.advanceTimersByTime(500);
        cancelJoinWait();
        open = true;
        vi.advanceTimersByTime(1000);
        expect(onReady).not.toHaveBeenCalled();
    });

    it('bails out when the modal is hidden, even without an explicit cancel', () => {
        arm();
        visible = false;
        open = true;
        vi.advanceTimersByTime(1000);
        expect(onReady).not.toHaveBeenCalled();
    });

    it('re-arming replaces the earlier wait: exactly one join', () => {
        arm();
        arm();
        open = true;
        vi.advanceTimersByTime(300);
        expect(onReady).toHaveBeenCalledTimes(1);
    });

    it('times out after 20 s', () => {
        arm();
        vi.advanceTimersByTime(20200);
        expect(onTimeout).toHaveBeenCalledTimes(1);
        expect(onReady).not.toHaveBeenCalled();
    });
});

describe('admin.js wiring', () => {
    const src = readFileSync(
        join(dirname(fileURLToPath(import.meta.url)), '..', 'admin.js'), 'utf8');

    it('closeAdminJoinModal cancels the wait', () => {
        const body = src.slice(src.indexOf('function closeAdminJoinModal()'));
        expect(body.slice(0, body.indexOf('\n}\n'))).toContain('cancelJoinWait()');
    });

    it('handleAdminJoin uses the cancellable wait, not a bare setInterval', () => {
        const body = src.slice(src.indexOf('function handleAdminJoin()'));
        const fn = body.slice(0, body.indexOf('\n}\n'));
        expect(fn).toContain('startJoinWait(');
        expect(fn).not.toContain('setInterval(');
    });
});
