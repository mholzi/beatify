/**
 * #1402 B7 — consolidated modal Escape-close registry.
 *
 * admin.js used to wire three separate document keydown listeners (QR / rematch
 * / join, the last also handling end-game). They are replaced by one registry +
 * one handler in admin/modal-escape.js. These tests assert the contract:
 *   - Escape closes only the TOPMOST visible registered modal (one dismissal).
 *   - reverse registration order → most recently registered visible modal wins.
 *   - hidden modals are skipped; nothing fires when none is visible.
 *   - setupModalEscapeHandler ignores non-Escape keys and delegates to the
 *     same closeTopmostModal logic.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
    registerModalClose,
    closeTopmostModal,
    setupModalEscapeHandler,
    _resetModalCloseHandlers,
} from '../admin/modal-escape.js';

// Minimal fake document: a map of id → { hidden: bool }.
function makeDoc(modals) {
    return {
        _modals: modals,
        getElementById(id) {
            const m = modals[id];
            if (!m) return null;
            return { classList: { contains: (c) => c === 'hidden' && m.hidden } };
        },
        _keydownHandlers: [],
        addEventListener(type, fn) {
            if (type === 'keydown') this._keydownHandlers.push(fn);
        },
        fireKey(key) {
            this._keydownHandlers.forEach((fn) => fn({ key }));
        },
    };
}

beforeEach(() => {
    _resetModalCloseHandlers();
});

describe('closeTopmostModal (#1402 B7)', () => {
    it('closes only the topmost (last-registered) visible modal', () => {
        const closes = { a: vi.fn(), b: vi.fn() };
        registerModalClose('modal-a', closes.a);
        registerModalClose('modal-b', closes.b);
        const doc = makeDoc({ 'modal-a': { hidden: false }, 'modal-b': { hidden: false } });

        const closed = closeTopmostModal(doc);
        expect(closed).toBe(true);
        // modal-b registered later → it is the topmost, only it closes.
        expect(closes.b).toHaveBeenCalledTimes(1);
        expect(closes.a).not.toHaveBeenCalled();
    });

    it('skips hidden modals and closes the first visible one', () => {
        const closes = { a: vi.fn(), b: vi.fn() };
        registerModalClose('modal-a', closes.a);
        registerModalClose('modal-b', closes.b);
        const doc = makeDoc({ 'modal-a': { hidden: false }, 'modal-b': { hidden: true } });

        expect(closeTopmostModal(doc)).toBe(true);
        expect(closes.b).not.toHaveBeenCalled(); // hidden → skipped
        expect(closes.a).toHaveBeenCalledTimes(1);
    });

    it('returns false and fires nothing when no registered modal is visible', () => {
        const close = vi.fn();
        registerModalClose('modal-a', close);
        const doc = makeDoc({ 'modal-a': { hidden: true } });
        expect(closeTopmostModal(doc)).toBe(false);
        expect(close).not.toHaveBeenCalled();
    });

    it('ignores ids that are not in the DOM', () => {
        const close = vi.fn();
        registerModalClose('missing-modal', close);
        const doc = makeDoc({});
        expect(closeTopmostModal(doc)).toBe(false);
        expect(close).not.toHaveBeenCalled();
    });
});

describe('setupModalEscapeHandler (#1402 B7)', () => {
    it('wires a single keydown listener that closes the topmost modal on Escape only', () => {
        const close = vi.fn();
        registerModalClose('modal-a', close);
        const doc = makeDoc({ 'modal-a': { hidden: false } });

        setupModalEscapeHandler(doc);
        expect(doc._keydownHandlers).toHaveLength(1); // exactly one listener

        doc.fireKey('Enter');
        expect(close).not.toHaveBeenCalled(); // non-Escape ignored

        doc.fireKey('Escape');
        expect(close).toHaveBeenCalledTimes(1);
    });
});
