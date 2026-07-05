/**
 * #1716 — accessible focus management for aria-modal dialogs.
 *
 * showConfirmModal (and the app's other confirm/action dialogs) used to open
 * with classList.remove('hidden') but never moved focus in, never trapped Tab,
 * and had no Escape handler — focus stayed on the trigger behind the backdrop.
 * createModalFocusTrap centralises the fix: on activate() it moves focus into
 * the dialog, traps Tab within .modal-content and closes on Escape; deactivate()
 * restores focus to the pre-open element.
 *
 * These tests drive the real helper with a minimal fake DOM (the suite runs in
 * a Node environment with no browser), tracking activeElement as .focus() moves
 * it — exactly the contract the trap depends on.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---- browser-global stubs (must exist before player-utils is imported) ------
// player-utils.js has import-time side effects (view lookups, an AnimationUtils
// IIFE that probes matchMedia + navigator). Stub just enough so the real module
// loads; createModalFocusTrap itself is DOM-injectable (reads modal.ownerDocument).
global.window = {
    BeatifyUtils: { t: (k) => k, debug: () => {} },
    location: { search: '' },
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
};
Object.defineProperty(global, 'navigator', {
    value: { hardwareConcurrency: 8, deviceMemory: 8, userAgent: 'node' },
    configurable: true, writable: true,
});
global.document = { getElementById: () => null };

const { createModalFocusTrap } = await import('../player-utils.js');

function makeDoc() {
    const listeners = {};
    return {
        activeElement: null,
        addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
        removeEventListener(type, fn) {
            listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
        },
        _fire(type, ev) { (listeners[type] || []).slice().forEach((f) => f(ev)); },
        _count(type) { return (listeners[type] || []).length; },
    };
}

function makeButton(doc, id) {
    const b = { id, disabled: false, _attrs: {} };
    b.getAttribute = (k) => (k in b._attrs ? b._attrs[k] : null);
    b.setAttribute = (k, v) => { b._attrs[k] = v; };
    b.focus = () => { doc.activeElement = b; };
    return b;
}

function setup() {
    const doc = makeDoc();
    const cancelBtn = makeButton(doc, 'confirm-modal-no');
    const confirmBtn = makeButton(doc, 'confirm-modal-yes');
    const trigger = makeButton(doc, 'leave-btn');
    const content = { querySelectorAll: () => [cancelBtn, confirmBtn] };
    const modal = {
        ownerDocument: doc,
        querySelector: (sel) => (sel === '.modal-content' ? content : null),
    };
    return { doc, cancelBtn, confirmBtn, trigger, modal };
}

describe('createModalFocusTrap (#1716)', () => {
    let ctx;
    beforeEach(() => { ctx = setup(); });

    it('moves focus to the requested initial element on activate', () => {
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn });
        expect(ctx.doc.activeElement).toBe(ctx.cancelBtn);
    });

    it('traps Tab: wraps from the last focusable back to the first', () => {
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn });
        ctx.doc.activeElement = ctx.confirmBtn; // last element focused
        const preventDefault = vi.fn();
        ctx.doc._fire('keydown', { key: 'Tab', shiftKey: false, preventDefault });
        expect(preventDefault).toHaveBeenCalled();
        expect(ctx.doc.activeElement).toBe(ctx.cancelBtn); // wrapped to first
    });

    it('traps Shift+Tab: wraps from the first focusable to the last', () => {
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn }); // first element focused
        const preventDefault = vi.fn();
        ctx.doc._fire('keydown', { key: 'Tab', shiftKey: true, preventDefault });
        expect(preventDefault).toHaveBeenCalled();
        expect(ctx.doc.activeElement).toBe(ctx.confirmBtn); // wrapped to last
    });

    it('calls onEscape when Escape is pressed', () => {
        const onEscape = vi.fn();
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn, onEscape });
        const preventDefault = vi.fn();
        ctx.doc._fire('keydown', { key: 'Escape', preventDefault });
        expect(onEscape).toHaveBeenCalledTimes(1);
        expect(preventDefault).toHaveBeenCalled();
    });

    it('restores focus to the pre-open element and unbinds on deactivate', () => {
        ctx.doc.activeElement = ctx.trigger; // focus held by the trigger before open
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn });
        expect(ctx.doc.activeElement).toBe(ctx.cancelBtn);
        expect(ctx.doc._count('keydown')).toBe(1);

        trap.deactivate();
        expect(ctx.doc.activeElement).toBe(ctx.trigger); // focus restored
        expect(ctx.doc._count('keydown')).toBe(0);       // handler removed
    });

    it('ignores non-Tab / non-Escape keys', () => {
        const onEscape = vi.fn();
        const trap = createModalFocusTrap(ctx.modal);
        trap.activate({ initialFocus: ctx.cancelBtn, onEscape });
        const preventDefault = vi.fn();
        ctx.doc._fire('keydown', { key: 'a', preventDefault });
        expect(onEscape).not.toHaveBeenCalled();
        expect(preventDefault).not.toHaveBeenCalled();
        expect(ctx.doc.activeElement).toBe(ctx.cancelBtn);
    });
});
