/**
 * Regression test for #1400: a rejected NoSleep enable() must reset
 * `_noSleepActive` to false so a later #1285 banner-tap (or visibilitychange
 * re-acquire) can re-attempt ns.enable() inside a trusted gesture.
 *
 * dashboard.js is a self-running IIFE (no exports, touches the DOM + registers
 * a service worker on load), so it can't be imported cleanly under vitest.
 * Instead we extract the `requestWakeLock` source straight from the served
 * file and evaluate it in a controlled scope with stubbed globals. This both
 * proves the fix and pins the exact source line so the bug can't silently
 * regress (the build then re-minifies it 1:1 into dashboard.min.js).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DASHBOARD_SRC = readFileSync(
    path.join(__dirname, '..', 'dashboard.js'),
    'utf8',
);

// Pull the `async function requestWakeLock() { ... }` body out of the IIFE so
// we can run it in isolation against injected dependencies.
function extractRequestWakeLockBody() {
    const start = DASHBOARD_SRC.indexOf('async function requestWakeLock()');
    expect(start).toBeGreaterThan(-1);
    const openBrace = DASHBOARD_SRC.indexOf('{', start);
    let depth = 0;
    let i = openBrace;
    for (; i < DASHBOARD_SRC.length; i++) {
        const c = DASHBOARD_SRC[i];
        if (c === '{') depth++;
        else if (c === '}') {
            depth--;
            if (depth === 0) break;
        }
    }
    // Body between the outermost braces (exclusive).
    return DASHBOARD_SRC.slice(openBrace + 1, i);
}

/**
 * Build a runnable copy of requestWakeLock with the closure variables and
 * helper functions it depends on injected via a factory. `enableImpl` controls
 * how the stubbed `ns.enable()` behaves (resolve / reject).
 */
function makeRequestWakeLock({ enableImpl, hasNativeWakeLock }) {
    const body = extractRequestWakeLockBody();
    const state = { noSleepActive: false, enableCalls: 0 };

    const navigator = hasNativeWakeLock
        ? { wakeLock: { request: () => Promise.reject(new Error('no gesture')) } }
        : {};

    const _ensureNoSleep = () => ({
        enable: () => {
            state.enableCalls++;
            return enableImpl();
        },
    });
    const _ensureMutedAutoplayVideo = () => null;

    // Reconstruct the closure: requestWakeLock reads/writes the outer
    // `_noSleepActive`, `_wakeLock`, and calls the helpers above. We expose
    // `_noSleepActive` through getter/setter-backed locals via `with`-free eval.
    // eslint-disable-next-line no-new-func
    const factory = new Function(
        'navigator',
        '_ensureNoSleep',
        '_ensureMutedAutoplayVideo',
        'getState',
        'setActive',
        `
        'use strict';
        let _wakeLock = null;
        let _noSleep = null;
        Object.defineProperty(globalThis, '__nsa', {
            configurable: true,
            get: () => getState().noSleepActive,
            set: (v) => setActive(v),
        });
        // Rewrite the closure's _noSleepActive accesses onto the shared proxy.
        const console = { debug() {}, warn() {}, error() {} };
        async function requestWakeLock() {
            ${body.replace(/_noSleepActive/g, 'globalThis.__nsa')}
        }
        return requestWakeLock;
        `,
    );

    const requestWakeLock = factory(
        navigator,
        _ensureNoSleep,
        _ensureMutedAutoplayVideo,
        () => state,
        (v) => { state.noSleepActive = v; },
    );
    return { requestWakeLock, state };
}

describe('#1400 dashboard requestWakeLock NoSleep flag reset', () => {
    beforeEach(() => {
        delete globalThis.__nsa;
    });

    it('still references _noSleepActive in the rejection handler (source pin)', () => {
        const body = extractRequestWakeLockBody();
        // The catch handler must reset the flag, not just log.
        const catchIdx = body.indexOf('Layer 2 enable promise rejected');
        expect(catchIdx).toBeGreaterThan(-1);
        const handler = body.slice(catchIdx - 200, catchIdx);
        expect(handler).toMatch(/_noSleepActive\s*=\s*false/);
    });

    it('resets _noSleepActive to false when enable() rejects async', async () => {
        let rejecter;
        const { requestWakeLock, state } = makeRequestWakeLock({
            hasNativeWakeLock: false,
            enableImpl: () => new Promise((_resolve, reject) => { rejecter = reject; }),
        });

        await requestWakeLock();
        // While the enable() promise is pending the flag guards re-entry.
        expect(state.noSleepActive).toBe(true);

        // Simulate iOS gesture-gated rejection of the init() enable() call.
        rejecter(new Error('NoSleep video play rejected — needs gesture'));
        await new Promise((r) => setTimeout(r, 0));

        // BUG #1400: without the fix the flag stayed true here, so the next
        // call short-circuited at `if (_noSleepActive) return false;`.
        expect(state.noSleepActive).toBe(false);
    });

    it('lets a subsequent banner-tap retry call ns.enable() again', async () => {
        let rejecter;
        const { requestWakeLock, state } = makeRequestWakeLock({
            hasNativeWakeLock: false,
            enableImpl: () => new Promise((_resolve, reject) => { rejecter = reject; }),
        });

        // 1) init()-style automatic call — rejected (no gesture on passive TV).
        await requestWakeLock();
        rejecter(new Error('needs gesture'));
        await new Promise((r) => setTimeout(r, 0));
        expect(state.enableCalls).toBe(1);
        expect(state.noSleepActive).toBe(false);

        // 2) #1285 banner tap re-runs requestWakeLock inside a trusted gesture.
        await requestWakeLock();
        // The one-tap recovery path must actually re-attempt enable() now.
        expect(state.enableCalls).toBe(2);
    });
});
