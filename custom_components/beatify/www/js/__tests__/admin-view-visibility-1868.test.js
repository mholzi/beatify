/**
 * #1868 — the admin must never boot into an empty page.
 *
 * Reported symptom: after completing the wizard and reloading, both roots stayed
 * hidden. `#wizard-root` and `#home-view` are each invisible by default —
 * `#home-view` needs `body.home-mode`, `#wizard-root` needs `body.wizard-active`
 * — so "neither branch ran" renders a page with just the logo, two header
 * buttons and the version footer, and no way back except clearing localStorage.
 *
 * `adminHasVisibleView` is the predicate the boot path's recovery guard uses.
 *
 * The suite runs on `environment: 'node'` with no jsdom, so this builds the
 * minimal fake document the predicate actually touches — same approach as
 * modal-focus-trap.test.js.
 */

import { describe, it, expect } from 'vitest';
import { adminHasVisibleView } from '../admin/util.js';

const PHASE_SECTIONS = [
    'admin-playing-section',
    'admin-reveal-section',
    'admin-end-section',
];

function makeClassList(initial = []) {
    const set = new Set(initial);
    return {
        contains: (c) => set.has(c),
        add: (c) => set.add(c),
        remove: (c) => set.delete(c),
    };
}

/**
 * A completed-wizard admin page with nothing routed yet — the reported state.
 * All three phase sections exist in the DOM at all times and carry `hidden`.
 */
function makeDoc({ bodyClasses = [], visibleSections = [] } = {}) {
    const els = {
        'home-view': { classList: makeClassList(['home-view', 'hidden']) },
        'wizard-root': { classList: makeClassList([]) },
    };
    for (const id of PHASE_SECTIONS) {
        els[id] = {
            classList: makeClassList(visibleSections.includes(id) ? [] : ['hidden']),
        };
    }
    return {
        body: { classList: makeClassList(bodyClasses) },
        getElementById: (id) => els[id] || null,
    };
}

describe('adminHasVisibleView (#1868)', () => {
    it('is false for the exact dead end that was reported', () => {
        // Wizard done, no game, neither body class set — header and footer
        // render, everything else is hidden.
        expect(adminHasVisibleView(makeDoc())).toBe(false);
    });

    it('is true once the home view is entered', () => {
        expect(adminHasVisibleView(makeDoc({ bodyClasses: ['home-mode'] }))).toBe(true);
    });

    it('is true while the wizard has the screen', () => {
        expect(adminHasVisibleView(makeDoc({ bodyClasses: ['wizard-active'] }))).toBe(true);
    });

    it.each(PHASE_SECTIONS)('is true when %s is showing', (id) => {
        expect(adminHasVisibleView(makeDoc({ visibleSections: [id] }))).toBe(true);
    });

    it('is not fooled by phase sections that exist but are hidden', () => {
        const doc = makeDoc();
        for (const id of PHASE_SECTIONS) {
            expect(doc.getElementById(id)).not.toBeNull();
        }
        expect(adminHasVisibleView(doc)).toBe(false);
    });

    it('is not fooled by home-view merely losing its hidden class', () => {
        // `.home-view { display: none }` is unconditional; only body.home-mode
        // makes it flex. Removing `hidden` alone still renders nothing, which
        // is exactly why the predicate keys on the body class instead.
        const doc = makeDoc();
        doc.getElementById('home-view').classList.remove('hidden');
        expect(adminHasVisibleView(doc)).toBe(false);
    });

    it('survives a document with no body', () => {
        expect(adminHasVisibleView({ body: null })).toBe(false);
        expect(adminHasVisibleView(null)).toBe(false);
        expect(adminHasVisibleView(undefined)).toBe(false);
    });
});

describe('recovery ordering (#1868)', () => {
    // Mirrors ensureAdminViewVisible in admin.js: home view first, wizard only
    // if that failed to produce a view.
    function recover(win, doc) {
        if (adminHasVisibleView(doc)) return 'noop';
        try { win.BeatifyHome?.enter(); } catch { /* fall through to the wizard */ }
        if (adminHasVisibleView(doc)) return 'home';
        try { win.BeatifyWizard?.show(1); } catch { /* nothing left to try */ }
        return adminHasVisibleView(doc) ? 'wizard' : 'failed';
    }

    it('does nothing when a view is already up', () => {
        const doc = makeDoc({ bodyClasses: ['home-mode'] });
        const win = {
            BeatifyHome: { enter: () => { throw new Error('must not be called'); } },
        };
        expect(recover(win, doc)).toBe('noop');
    });

    it('prefers the home view — reopening the wizard is more disruptive', () => {
        const doc = makeDoc();
        const win = {
            BeatifyHome: { enter: () => doc.body.classList.add('home-mode') },
            BeatifyWizard: { show: () => { throw new Error('must not be called'); } },
        };
        expect(recover(win, doc)).toBe('home');
    });

    it('falls back to the wizard when entering home throws', () => {
        const doc = makeDoc();
        const win = {
            BeatifyHome: { enter: () => { throw new Error('boom'); } },
            BeatifyWizard: { show: () => doc.body.classList.add('wizard-active') },
        };
        expect(recover(win, doc)).toBe('wizard');
    });

    it('falls back to the wizard when entering home silently shows nothing', () => {
        // The nastier variant: no exception, just no view. A try/catch alone
        // would have called this a success and left the page empty.
        const doc = makeDoc();
        const win = {
            BeatifyHome: { enter: () => {} },
            BeatifyWizard: { show: () => doc.body.classList.add('wizard-active') },
        };
        expect(recover(win, doc)).toBe('wizard');
    });

    it('reports failure rather than throwing when both recoveries fail', () => {
        const doc = makeDoc();
        const win = {
            BeatifyHome: { enter: () => { throw new Error('boom'); } },
            BeatifyWizard: { show: () => { throw new Error('boom'); } },
        };
        expect(() => recover(win, doc)).not.toThrow();
        expect(recover(win, doc)).toBe('failed');
    });

    it('tolerates the globals being absent entirely', () => {
        expect(() => recover({}, makeDoc())).not.toThrow();
    });
});
