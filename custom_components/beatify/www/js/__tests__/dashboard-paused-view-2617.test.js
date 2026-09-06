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
 * dashboard.js is a DOM-coupled IIFE with no exports and the vitest env is
 * `node` without jsdom, so — as in dashboard-2130-end-stage.test.js — the
 * guard reads the shipped source from disk.
 *
 * The second assertion is the one that matters going forward: it does not
 * hard-code `data`, it requires every phase branch to hand the SAME
 * identifier to its renderer. A future rename of the parameter keeps passing;
 * a single branch drifting off it fails, whatever the name.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = readFileSync(join(__dirname, '..', 'dashboard.js'), 'utf8');
const MIN = readFileSync(join(__dirname, '..', 'dashboard.min.js'), 'utf8');

/** The `switch (phase)` block that dispatches the phase renderers. */
function phaseSwitch() {
    const start = JS.indexOf("case 'LOBBY':");
    expect(start, "the phase switch should still start at case 'LOBBY'").toBeGreaterThan(-1);
    const end = JS.indexOf("Unknown phase", start);
    expect(end, 'the phase switch should still end at the default branch').toBeGreaterThan(start);
    return JS.slice(start, end);
}

describe('#2617 dashboard phase dispatch', () => {
    it('hands the PAUSED branch the same object as every other branch', () => {
        expect(phaseSwitch()).toMatch(/renderPausedView\(data\)/);
    });

    it('passes one and the same identifier to every phase renderer', () => {
        const args = [...phaseSwitch().matchAll(/render(\w+)View\((\w+)\)/g)].map((m) => ({
            view: m[1],
            arg: m[2],
        }));
        // Lobby, Playing, Reveal, End, Paused — a shrinking list would mean a
        // branch lost its renderer, which this guard should also catch.
        expect(args.length).toBeGreaterThanOrEqual(5);
        const distinct = [...new Set(args.map((a) => a.arg))];
        expect(distinct, `phase renderers disagree on their argument: ${JSON.stringify(args)}`).toHaveLength(1);
    });

    it('ships the fix in the bundle, not only in the source', () => {
        // The bundle is what the TV loads. #2617 was present in both.
        expect(MIN).not.toMatch(/case"PAUSED":[^;]*\(state\)/);
    });
});
