/**
 * Unit tests for player-tour.js (Player onboarding v2).
 * Focused on pure decision logic — DOM-heavy flows are exercised manually
 * via the design-consultation preview + live QA.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ------------------------------------------------------------------
// Minimal browser-global stubs — vitest runs in node env.
// Must be set BEFORE the dynamic import below so the module's
// top-level `var utils = window.BeatifyUtils || {};` doesn't throw.
// ------------------------------------------------------------------
const memoryStore = {};
const localStorageStub = {
    getItem: (k) => (k in memoryStore ? memoryStore[k] : null),
    setItem: (k, v) => { memoryStore[k] = String(v); },
    removeItem: (k) => { delete memoryStore[k]; },
    clear: () => { Object.keys(memoryStore).forEach((k) => delete memoryStore[k]); },
};
global.window = {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: false }),
};
global.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
};
global.localStorage = localStorageStub;
global.WebSocket = class MockWS { static OPEN = 1; };

// Stub the player-utils dependency so we don't pull in real DOM code.
vi.mock('../player-utils.js', () => ({
    state: { ws: null, playerName: 'Markus' },
    showView: vi.fn(),
}));

// Dynamic import AFTER globals are in place.
const { shouldShowTour, isActive } = await import('../player-tour.js');

// ------------------------------------------------------------------
// shouldShowTour — gating logic for post-QR onboarding tour
// ------------------------------------------------------------------
describe('shouldShowTour', () => {
    beforeEach(() => {
        localStorageStub.clear();
    });

    it('returns false when currentPlayer is null/undefined', () => {
        expect(shouldShowTour(null)).toBe(false);
        expect(shouldShowTour(undefined)).toBe(false);
    });

    it('returns false for admin players regardless of other flags', () => {
        expect(shouldShowTour({ is_admin: true, onboarded: false })).toBe(false);
    });

    it('returns false when the server already flagged the player as onboarded', () => {
        expect(shouldShowTour({ is_admin: false, onboarded: true })).toBe(false);
    });

    it('returns true for a fresh non-admin player with no localStorage flag', () => {
        expect(shouldShowTour({ is_admin: false, onboarded: false })).toBe(true);
    });

    it('returns false when localStorage flag is set (returning player short-circuit)', () => {
        localStorageStub.setItem('beatify_onboarded_v2', '1');
        expect(shouldShowTour({ is_admin: false, onboarded: false })).toBe(false);
    });

    it('treats any truthy-but-not-"1" flag value as "not set" for strictness', () => {
        // Only exact '1' short-circuits — protects against legacy junk values
        localStorageStub.setItem('beatify_onboarded_v2', 'true');
        expect(shouldShowTour({ is_admin: false, onboarded: false })).toBe(true);
    });
});

// ------------------------------------------------------------------
// Module lifecycle
// ------------------------------------------------------------------
describe('tour module lifecycle', () => {
    it('reports inactive before startTour is called', () => {
        expect(isActive()).toBe(false);
    });
});
