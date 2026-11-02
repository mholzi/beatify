/**
 * #3391 — the name field: rejected mark, and the last name offered again.
 */
import { describe, it, expect, beforeEach } from 'vitest';

const store = {};
global.sessionStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};

const {
    markNameRejected, clearNameRejected,
    rememberLastName, getLastNameSuggestion, prefillNameSuggestion,
} = await import('../name-field.js');

function makeInput(value = '') {
    const attrs = {};
    const classes = new Set();
    return {
        value,
        focused: false,
        selected: false,
        setAttribute: (k, v) => { attrs[k] = String(v); },
        removeAttribute: (k) => { delete attrs[k]; },
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        },
        focus() { this.focused = true; },
        select() { this.selected = true; },
    };
}

beforeEach(() => { Object.keys(store).forEach((k) => delete store[k]); });

describe('markNameRejected / clearNameRejected', () => {
    it('marks, focuses and selects the field so the guest types over it', () => {
        const input = makeInput('Jana');
        markNameRejected(input);
        expect(input.getAttribute('aria-invalid')).toBe('true');
        expect(input.classList.contains('name-input--invalid')).toBe(true);
        expect(input.focused).toBe(true);
        expect(input.selected).toBe(true);
    });

    it('clears the mark again', () => {
        const input = makeInput('Jana');
        markNameRejected(input);
        clearNameRejected(input);
        expect(input.getAttribute('aria-invalid')).toBeNull();
        expect(input.classList.contains('name-input--invalid')).toBe(false);
    });

    it('tolerates a missing field', () => {
        expect(() => markNameRejected(null)).not.toThrow();
        expect(() => clearNameRejected(null)).not.toThrow();
    });
});

describe('last name for a rematch (session only)', () => {
    it('lives in sessionStorage, not localStorage', () => {
        rememberLastName('Jana');
        expect(store.beatify_last_name).toBe('Jana');
        expect(getLastNameSuggestion()).toBe('Jana');
    });

    it('fills an empty field and never overwrites typed text', () => {
        rememberLastName('Jana');
        const empty = makeInput('');
        expect(prefillNameSuggestion(empty)).toBe(true);
        expect(empty.value).toBe('Jana');
        const typed = makeInput('Ben');
        expect(prefillNameSuggestion(typed)).toBe(false);
        expect(typed.value).toBe('Ben');
    });

    it('does nothing without a remembered name', () => {
        const input = makeInput('');
        expect(prefillNameSuggestion(input)).toBe(false);
        expect(input.value).toBe('');
    });

    it('survives a storage that throws (private mode)', () => {
        const saved = global.sessionStorage;
        global.sessionStorage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
        expect(() => rememberLastName('X')).not.toThrow();
        expect(getLastNameSuggestion()).toBeNull();
        global.sessionStorage = saved;
    });
});
